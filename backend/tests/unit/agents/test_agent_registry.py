"""Tests for AgentRegistry and integration with existing agents."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.agents.definition import AgentDefinition
from app.agents.agents.protocol import AgentRequest, AgentResult
from app.agents.agents.registry import AgentRegistry


class TestAgentRegistry:
    """Test AgentRegistry functionality."""

    @pytest.fixture
    def registry(self):
        return AgentRegistry()

    def test_get_definition_not_found(self, registry):
        result = registry.get_definition("nonexistent_agent")
        assert result is None

    def test_get_schemas_empty(self, registry):
        schemas = registry.get_schemas(capability_type="nonexistent")
        assert schemas == []

    def test_convert_to_definition(self, registry):
        from app.agents.skills.parser import SkillMDDocument

        doc = SkillMDDocument(
            skill_id="test_agent",
            name="Test",
            capability_type="agent",
            description="Test agent",
            executor="app.test:TestAgent.run",
            input_schema={"type": "object"},
            output_summary="test",
            suitable_scenarios=[],
            workflow_steps=[],
            raw_markdown="",
            frontmatter={
                "temperature": 0.5,
                "max_rounds": 15,
                "permission_mode": "auto",
                "memory": {"namespace": "test_ns"},
            },
        )
        definition = registry._convert_to_definition(doc)
        assert definition.skill_id == "test_agent"
        assert definition.temperature == 0.5
        assert definition.max_rounds == 15
        assert definition.permission_mode == "auto"
        assert definition.memory.namespace == "test_ns"
        assert definition.is_agent()

    def test_circuit_breaker_management(self, registry):
        cb1 = registry._get_circuit_breaker("agent_a")
        cb2 = registry._get_circuit_breaker("agent_a")
        assert cb1 is cb2

        cb3 = registry._get_circuit_breaker("agent_b")
        assert cb3 is not cb1

    @pytest.mark.asyncio
    async def test_execute_agent_not_found(self, registry):
        request = AgentRequest(
            agent_id="nonexistent",
            task_description="test",
            parent_session_id="sess_1",
        )
        result = await registry.execute_agent(request)
        assert not result.success
        assert "未定义" in result.summary
        assert result.error == "agent_not_found: nonexistent"

    @pytest.mark.asyncio
    async def test_execute_with_fallback(self, registry):
        request = AgentRequest(
            agent_id="nonexistent_primary",
            task_description="test",
            parent_session_id="sess_1",
        )
        result = await registry.execute_with_fallback(
            request,
            fallback_agents=["nonexistent_fallback"],
        )
        assert not result.success
        assert "所有可用 Agent 均执行失败" in result.summary
        assert "all_agents_failed" in result.error

    @pytest.mark.asyncio
    async def test_legacy_execute_interface(self, registry):
        """Test backward-compatible execute() interface."""
        result = await registry.execute(
            name="nonexistent",
            arguments={"user_request": "test request"},
            session_id="sess_1",
        )
        assert result["agent"] == "nonexistent"
        assert not result["success"]
        assert result["error"] == "agent_not_found: nonexistent"

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self, registry):
        """Test that open circuit breaker returns failure."""
        from app.agents.agents.circuit_breaker import CircuitBreakerOpen

        # Mock execute_agent to raise CircuitBreakerOpen
        registry._circuit_breakers["test_agent"] = MagicMock()
        registry._circuit_breakers["test_agent"].call.side_effect = CircuitBreakerOpen("open")

        # Mock get_definition to return something
        registry._agent_cache["test_agent"] = AgentDefinition(
            skill_id="test_agent",
            name="Test",
            capability_type="agent",
            description="Test",
        )

        request = AgentRequest(
            agent_id="test_agent",
            task_description="test",
            parent_session_id="sess_1",
        )
        result = await registry.execute_agent(request)
        assert not result.success
        assert "熔断器打开" in result.summary
        assert result.error == "circuit_breaker_open"


class TestAgentRegistryIntegration:
    """Integration tests with real .md definitions."""

    def test_trade_agent_definition_parsing(self):
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        doc = parser.get_document("trade_workflow")

        if doc:  # Skip if .md not found in test environment
            registry = AgentRegistry(parser)
            definition = registry.get_definition("trade_workflow")
            assert definition is not None
            assert definition.is_agent()
            assert definition.max_rounds == 10
            assert definition.permission_mode == "plan"
            assert definition.memory.namespace == "trade"
            assert "asset_manage" in definition.tools

    def test_qa_agent_definition_parsing(self):
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        doc = parser.get_document("qa_research")

        if doc:
            registry = AgentRegistry(parser)
            definition = registry.get_definition("qa_research")
            assert definition is not None
            assert definition.is_agent()
            assert definition.temperature == 0.3
            assert definition.permission_mode == "auto"
            assert definition.memory.namespace == "qa"

    def test_schema_backward_compatibility(self):
        """Test that get_subagent_schemas works as alias."""
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        registry = AgentRegistry(parser)

        # get_subagent_schemas should be an alias for get_agent_schemas
        agent_schemas = registry.get_agent_schemas()
        subagent_schemas = registry.get_subagent_schemas()
        assert agent_schemas == subagent_schemas

    def test_get_schemas_l1(self):
        """Test that get_schemas(level='l1') returns lightweight schemas."""
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        registry = AgentRegistry(parser)

        l1_schemas = registry.get_schemas(level="l1")
        l2_schemas = registry.get_schemas(level="l2")

        # Both should return same number of schemas
        assert len(l1_schemas) == len(l2_schemas)

        if l1_schemas:
            for schema in l1_schemas:
                # L1 should only have lightweight fields
                assert set(schema.keys()) <= {
                    "name", "display_name", "capability_type", "description", "tools"
                }
                assert "workflow_steps" not in schema
                assert "suitable_scenarios" not in schema
                assert "parameters" not in schema

    def test_get_schemas_l2_default(self):
        """Test that default get_schemas behavior is unchanged (L2)."""
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        registry = AgentRegistry(parser)

        # Default should be L2
        schemas_default = registry.get_schemas()
        schemas_l2 = registry.get_schemas(level="l2")
        assert schemas_default == schemas_l2

        if schemas_l2:
            for schema in schemas_l2:
                # L2 should have full fields
                assert "name" in schema
                assert "display_name" in schema
                assert "capability_type" in schema
                assert "description" in schema
                # These may or may not be present depending on the doc,
                # but the schema structure should support them

    def test_get_agent_schemas_level_pass_through(self):
        """Test that get_agent_schemas passes level parameter correctly."""
        from app.agents.skills.parser import SkillMDParser

        parser = SkillMDParser()
        registry = AgentRegistry(parser)

        l1 = registry.get_agent_schemas(level="l1")
        l2 = registry.get_agent_schemas(level="l2")

        assert len(l1) == len(l2)

        if l1:
            for schema in l1:
                assert "workflow_steps" not in schema
                assert "parameters" not in schema
