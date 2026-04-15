"""
TradeAgent Nodes unit tests

Test individual node functions in isolation.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, MagicMock

import sys
from pathlib import Path

# Add backend to path
BACKEND_ROOT = Path(__file__).resolve().parents[4] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.subagents.trade.state import TradeState
from app.agents.subagents.trade.nodes.common import (
    validate_input,
    select_mechanism,
    format_result,
)


class TestValidateInput:
    """Test validate_input node"""

    @pytest.fixture
    def mock_self(self):
        """Create mock self for node methods"""
        return Mock()

    async def test_valid_listing_action(self, mock_self):
        """Test validation with valid listing action"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await validate_input(mock_self, state)

        assert result["success"] is True
        assert "error" not in result

    async def test_valid_purchase_action(self, mock_self):
        """Test validation with valid purchase action"""
        state: TradeState = {
            "action": "purchase",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "buyer",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await validate_input(mock_self, state)

        assert result["success"] is True

    async def test_missing_action(self, mock_self):
        """Test validation with missing action"""
        state: TradeState = {
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await validate_input(mock_self, state)

        assert result["success"] is False
        assert "Missing required field: action" in result["error"]

    async def test_invalid_action(self, mock_self):
        """Test validation with invalid action"""
        state: TradeState = {
            "action": "invalid_action",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await validate_input(mock_self, state)

        assert result["success"] is False
        assert "Invalid action" in result["error"]


class TestSelectMechanism:
    """Test select_mechanism node"""

    @pytest.fixture
    def mock_self(self):
        return Mock()

    async def test_mechanism_from_hint(self, mock_self):
        """Test mechanism selection from explicit hint"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "mechanism_hint": "auction",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await select_mechanism(mock_self, state)

        assert result["selected_mechanism"] == "auction"

    async def test_mechanism_from_pricing_strategy_negotiable(self, mock_self):
        """Test mechanism selection from negotiable strategy"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "pricing_strategy": "negotiable",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await select_mechanism(mock_self, state)

        assert result["selected_mechanism"] == "bilateral"

    async def test_mechanism_from_pricing_strategy_auction(self, mock_self):
        """Test mechanism selection from auction strategy"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "pricing_strategy": "auction",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await select_mechanism(mock_self, state)

        assert result["selected_mechanism"] == "auction"

    async def test_default_mechanism(self, mock_self):
        """Test default mechanism when no hint provided"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await select_mechanism(mock_self, state)

        assert result["selected_mechanism"] == "bilateral"

    async def test_returns_early_on_error(self, mock_self):
        """Test that node returns early when success is False"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": False,
            "error": "Previous error",
            "started_at": datetime.now(timezone.utc),
            "result": {},
        }

        result = await select_mechanism(mock_self, state)

        # Should return unchanged state
        assert result["success"] is False
        assert result["error"] == "Previous error"


class TestFormatResult:
    """Test format_result node"""

    @pytest.fixture
    def mock_self(self):
        return Mock()

    async def test_adds_completed_at(self, mock_self):
        """Test that completed_at is added"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {"status": "done"},
        }

        result = await format_result(mock_self, state)

        assert "completed_at" in result
        assert isinstance(result["completed_at"], datetime)

    async def test_creates_result_if_missing(self, mock_self):
        """Test that result dict is created if missing"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
        }

        result = await format_result(mock_self, state)

        assert "result" in result
        assert result["result"]["success"] is True

    async def test_preserves_existing_result(self, mock_self):
        """Test that existing result is preserved"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.now(timezone.utc),
            "result": {"custom_key": "custom_value"},
        }

        result = await format_result(mock_self, state)

        assert result["result"]["custom_key"] == "custom_value"

    async def test_returns_early_on_error(self, mock_self):
        """Test that node returns early when success is False"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": False,
            "error": "Something failed",
            "started_at": datetime.now(timezone.utc),
        }

        result = await format_result(mock_self, state)

        # completed_at should still be added even on error
        assert "completed_at" in result
