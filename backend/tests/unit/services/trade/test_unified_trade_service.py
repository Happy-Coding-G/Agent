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
