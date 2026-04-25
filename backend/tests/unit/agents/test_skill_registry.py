"""Tests for SkillRegistry skill execution layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.skills.registry import (
    SkillRegistry,
    execute_skill_md,
    _resolve_executor,
    MarketTrendInput,
    AuditReportInput,
    PrivacyProtocolInput,
)


class TestResolveExecutor:
    """Test executor path resolution."""

    def test_resolve_valid_path(self):
        """Parse a valid executor path."""
        cls, method_name, is_async = _resolve_executor(
            "app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview"
        )
        from app.services.skills.market_analysis_skill import MarketAnalysisSkill

        assert cls is MarketAnalysisSkill
        assert method_name == "get_market_overview"
        assert is_async is True

    def test_resolve_invalid_path_missing_colon(self):
        """Reject path without colon separator."""
        with pytest.raises(ValueError, match="missing ':'"):
            _resolve_executor("app.module.Class.method")

    def test_resolve_invalid_path_missing_dot(self):
        """Reject path without dot in class.method."""
        with pytest.raises(ValueError, match="missing '.'"):
            _resolve_executor("app.module:ClassMethod")


class TestExecuteSkillMd:
    """Test execute_skill_md dispatcher."""

    @pytest.mark.asyncio
    async def test_skill_not_found(self):
        """Return error when skill document is missing."""
        parser = MagicMock()
        parser.get_document.return_value = None

        result = await execute_skill_md("nonexistent", {}, MagicMock(), parser)

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_skill_no_executor(self):
        """Return error when skill has no executor configured."""
        parser = MagicMock()
        doc = MagicMock()
        doc.executor = None
        parser.get_document.return_value = doc

        result = await execute_skill_md("no_exec_skill", {}, MagicMock(), parser)

        assert result["success"] is False
        assert "no executor" in result["error"]

    @pytest.mark.asyncio
    async def test_skill_execution_success(self):
        """Successfully execute a skill via executor path."""
        parser = MagicMock()
        doc = MagicMock()
        doc.executor = (
            "app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview"
        )
        parser.get_document.return_value = doc

        db = MagicMock()
        mock_result = {"total_transactions": 100, "active_assets": 50}

        with patch(
            "app.services.skills.market_analysis_skill.MarketAnalysisSkill.get_market_overview",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await execute_skill_md("market_overview", {}, db, parser)

        assert result["success"] is True
        assert result["result"] == mock_result
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_skill_execution_with_validation(self):
        """Execute skill with Pydantic input validation."""
        parser = MagicMock()
        doc = MagicMock()
        doc.executor = (
            "app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_trend"
        )
        parser.get_document.return_value = doc

        db = MagicMock()
        mock_result = MagicMock()
        mock_result.data_type = "medical"
        mock_result.transaction_count = 10
        mock_result.avg_price = 100.0
        mock_result.price_change_pct = 0.0
        mock_result.trend = "stable"
        mock_result.top_assets = []

        with patch(
            "app.services.skills.market_analysis_skill.MarketAnalysisSkill.get_market_trend",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await execute_skill_md(
                "market_trend",
                {"data_type": "medical", "days": 7},
                db,
                parser,
            )

        assert result["success"] is True
        assert result["result"] == mock_result

    @pytest.mark.asyncio
    async def test_skill_input_validation_failure(self):
        """Return error when input validation fails."""
        parser = MagicMock()
        doc = MagicMock()
        doc.executor = (
            "app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_trend"
        )
        parser.get_document.return_value = doc

        result = await execute_skill_md(
            "market_trend",
            {"days": 999},  # exceeds max 365
            MagicMock(),
            parser,
        )

        assert result["success"] is False
        assert "validation failed" in result["error"]

    @pytest.mark.asyncio
    async def test_skill_execution_failure(self):
        """Return error when executor raises exception."""
        parser = MagicMock()
        doc = MagicMock()
        doc.executor = (
            "app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview"
        )
        parser.get_document.return_value = doc

        with patch(
            "app.services.skills.market_analysis_skill.MarketAnalysisSkill.get_market_overview",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = await execute_skill_md("market_overview", {}, MagicMock(), parser)

        assert result["success"] is False
        assert "DB connection lost" in result["error"]


class TestSkillRegistry:
    """Test SkillRegistry public interface."""

    @pytest.mark.asyncio
    async def test_registry_execute_delegates(self):
        """Registry.execute delegates to execute_skill_md."""
        db = MagicMock()
        registry = SkillRegistry(db=db)

        with patch(
            "app.agents.skills.registry.execute_skill_md",
            new_callable=AsyncMock,
            return_value={"skill": "market_overview", "success": True, "result": {}, "error": None},
        ) as mock_exec:
            result = await registry.execute("market_overview", {"days": 30})

        assert result["success"] is True
        mock_exec.assert_awaited_once()

    def test_get_skill_schemas_filters_by_type(self):
        """Schemas only include capability_type='skill' documents."""
        parser = MagicMock()
        parser.get_schemas.return_value = [
            {"name": "market_overview", "capability_type": "skill"},
            {"name": "audit_report", "capability_type": "skill"},
        ]

        registry = SkillRegistry(db=MagicMock(), parser=parser)
        schemas = registry.get_skill_schemas(level="l1")

        assert len(schemas) == 2
        parser.get_schemas.assert_called_once_with(capability_type="skill", level="l1")


class TestSkillInputModels:
    """Test Pydantic input models for strict validation."""

    def test_market_trend_input_defaults(self):
        """MarketTrendInput uses sensible defaults."""
        inp = MarketTrendInput()
        assert inp.days == 30
        assert inp.data_type is None

    def test_market_trend_input_validates_days_range(self):
        """MarketTrendInput enforces days range 1-365."""
        with pytest.raises(Exception):
            MarketTrendInput(days=0)
        with pytest.raises(Exception):
            MarketTrendInput(days=366)

    def test_audit_report_input_requires_transaction_id(self):
        """AuditReportInput requires transaction_id."""
        with pytest.raises(Exception):
            AuditReportInput()

        inp = AuditReportInput(transaction_id="tx_123")
        assert inp.transaction_id == "tx_123"
        assert inp.days == 30

    def test_privacy_protocol_input_requires_fields(self):
        """PrivacyProtocolInput requires asset_id and sensitivity."""
        with pytest.raises(Exception):
            PrivacyProtocolInput()

        inp = PrivacyProtocolInput(asset_id="a1", sensitivity="high")
        assert inp.asset_id == "a1"
        assert inp.sensitivity == "high"
