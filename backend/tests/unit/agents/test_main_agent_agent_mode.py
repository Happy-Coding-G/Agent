"""Integration tests: MainAgent -> AgentRegistry -> AgentSession."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.core import MainAgent, MainAgentState, AgentType, TaskStatus
from app.agents.core.prompts import CAPABILITY_ROUTING_SYSTEM_PROMPT


class TestMainAgentAgentExecution:
    """Test MainAgent's new agent execution path."""

    @pytest.fixture
    def main_agent(self):
        mock_db = MagicMock()
        mock_llm = AsyncMock()
        agent = MainAgent(db=mock_db, llm_client=mock_llm)
        return agent

    @pytest.mark.asyncio
    async def test_build_context_summary(self, main_agent):
        state: MainAgentState = {
            "user_request": "What is X?",
            "session_id": "sess_1",
            "user_id": 1,
            "intent": AgentType.QA,
            "conversation_history": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ],
        }
        summary = await main_agent._build_context_summary(state)
        assert "What is X?" in summary
        assert "qa" in summary
        assert "Hello" in summary

    @pytest.mark.asyncio
    async def test_build_context_summary_no_history(self, main_agent):
        state: MainAgentState = {
            "user_request": "Simple query",
            "session_id": "sess_1",
            "user_id": 1,
        }
        summary = await main_agent._build_context_summary(state)
        assert "Simple query" in summary

    @pytest.mark.asyncio
    async def test_execute_subagent_not_found(self, main_agent):
        state: MainAgentState = {
            "active_subagent_call": {"name": "nonexistent", "arguments": {}},
            "session_id": "sess_1",
            "user_id": 1,
        }
        # Mock user lookup
        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        main_agent._db.execute = AsyncMock(return_value=mock_result)

        result = await main_agent._execute_subagent(state)
        # Subagent not found should be recorded in subagent_results
        sr = result.get("subagent_results", [])
        assert len(sr) > 0
        assert any("agent_not_found" in (r.get("error") or "") for r in sr)

    def test_routing_prompt_format(self):
        """Test that routing prompt accepts new schema placeholders."""
        prompt = CAPABILITY_ROUTING_SYSTEM_PROMPT.format(
            tool_schemas="[]",
            skill_schemas="[]",
            agent_schemas='[{"name": "qa", "capability_type": "agent"}]',
            user_id=1,
            space_id="space_1",
        )
        assert "subagent" in prompt
        assert "tool" in prompt
        assert "skill" in prompt

    @pytest.mark.asyncio
    async def test_plan_step_uses_l1_schemas(self, main_agent):
        """Test that _plan_step injects L1 lightweight schemas into the prompt."""
        from unittest.mock import patch

        state: MainAgentState = {
            "user_request": "What is X?",
            "space_id": "space_1",
            "user_id": 1,
            "session_id": "sess_1",
        }

        # Mock user lookup
        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        main_agent._db.execute = AsyncMock(return_value=mock_result)

        # Mock LLM to return a direct answer
        mock_response = MagicMock()
        mock_response.content = '{"decision": {"mode": "direct", "answer": "X is a variable"}}'
        main_agent._llm_client.ainvoke = AsyncMock(return_value=mock_response)

        # Patch registries to return controlled schemas
        mock_tool_registry = MagicMock()
        mock_tool_registry.get_tool_schemas.return_value = [
            {"name": "search", "capability_type": "tool", "description": "search tool"}
        ]

        mock_skill_registry = MagicMock()
        mock_skill_registry.get_skill_schemas.return_value = [
            {"name": "pricing", "capability_type": "skill", "description": "pricing skill"}
        ]

        mock_agent_registry = MagicMock()
        mock_agent_registry.get_agent_schemas.return_value = [
            {"name": "qa", "capability_type": "agent", "description": "qa agent"}
        ]

        with patch.object(main_agent, "_get_tool_registry", return_value=mock_tool_registry):
            with patch.object(main_agent, "_get_skill_registry", return_value=mock_skill_registry):
                with patch.object(main_agent, "_get_agent_registry", return_value=mock_agent_registry):
                    result = await main_agent._plan_step(state)

        # Verify that registries were called with level="l1"
        mock_tool_registry.get_tool_schemas.assert_called_once_with(level="l1")
        mock_skill_registry.get_skill_schemas.assert_called_once_with(level="l1")
        mock_agent_registry.get_agent_schemas.assert_called_once_with(level="l1")

        # Verify the LLM was called (meaning L1 schemas were injected)
        main_agent._llm_client.ainvoke.assert_called_once()
        call_args = main_agent._llm_client.ainvoke.call_args
        messages = call_args[0][0]
        system_msg = messages[0]
        assert "search" in system_msg.content
        assert "pricing" in system_msg.content
        assert "qa" in system_msg.content

    @pytest.mark.asyncio
    async def test_plan_step_routes_subagent_mode(self, main_agent):
        """Test that subagent mode populates the active subagent call."""
        state: MainAgentState = {
            "user_request": "请让研究 Agent 帮我分析这个问题",
            "space_id": "space_1",
            "user_id": 1,
            "session_id": "sess_1",
        }

        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        main_agent._db.execute = AsyncMock(return_value=mock_result)

        mock_response = MagicMock()
        mock_response.content = (
            '{"decision": {"mode": "subagent", "name": "qa_research", '
            '"arguments": {"query": "test"}}}'
        )
        main_agent._llm_client.ainvoke = AsyncMock(return_value=mock_response)

        mock_tool_registry = MagicMock()
        mock_tool_registry.get_tool_schemas.return_value = []

        mock_skill_registry = MagicMock()
        mock_skill_registry.get_skill_schemas.return_value = []

        mock_agent_registry = MagicMock()
        mock_agent_registry.get_agent_schemas.return_value = []

        with patch.object(main_agent, "_get_tool_registry", return_value=mock_tool_registry):
            with patch.object(main_agent, "_get_skill_registry", return_value=mock_skill_registry):
                with patch.object(main_agent, "_get_agent_registry", return_value=mock_agent_registry):
                    result = await main_agent._plan_step(state)

        assert result["decision_mode"] == "subagent"
        assert result["active_subagent_call"] == {
            "name": "qa_research",
            "arguments": {"query": "test"},
        }
        assert len(result.get("subagent_calls", [])) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("intent", "expected_name", "expected_arguments"),
        [
            (
                AgentType.REVIEW,
                "review_workflow",
                {"doc_id": "", "review_type": "standard"},
            ),
            (
                AgentType.ASSET_ORGANIZE,
                "asset_organize_workflow",
                {"asset_ids": [], "space_id": "space_1"},
            ),
            (
                AgentType.TRADE,
                "trade_workflow",
                {"action": "purchase", "space_id": "space_1", "payload": {}},
            ),
        ],
    )
    async def test_fallback_plan_routes_complex_intents_to_subagents(
        self,
        main_agent,
        intent,
        expected_name,
        expected_arguments,
    ):
        state: MainAgentState = {
            "user_request": "请帮我处理复杂工作流",
            "space_id": "space_1",
            "tool_calls": [],
            "subagent_calls": [],
        }

        result = await main_agent._fallback_plan(state, MagicMock(), intent)

        assert result["active_subagent_call"] == {
            "name": expected_name,
            "arguments": expected_arguments,
        }
        assert result.get("subagent_calls") == [result["active_subagent_call"]]
        assert result.get("active_tool") is None

    def test_extract_routing_decision_rejects_agent_alias(self, main_agent):
        content = '{"decision": {"mode": "agent", "name": "qa_research", "arguments": {}}}'
        assert main_agent._extract_routing_decision(content) is None

    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ({"error": "boom", "active_tool": {"name": "search"}}, "error"),
            (
                {
                    "active_tool": {"name": "search"},
                    "active_skill": {"name": "pricing"},
                    "active_subagent_call": {"name": "qa_research"},
                },
                "tool",
            ),
            (
                {
                    "active_skill": {"name": "pricing"},
                    "active_subagent_call": {"name": "qa_research"},
                },
                "skill",
            ),
            ({"active_subagent_call": {"name": "qa_research"}}, "subagent"),
            ({}, "direct"),
        ],
    )
    def test_plan_router_precedence(self, main_agent, state, expected):
        assert main_agent._plan_router(state) == expected

    @pytest.mark.asyncio
    async def test_graph_retries_once_then_fails(self, main_agent):
        initial_state: MainAgentState = {
            "user_request": "请帮我处理这个请求",
            "space_id": "space_1",
            "user_id": None,
            "session_id": "sess_retry",
            "intent": None,
            "active_subagent": None,
            "subagent_result": None,
            "task_id": "task_retry",
            "task_status": TaskStatus.PENDING,
            "task_result": None,
            "conversation_history": [],
            "context": {},
            "error": None,
            "retry_count": 0,
            "tool_calls": [],
            "tool_results": [],
            "active_tool": None,
            "skill_calls": [],
            "skill_results": [],
            "active_skill": None,
            "subagent_calls": [],
            "subagent_results": [],
            "active_subagent_call": None,
            "decision_mode": None,
            "final_answer": None,
        }

        final_state = await main_agent.graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "task_retry"}},
        )

        assert final_state["retry_count"] == 1
        assert final_state["task_status"] == TaskStatus.FAILED
        assert "User not found" in final_state["task_result"]["answer"]


class TestMainAgentRespondStep:
    """Test MainAgent's respond step with new AgentResult format."""

    @pytest.fixture
    def main_agent(self):
        mock_db = MagicMock()
        mock_llm = AsyncMock()
        agent = MainAgent(db=mock_db, llm_client=mock_llm)
        return agent

    @pytest.mark.asyncio
    async def test_respond_with_subagent_result(self, main_agent):
        # Mock LLM to return a fixed response
        mock_response = MagicMock()
        mock_response.content = "X is a variable"
        main_agent._llm_client.ainvoke = AsyncMock(return_value=mock_response)

        state: MainAgentState = {
            "user_request": "What is X?",
            "subagent_results": [
                {
                    "subagent": "qa_research",
                    "success": True,
                    "summary": "X is a variable",
                    "artifacts": [],
                    "error": None,
                    "sidechain_id": "sess_1:qa_research",
                }
            ],
        }
        result = await main_agent._respond_step(state)
        assert result["task_status"] == TaskStatus.COMPLETED
        assert "X is a variable" in result["task_result"]["answer"]

    @pytest.mark.asyncio
    async def test_respond_with_failed_subagent(self, main_agent):
        main_agent._llm_client = None  # Force simple summary
        state: MainAgentState = {
            "user_request": "What is X?",
            "subagent_results": [
                {
                    "subagent": "qa_research",
                    "success": False,
                    "summary": "",
                    "error": "Database error",
                    "sidechain_id": "",
                }
            ],
        }
        result = await main_agent._respond_step(state)
        assert result["task_status"] == TaskStatus.COMPLETED
        assert "qa_research" in result["task_result"]["answer"]

    @pytest.mark.asyncio
    async def test_respond_includes_tool_and_skill_results_in_llm_prompt(self, main_agent):
        mock_response = MagicMock()
        mock_response.content = "已经完成检索和分析。"
        main_agent._llm_client.ainvoke = AsyncMock(return_value=mock_response)

        state: MainAgentState = {
            "user_request": "帮我先检索再报价",
            "tool_results": [{"tool": "search", "result": {"hits": 2}}],
            "skill_results": [
                {
                    "skill": "pricing_quick_quote",
                    "result": {"price": 128, "currency": "CNY"},
                }
            ],
            "subagent_results": [],
        }

        result = await main_agent._respond_step(state)

        prompt = main_agent._llm_client.ainvoke.call_args[0][0]
        assert "search" in prompt
        assert "hits" in prompt
        assert "pricing_quick_quote" in prompt
        assert "price" in prompt
        assert result["task_result"]["answer"] == "已经完成检索和分析。"
