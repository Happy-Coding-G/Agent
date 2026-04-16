"""
Tests for TradeService purchase_negotiated.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade.trade_service import TradeService


class TestPurchaseNegotiated:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def trade_service(self, mock_db):
        with patch(
            "app.services.trade.trade_service.AssetService"
        ), patch(
            "app.services.trade.trade_service.TradeRepository"
        ) as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo_cls.return_value = mock_repo
            service = TradeService(mock_db)
            service._repo = mock_repo
            return service

    @pytest.mark.asyncio
    async def test_purchase_negotiated_uses_agreed_price(self, trade_service, mock_db):
        mock_buyer = MagicMock()
        mock_buyer.id = 1

        mock_listing = MagicMock()
        mock_listing.status = "active"
        mock_listing.seller_user_id = 2
        mock_listing.price_credits = 10000  # 100 credits
        mock_listing.public_id = "lst_123"
        mock_listing.title = "Test Asset"
        mock_listing.seller_alias = "seller-abc"
        mock_listing.asset_id = "ast_1"
        mock_listing.space_public_id = "sp_1"
        mock_listing.delivery_payload_encrypted = b'{}'
        mock_listing.rights_template = {}

        mock_wallet = MagicMock()
        mock_wallet.liquid_credits = 50000  # 500 credits

        trade_service._repo.get_holding_by_listing = AsyncMock(return_value=None)
        trade_service._repo.get_listing_by_public_id = AsyncMock(return_value=mock_listing)
        trade_service._repo.get_wallet = AsyncMock(return_value=mock_wallet)
        trade_service._repo.debit_wallet = AsyncMock()
        trade_service._repo.credit_wallet = AsyncMock()
        trade_service._repo.update_listing_stats = AsyncMock()
        trade_service._repo.create_order = AsyncMock(return_value=MagicMock(
            public_id="ord_123",
            price_credits=8000,
            platform_fee=400,
            seller_income=7600,
            status="completed",
            created_at=None,
            completed_at=None,
        ))
        trade_service._repo.create_holding = AsyncMock(return_value=MagicMock(
            id=1,
            order_id="ord_123",
            listing_id="lst_123",
            asset_title="Test Asset",
            seller_alias="seller-abc",
            purchased_at=None,
            download_count=0,
            last_accessed_at=None,
        ))
        trade_service._repo.create_rights_transaction = AsyncMock(return_value=MagicMock(
            transaction_id="rt_123"
        ))

        with patch("app.services.trade.trade_service.LineageService") as mock_lineage_cls:
            mock_lineage = AsyncMock()
            mock_lineage_cls.return_value = mock_lineage

            result = await trade_service.purchase_negotiated(
                listing_id="lst_123",
                buyer=mock_buyer,
                agreed_price_credits=80.0,  # 协商价格 80 credits
            )

            assert result["status"] == "completed"
            trade_service._repo.create_order.assert_awaited_once()
            # 验证 override_price_cents 传入的是协商价 80 * 100 = 8000 cents
            call_kwargs = trade_service._repo.create_order.await_args.kwargs
            assert call_kwargs.get("override_price_cents") == 8000

            # 验证买方被扣款 80 credits (8000 cents -> 80.0 credits)
            debit_call = trade_service._repo.debit_wallet.await_args
            assert debit_call.kwargs["amount_credits"] == 80.0
