"""
Unified Trade Service - Facade Layer

薄 facade，将调用委托给现有交易服务：
- TradeService: 购买、上架、钱包
- SimpleNegotiationService: 双边协商
- EscrowService: 资金托管
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Users
from app.core.errors import ServiceError
from app.services.trade.trade_service import TradeService
from app.services.trade.simple_negotiation_service import SimpleNegotiationService
from app.services.safety.escrow_service import EscrowService


class UnifiedTradeService:
    """
    统一交易服务 Facade

    将前端业务动作委托给底层专业服务，不重复实现业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._trade = TradeService(db)
        self._negotiation = SimpleNegotiationService(db)
        self._escrow = EscrowService(db)

    # ======================================================================
    # TradeService 委托
    # ======================================================================

    async def purchase(self, listing_id: str, buyer: Users, purchase_type: str = "direct") -> Dict[str, Any]:
        """直接购买"""
        return await self._trade.purchase(listing_id=listing_id, buyer=buyer)

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        pricing_strategy: str = "fixed",
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

    async def place_auction_bid(
        self, lot_id: str, user: Users, amount: float
    ) -> Dict[str, Any]:
        """拍卖出价（暂未实现）"""
        raise ServiceError(501, "Auction bid not implemented yet")

    async def close_auction(self, lot_id: str, user: Users) -> Dict[str, Any]:
        """关闭拍卖（暂未实现）"""
        raise ServiceError(501, "Auction close not implemented yet")

    # ======================================================================
    # SimpleNegotiationService 委托
    # ======================================================================

    async def create_negotiation(
        self,
        listing_id: str,
        buyer: Users,
        initial_offer: float = 0,
        max_rounds: int = 10,
        message: str = "",
    ) -> Dict[str, Any]:
        """创建双边协商"""
        result = await self._negotiation.create_negotiation(
            buyer_id=buyer.id,
            listing_id=listing_id,
            requirements={
                "preferred_price": initial_offer if initial_offer else None,
                "max_rounds": max_rounds,
                "message": message,
            },
        )
        # 确保返回结果包含 negotiation_id（兼容旧接口）
        if "negotiation_id" in result and "session_id" not in result:
            result["session_id"] = result["negotiation_id"]
        return result

    async def make_offer(
        self,
        session_id: str,
        user: Users,
        price: float,
        message: str = "",
    ) -> Dict[str, Any]:
        """提交报价"""
        result = await self._negotiation.make_offer(
            negotiation_id=session_id,
            user_id=user.id,
            price=price,
            message=message,
        )
        return {
            "success": result.success,
            "session_id": result.session_id,
            "offer_accepted": result.offer_accepted,
            "new_price": result.new_price,
            "message": result.message,
            "status": result.status.value if result.status else None,
            "current_round": result.current_round,
            "remaining_rounds": result.remaining_rounds,
        }

    async def respond_to_offer(
        self,
        session_id: str,
        user: Users,
        response: str,
    ) -> Dict[str, Any]:
        """响应报价（接受/拒绝）"""
        result = await self._negotiation.respond_to_offer(
            negotiation_id=session_id,
            user_id=user.id,
            response=response,
        )
        return {
            "success": result.success,
            "session_id": result.session_id,
            "offer_accepted": result.offer_accepted,
            "new_price": result.new_price,
            "message": result.message,
            "status": result.status.value if result.status else None,
            "current_round": result.current_round,
            "remaining_rounds": result.remaining_rounds,
        }

    async def withdraw_negotiation(
        self,
        session_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """撤回协商"""
        return await self._negotiation.withdraw_negotiation(
            negotiation_id=session_id,
            user_id=user.id,
        )

    # ======================================================================
    # EscrowService 委托
    # ======================================================================

    async def lock_funds(
        self,
        negotiation_id: str,
        buyer_id: int,
        seller_id: int,
        listing_id: str,
        amount: float,
        expiry_hours: Optional[int] = None,
    ) -> Any:
        """锁定资金"""
        return await self._escrow.lock_funds(
            negotiation_id=negotiation_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            listing_id=listing_id,
            amount=amount,
            expiry_hours=expiry_hours,
        )

    async def release_funds(self, escrow_id: str) -> Any:
        """释放资金给卖方"""
        return await self._escrow.release_to_seller(escrow_id=escrow_id)

    async def refund_funds(self, escrow_id: str, reason: str = "Refund") -> Any:
        """退还资金给买方"""
        return await self._escrow.refund_to_buyer(
            escrow_id=escrow_id,
            reason=reason,
        )
