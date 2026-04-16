"""
Tests for Agent-First trade nodes.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.agents.subagents.trade.nodes.agent_first import (
    create_session,
    evaluate_risk,
    check_approval,
)
from app.agents.subagents.trade.state import TradeState


class MockSelf:
    def __init__(self):
        self.db = AsyncMock()
        self.assets = AsyncMock()
        self.skills = {}


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_session_buy_asset_auction_uses_listing_seller(self):
        """
        buy_asset + auction: seller_id 必须查询 TradeListings.seller_user_id
        """
        mock_self = MockSelf()
        mock_listing = MagicMock()
        mock_listing.seller_user_id = 42

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_listing
            return result

        mock_self.db.execute = mock_execute

        with patch(
            "app.services.trade.hybrid_negotiation_service.HybridNegotiationService",
            create_mock_hybrid,
        ):
            state: TradeState = {
                "success": True,
                "selected_mechanism": "auction",
                "engine_type": "event_sourced",
                "trade_goal": {
                    "intent": "buy_asset",
                    "listing_id": "lst_123",
                    "min_price": 100.0,
                },
                "user_id": 7,
                "decisions": [],
            }
            result = await create_session(mock_self, state)
            assert result.get("session_id") == "sess_123"


def create_mock_hybrid(db):
    mock = MagicMock()
    async def async_create_negotiation(**kwargs):
        assert kwargs["seller_id"] == 42, "seller_id should come from listing, not user_id"
        assert kwargs["buyer_id"] == 7
        return {"session_id": "sess_123"}
    mock.create_negotiation = async_create_negotiation
    return mock


class TestEvaluateRisk:
    @pytest.mark.asyncio
    async def test_evaluate_risk_first_time_buyer(self):
        mock_self = MockSelf()

        async def mock_execute(stmt):
            result = MagicMock()
            # 模拟 0 笔 completed，0 笔 failed
            result.scalar.return_value = 0
            return result

        mock_self.db.execute = mock_execute

        state: TradeState = {
            "trade_goal": {"target_price": 500.0, "urgency": "low"},
            "trade_constraints": {},
            "user_id": 1,
            "user_config": {"auto_negotiate": True},
            "decisions": [],
        }
        result = await evaluate_risk(mock_self, state)
        risk = result.get("risk_context", {})
        assert risk.get("is_first_transaction") is True
        assert risk.get("user_trust_score") == pytest.approx(0.3)


class TestCheckApproval:
    @pytest.mark.asyncio
    async def test_check_approval_persists_decision(self):
        mock_self = MockSelf()
        mock_task = MagicMock()
        mock_task.status = "running"
        mock_task.output_data = {}

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_task
            return result

        mock_self.db.execute = mock_execute
        mock_self.db.commit = AsyncMock()

        with patch(
            "app.services.trade.approval_policy_service.ApprovalPolicyService"
        ) as mock_policy_cls:
            mock_decision = MagicMock()
            mock_decision.requires_approval = True
            mock_decision.reason = "First transaction requires approval"
            mock_decision.trigger.value = "first_transaction"
            mock_decision.policy_applied = "first_transaction"
            mock_policy_cls.evaluate_transaction.return_value = mock_decision

            state: TradeState = {
                "approval_required": True,
                "trade_goal": {
                    "intent": "buy_asset",
                    "listing_id": "lst_1",
                    "target_price": 100.0,
                },
                "trade_constraints": {},
                "risk_context": {
                    "user_trust_score": 0.3,
                    "is_first_transaction": True,
                },
                "current_step": "run_negotiation",
                "task_id": "task_123",
                "decisions": [],
            }
            result = await check_approval(mock_self, state)

            assert result.get("pending_decision") is not None
            assert result["pending_decision"]["type"] == "approval_required"
            mock_self.db.commit.assert_awaited()
            assert mock_task.status == "pending_approval"
