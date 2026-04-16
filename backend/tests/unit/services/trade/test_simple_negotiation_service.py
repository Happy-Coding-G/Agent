"""
Tests for SimpleNegotiationService respond_to_offer settlement.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade.simple_negotiation_service import SimpleNegotiationService
from app.services.trade.result_types import NegotiationStatus


class TestRespondToOfferAcceptSettles:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        return SimpleNegotiationService(mock_db)

    @pytest.mark.asyncio
    async def test_respond_to_offer_accept_settles(self, service, mock_db):
        """验证接受报价后触发真实结算"""
        from datetime import datetime, timezone

        session = MagicMock()
        session.negotiation_id = "neg_123"
        session.status = "active"
        session.buyer_user_id = 1
        session.seller_user_id = 2
        session.current_round = 2
        session.version = 1
        session.listing_id = "lst_123"
        session.agreed_price = None
        session.settlement_at = None
        session.last_activity_at = None
        session.shared_board = {
            "history": [
                {"round": 1, "action": "offer", "price": 90.0, "by": "buyer"},
                {"round": 2, "action": "offer", "price": 85.0, "by": "seller"},
            ],
            "current_offer": {"price": 85.0},
        }

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute

        mock_buyer = MagicMock()
        mock_buyer.id = 1

        with patch.object(service, "_get_user", new_callable=AsyncMock) as mock_get_user:
            mock_get_user.return_value = mock_buyer

            with patch(
                "app.services.trade.simple_negotiation_service.TradeService"
            ) as mock_trade_cls:
                mock_trade_instance = MagicMock()
                mock_trade_cls.return_value = mock_trade_instance
                mock_trade_instance.purchase_negotiated = AsyncMock(return_value={
                    "status": "completed",
                    "order": {"order_id": "ord_999"},
                })

                result = await service.respond_to_offer(
                    negotiation_id="neg_123",
                    user_id=1,  # buyer accepts seller's offer
                    response="accept",
                )

                assert result.success is True
                assert result.offer_accepted is True
                assert result.order_id == "ord_999"
                assert result.status == NegotiationStatus.ACCEPTED
                assert session.status == "accepted"
                assert session.agreed_price == 8500  # 85.0 * 100

                mock_trade_instance.purchase_negotiated.assert_awaited_once_with(
                    listing_id="lst_123",
                    buyer=mock_buyer,
                    agreed_price_credits=85.0,
                )

    @pytest.mark.asyncio
    async def test_respond_to_offer_accept_settlement_failure_rolls_back(self, service, mock_db):
        """验证结算失败时回滚协商接受状态"""
        session = MagicMock()
        session.negotiation_id = "neg_123"
        session.status = "active"
        session.buyer_user_id = 1
        session.seller_user_id = 2
        session.current_round = 2
        session.version = 1
        session.listing_id = "lst_123"
        session.agreed_price = None
        session.settlement_at = None
        session.last_activity_at = None
        session.shared_board = {
            "history": [
                {"round": 1, "action": "offer", "price": 90.0, "by": "buyer"},
            ],
            "current_offer": {"price": 90.0},
        }

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = session
            return result

        mock_db.execute = mock_execute
        mock_db.rollback = AsyncMock()

        mock_buyer = MagicMock()
        mock_buyer.id = 1

        with patch.object(service, "_get_user", new_callable=AsyncMock) as mock_get_user:
            mock_get_user.return_value = mock_buyer

            with patch(
                "app.services.trade.simple_negotiation_service.TradeService"
            ) as mock_trade_cls:
                mock_trade_instance = MagicMock()
                mock_trade_cls.return_value = mock_trade_instance
                mock_trade_instance.purchase_negotiated = AsyncMock(
                    side_effect=Exception("insufficient balance")
                )

                result = await service.respond_to_offer(
                    negotiation_id="neg_123",
                    user_id=1,
                    response="accept",
                )

                assert result.success is False
                assert "settlement failed" in result.error.lower()
                mock_db.rollback.assert_awaited_once()
