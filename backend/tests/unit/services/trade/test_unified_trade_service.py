"""
Tests for UnifiedTradeService facade.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade.unified_trade_service import UnifiedTradeService


class TestUnifiedTradeService:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        return UnifiedTradeService(mock_db)

    @pytest.mark.asyncio
    async def test_purchase_delegates_to_trade_service(self, service, mock_db):
        with patch.object(
            service._trade, "purchase", new_callable=AsyncMock
        ) as mock_purchase:
            mock_user = MagicMock()
            mock_user.id = 1
            mock_purchase.return_value = {"status": "completed"}

            result = await service.purchase("listing_123", mock_user)

            mock_purchase.assert_awaited_once_with(listing_id="listing_123", buyer=mock_user)
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_create_listing_delegates_to_trade_service(self, service, mock_db):
        with patch.object(
            service._trade, "create_listing", new_callable=AsyncMock
        ) as mock_create:
            mock_user = MagicMock()
            mock_user.id = 1
            mock_create.return_value = {"listing_id": "lst_123"}

            result = await service.create_listing(
                space_public_id="sp_1",
                asset_id="ast_1",
                user=mock_user,
                price_credits=100.0,
            )

            mock_create.assert_awaited_once()
            assert result["listing_id"] == "lst_123"

    @pytest.mark.asyncio
    async def test_create_negotiation_delegates_to_simple_service(self, service, mock_db):
        with patch.object(
            service._negotiation, "create_negotiation", new_callable=AsyncMock
        ) as mock_create:
            mock_user = MagicMock()
            mock_user.id = 1
            mock_create.return_value = {"negotiation_id": "neg_123", "success": True}

            result = await service.create_negotiation(
                listing_id="lst_1",
                buyer=mock_user,
                initial_offer=50.0,
            )

            mock_create.assert_awaited_once()
            assert result["negotiation_id"] == "neg_123"

    @pytest.mark.asyncio
    async def test_lock_funds_delegates_to_escrow_service(self, service, mock_db):
        with patch.object(
            service._escrow, "lock_funds", new_callable=AsyncMock
        ) as mock_lock:
            mock_lock.return_value = MagicMock(escrow_id="esc_123")

            result = await service.lock_funds(
                negotiation_id="neg_1",
                buyer_id=1,
                seller_id=2,
                listing_id="lst_1",
                amount=10.0,
            )

            mock_lock.assert_awaited_once()
            assert result.escrow_id == "esc_123"

    @pytest.mark.asyncio
    async def test_release_funds_delegates_to_escrow_service(self, service, mock_db):
        with patch.object(
            service._escrow, "release_to_seller", new_callable=AsyncMock
        ) as mock_release:
            mock_release.return_value = MagicMock(status="released")

            result = await service.release_funds("esc_123")

            mock_release.assert_awaited_once_with(escrow_id="esc_123")
            assert result.status == "released"

    @pytest.mark.asyncio
    async def test_place_auction_bid_not_implemented(self, service, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1

        with pytest.raises(Exception) as exc_info:
            await service.place_auction_bid("lot_1", mock_user, 100.0)

        assert "not implemented" in str(exc_info.value).lower()
