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
    async def test_execute_agent_not_found(self, main_agent):
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

        result = await main_agent._execute_agent(state)
        # Agent not found should be recorded in subagent_results
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
        assert "agent" in prompt
        assert "agent" in prompt
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


class TestMainAgentRespondStep:
    """Test MainAgent's respond step with new AgentResult format."""

    @pytest.fixture
    def main_agent(self):
        mock_db = MagicMock()
        mock_llm = AsyncMock()
        agent = MainAgent(db=mock_db, llm_client=mock_llm)
        return agent

    @pytest.mark.asyncio
    async def test_respond_with_agent_result(self, main_agent):
        # Mock LLM to return a fixed response
        mock_response = MagicMock()
        mock_response.content = "X is a variable"
        main_agent._llm_client.ainvoke = AsyncMock(return_value=mock_response)

        state: MainAgentState = {
            "user_request": "What is X?",
            "subagent_results": [
                {
                    "agent": "qa_research",
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
    async def test_respond_with_failed_agent(self, main_agent):
        main_agent._llm_client = None  # Force simple summary
        state: MainAgentState = {
            "user_request": "What is X?",
            "subagent_results": [
                {
                    "agent": "qa_research",
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
