"""
TradeAgent State unit tests

Test TradeState TypedDict definitions and type safety.
"""
import pytest
from datetime import datetime

from app.agents.subagents.trade.state import TradeState


class TestTradeState:
    """Test TradeState type definition"""

    def test_trade_state_creation(self):
        """Test creating a valid TradeState"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test-space",
            "asset_id": "test-asset",
            "user_id": 1,
            "user_role": "seller",
            "success": True,
            "started_at": datetime.utcnow(),
            "result": {},
        }

        assert state["action"] == "listing"
        assert state["space_public_id"] == "test-space"
        assert state["success"] is True

    def test_trade_state_with_optional_fields(self):
        """Test TradeState with all optional fields"""
        state: TradeState = {
            "action": "purchase",
            "space_public_id": "test-space",
            "asset_id": "asset-123",
            "user_id": 2,
            "user_role": "buyer",
            "pricing_strategy": "negotiable",
            "reserve_price": 100.0,
            "budget_max": 200.0,
            "listing_id": "listing-456",
            "bid_amount": 150.0,
            "success": True,
            "result": {"status": "pending"},
            "calculated_price": 120.0,
            "selected_mechanism": "bilateral",
            "started_at": datetime.utcnow(),
        }

        assert state["pricing_strategy"] == "negotiable"
        assert state["reserve_price"] == 100.0
        assert state["selected_mechanism"] == "bilateral"

    def test_trade_state_error_state(self):
        """Test TradeState with error"""
        state: TradeState = {
            "action": "listing",
            "space_public_id": "test",
            "user_id": 1,
            "user_role": "seller",
            "success": False,
            "error": "Invalid asset",
            "started_at": datetime.utcnow(),
            "result": {},
        }

        assert state["success"] is False
        assert state["error"] == "Invalid asset"


class TestTradeStateValidation:
    """Test TradeState validation logic"""

    def test_valid_actions(self):
        """Test all valid action types"""
        valid_actions = ["listing", "purchase", "auction_bid", "bilateral", "yield"]

        for action in valid_actions:
            state: TradeState = {
                "action": action,
                "space_public_id": "test",
                "user_id": 1,
                "user_role": "seller",
                "success": True,
                "started_at": datetime.utcnow(),
                "result": {},
            }
            assert state["action"] == action
