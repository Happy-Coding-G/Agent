"""Tests for the new AgentSession architecture."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.agents.definition import AgentDefinition, AgentMemoryConfig
from app.agents.agents.protocol import AgentRequest, AgentResult, AgentMessage
from app.agents.agents.session import AgentSession, AgentMaxRoundsError
from app.agents.agents.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from app.agents.agents.sidechain import SidechainLogger
from app.agents.agents.bus import AgentMessageBus


class TestAgentDefinition:
    """Test AgentDefinition data class."""

    def test_is_agent(self):
        d = AgentDefinition(
            skill_id="trade",
            name="Trade Agent",
            capability_type="agent",
            description="Trade agent",
        )
        assert d.is_agent()
        assert not d.is_skill()
        assert not d.is_tool()

    def test_is_skill(self):
        d = AgentDefinition(
            skill_id="pricing",
            name="Pricing",
            capability_type="skill",
            description="Pricing skill",
        )
        assert d.is_skill()
        assert not d.is_agent()

    def test_to_capability_schema(self):
        d = AgentDefinition(
            skill_id="trade",
            name="Trade Agent",
            capability_type="agent",
            description="Trade agent",
            model="deepseek-chat",
            temperature=0.2,
            max_rounds=10,
            permission_mode="plan",
            tools=["asset_search"],
            memory=AgentMemoryConfig(namespace="trade"),
        )
        schema = d.to_capability_schema()
        assert schema["name"] == "trade"
        assert schema["capability_type"] == "agent"
        assert schema["model"] == "deepseek-chat"
        assert schema["max_rounds"] == 10
        assert schema["permission_mode"] == "plan"
        assert schema["tools"] == ["asset_search"]
        assert schema["memory_namespace"] == "trade"

    def test_to_capability_schema_l1(self):
        d = AgentDefinition(
            skill_id="trade",
            name="Trade Agent",
            capability_type="agent",
            description="Trade agent",
            tools=["asset_search", "asset_manage"],
            workflow_steps=["step1", "step2"],
            suitable_scenarios=["scenario1"],
            examples=[{"input": "x", "output": "y"}],
        )
        schema = d.to_capability_schema(level="l1")
        assert set(schema.keys()) <= {"name", "display_name", "capability_type", "description", "tools"}
        assert schema["name"] == "trade"
        assert schema["display_name"] == "Trade Agent"
        assert schema["capability_type"] == "agent"
        assert schema["description"] == "Trade agent"
        assert schema["tools"] == ["asset_search", "asset_manage"]
        assert "workflow_steps" not in schema
        assert "suitable_scenarios" not in schema
        assert "examples" not in schema
        assert "parameters" not in schema

    def test_to_capability_schema_l2_default(self):
        d = AgentDefinition(
            skill_id="trade",
            name="Trade Agent",
            capability_type="agent",
            description="Trade agent",
            tools=["asset_search"],
            workflow_steps=["step1"],
            suitable_scenarios=["scenario1"],
        )
        # Default level should be "l2"
        schema = d.to_capability_schema()
        assert "workflow_steps" in schema
        assert "suitable_scenarios" in schema
        assert "parameters" in schema
        assert schema["tools"] == ["asset_search"]

    def test_to_capability_schema_l1_no_tools(self):
        d = AgentDefinition(
            skill_id="simple",
            name="Simple Agent",
            capability_type="agent",
            description="No tools",
        )
        schema = d.to_capability_schema(level="l1")
        assert "tools" not in schema
        assert schema["name"] == "simple"


class TestAgentRequestResult:
    """Test AgentRequest / AgentResult protocols."""

    def test_request_dict(self):
        req = AgentRequest(
            agent_id="qa",
            task_description="What is X?",
            arguments={"query": "What is X?"},
            parent_session_id="sess_1",
            user_id=1,
        )
        d = req.dict()
        assert d["agent_id"] == "qa"
        assert d["correlation_id"] is not None

    def test_result_dict(self):
        result = AgentResult(
            success=True,
            summary="Answer found",
            agent_id="qa",
            rounds_used=3,
            tool_calls_count=2,
        )
        d = result.dict()
        assert d["success"] is True
        assert d["summary"] == "Answer found"
        assert d["rounds_used"] == 3


class TestCircuitBreaker:
    """Test CircuitBreaker."""

    @pytest.mark.asyncio
    async def test_closed_state_success(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)

        async def success():
            return "ok"

        result = await cb.call(success())
        assert result == "ok"
        assert cb.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_open_state_blocks(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert cb.state == "OPEN"

        async def success():
            return "ok"

        with pytest.raises(CircuitBreakerOpen):
            await cb.call(success())

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert cb.state == "OPEN"

        import asyncio
        await asyncio.sleep(0.02)

        async def success():
            return "ok"

        result = await cb.call(success())
        assert result == "ok"
        assert cb.state == "CLOSED"

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.state = "OPEN"
        cb.failure_count = 5
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0


class TestSidechainLogger:
    """Test SidechainLogger."""

    def test_log_and_get_entries(self):
        logger = SidechainLogger(
            session_id="sess_1:qa",
            parent_session_id="sess_1",
            agent_id="qa",
        )
        # 同步测试内存操作
        import asyncio

        async def _test():
            await logger.log("thought", {"content": "thinking"})
            await logger.log("tool_call", {"tool": "search"})
            entries = await logger.get_entries()
            assert len(entries) == 2
            assert entries[0].event_type == "thought"
            assert entries[1].event_type == "tool_call"

        asyncio.run(_test())

    def test_get_summary(self):
        logger = SidechainLogger(
            session_id="sess_1:qa",
            parent_session_id="sess_1",
            agent_id="qa",
        )
        import asyncio

        async def _test():
            await logger.log("task_start", {})
            await logger.log("tool_call", {"tool": "search"})
            await logger.log("task_complete", {})
            summary = await logger.get_summary()
            assert "qa" in summary
            assert "1 次" in summary

        asyncio.run(_test())


class TestAgentMessageBus:
    """Test AgentMessageBus (mocked Redis)."""

    @pytest.mark.asyncio
    async def test_publish_no_redis(self):
        bus = AgentMessageBus()
        # 没有 Redis 时不应该崩溃
        msg = AgentMessage(
            type="event",
            sender="agent_1",
            topic="test",
            payload={"data": "hello"},
        )
        # mock redis
        mock_redis = AsyncMock()
        mock_redis.publish.return_value = 1
        bus._redis = mock_redis
        receivers = await bus.publish("test", msg)
        assert receivers == 1


class TestAgentSession:
    """Test AgentSession core functionality."""

    def _make_definition(self) -> AgentDefinition:
        return AgentDefinition(
            skill_id="test_agent",
            name="Test Agent",
            capability_type="agent",
            description="A test agent",
            max_rounds=3,
            tools=["mock_tool"],
        )

    @pytest.mark.asyncio
    async def test_execute_react_max_rounds(self):
        """Test that AgentSession respects max_rounds with function calling."""
        definition = self._make_definition()
        definition.executor = None  # 强制使用 ReAct 模式

        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        # Mock LLM with bind_tools support
        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "I will call a tool"
                # 始终返回 tool_calls，迫使循环继续直到 max_rounds
                response.tool_calls = [
                    {"name": "mock_tool", "args": {}, "id": "call_1"}
                ]
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        mock_llm.total_tokens = 100
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False  # 防止 finally 关闭 mock
        session.tool_registry = MagicMock()
        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = "tool result"
        session.tool_registry.get_tool.return_value = mock_tool
        session.memory = None  # 跳过记忆同步

        request = AgentRequest(
            agent_id="test_agent",
            task_description="test task",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert not result.success
        assert result.error == "max_rounds_exceeded"
        assert result.rounds_used == 3

    @pytest.mark.asyncio
    async def test_react_result_formatting(self):
        """Test ReAct result formatting."""
        definition = self._make_definition()
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        # Direct answer result
        summary = await session._summarize_result({"answer": "The answer"})
        assert "The answer" in summary
