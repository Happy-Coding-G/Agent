"""
Unified Trade Service - Facade Layer

薄 facade，将调用委托给 TradeService（直接交易）。
已删除协商、拍卖、托管相关委托。
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Users
from app.services.trade.trade_service import TradeService


class UnifiedTradeService:
    """
    统一交易服务 Facade

    当前仅支持直接交易（direct trade）。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._trade = TradeService(db)

    # =================================================================
    # TradeService 委托
    # =================================================================

    async def purchase(self, listing_id: str, buyer: Users) -> Dict[str, Any]:
        """直接购买"""
        return await self._trade.purchase(listing_id=listing_id, buyer=buyer)

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        price_credits: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """创建资产上架"""
        return await self._trade.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            price_credits=price_credits,
            **kwargs
        )

    async def get_wallet(self, user_id: int) -> Dict[str, Any]:
        """获取用户钱包"""
        return await self._trade.get_wallet(user_id)
