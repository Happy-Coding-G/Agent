"""
Tests for TradeService pricing integration with AssetLineagePricingService.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade.trade_service import TradeService


class TestTradePricingIntegration:
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
    async def test_create_listing_uses_unified_pricing_when_no_price(self, trade_service, mock_db):
        """上架未传价格时调用统一定价 → recommended_price。"""
        mock_asset = {
            "asset_id": "ast_1",
            "content_markdown": "# Test\n" * 50,
            "graph_snapshot": {"node_count": 5, "edge_count": 3},
            "source_asset_ids": [],
            "summary": "Test asset",
        }

        trade_service._assets.get_asset = AsyncMock(return_value=mock_asset)
        trade_service._repo.check_rights = AsyncMock(return_value=True)
        trade_service._repo.create_listing = AsyncMock(return_value=MagicMock(
            public_id="lst_new",
            asset_id="ast_1",
            price_credits=12300,
            space_public_id="sp_1",
            seller_user_id=1,
            status="active",
            title="Test",
            seller_alias="seller",
        ))

        mock_pricing = MagicMock()
        mock_pricing.recommended_price = 123.0

        with patch(
            "app.services.trade.trade_service.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.calculate_price.return_value = mock_pricing
            mock_svc_cls.return_value = mock_svc

            result = await trade_service.create_listing(
                space_public_id="sp_1",
                asset_id="ast_1",
                user=MagicMock(id=1),
                price_credits=None,
            )

            mock_svc.calculate_price.assert_awaited_once_with("ast_1")
            assert result["price_credits"] == 123.0

    @pytest.mark.asyncio
    async def test_create_listing_uses_provided_price(self, trade_service, mock_db):
        """传入 price_credits 时不走自动定价。"""
        mock_asset = {
            "asset_id": "ast_1",
            "content_markdown": "# Test\n" * 50,
            "graph_snapshot": {"node_count": 5, "edge_count": 3},
            "source_asset_ids": [],
            "summary": "Test asset",
        }

        trade_service._assets.get_asset = AsyncMock(return_value=mock_asset)
        trade_service._repo.check_rights = AsyncMock(return_value=True)
        trade_service._repo.create_listing = AsyncMock(return_value=MagicMock(
            public_id="lst_new",
            asset_id="ast_1",
            price_credits=25000,
            space_public_id="sp_1",
            seller_user_id=1,
            status="active",
            title="Test",
            seller_alias="seller",
        ))

        with patch(
            "app.services.trade.trade_service.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc

            result = await trade_service.create_listing(
                space_public_id="sp_1",
                asset_id="ast_1",
                user=MagicMock(id=1),
                price_credits=250.0,
            )

            mock_svc.calculate_price.assert_not_awaited()
            assert result["price_credits"] == 250.0

    @pytest.mark.asyncio
    async def test_purchase_records_lineage_via_new_service(self, trade_service, mock_db):
        """交易完成后血缘记录指向新服务。"""
        mock_buyer = MagicMock()
        mock_buyer.id = 1

        mock_listing = MagicMock()
        mock_listing.status = "active"
        mock_listing.seller_user_id = 2
        mock_listing.price_credits = 10000
        mock_listing.public_id = "lst_123"
        mock_listing.title = "Test Asset"
        mock_listing.seller_alias = "seller-abc"
        mock_listing.asset_id = "ast_1"
        mock_listing.space_public_id = "sp_1"
        mock_listing.delivery_payload_encrypted = b'{}'
        mock_listing.rights_template = {}

        mock_wallet = MagicMock()
        mock_wallet.liquid_credits = 50000

        trade_service._repo.get_holding_by_listing = AsyncMock(return_value=None)
        trade_service._repo.get_listing_by_public_id = AsyncMock(return_value=mock_listing)
        trade_service._repo.get_wallet = AsyncMock(return_value=mock_wallet)
        trade_service._repo.debit_wallet = AsyncMock()
        trade_service._repo.credit_wallet = AsyncMock()
        trade_service._repo.update_listing_stats = AsyncMock()
        trade_service._repo.create_order = AsyncMock(return_value=MagicMock(
            public_id="ord_123",
            price_credits=10000,
            platform_fee=500,
            seller_income=9500,
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
        ))
        trade_service._repo.create_rights_transaction = AsyncMock(return_value=MagicMock(
            transaction_id="rt_123"
        ))

        # Mock async context manager for db.begin()
        mock_begin_ctx = AsyncMock()
        mock_begin_ctx.__aenter__ = AsyncMock(return_value=mock_begin_ctx)
        mock_begin_ctx.__aexit__ = AsyncMock(return_value=False)
        trade_service._db.begin = MagicMock(return_value=mock_begin_ctx)

        with patch(
            "app.services.trade.trade_service.AssetLineagePricingService"
        ) as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc

            await trade_service.purchase(
                listing_id="lst_123",
                buyer=mock_buyer,
            )

            mock_svc.record_lineage.assert_awaited_once()
            call_kwargs = mock_svc.record_lineage.await_args.kwargs
            assert call_kwargs["current_entity_id"] == "rt_123"
            assert call_kwargs["relationship"] == "rights_assigned"
