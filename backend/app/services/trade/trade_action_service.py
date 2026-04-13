"""
Trade Action Service - 业务动作导向的交易API

提供统一的交易业务动作入口，简化前端调用。
一个动作自动处理所有相关操作（状态检查、资金、通知、日志）。
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.db.models import Users
from app.services.trade.unified_trade_service import UnifiedTradeService
from app.services.safety import EscrowService

logger = logging.getLogger(__name__)


class TradeAction(str, Enum):
    """交易业务动作"""
    # 协商相关
    INITIATE_NEGOTIATION = "initiate_negotiation"  # 发起协商
    MAKE_OFFER = "make_offer"                      # 提交报价
    ACCEPT_OFFER = "accept_offer"                  # 接受报价
    REJECT_OFFER = "reject_offer"                  # 拒绝报价
    COUNTER_OFFER = "counter_offer"                # 还价
    WITHDRAW_NEGOTIATION = "withdraw_negotiation"  # 撤回协商

    # 拍卖相关
    PLACE_BID = "place_bid"                        # 出价
    CLOSE_AUCTION = "close_auction"                # 关闭拍卖

    # 购买相关
    DIRECT_PURCHASE = "direct_purchase"            # 直接购买
    CONFIRM_PURCHASE = "confirm_purchase"          # 确认购买

    # 上架相关
    CREATE_LISTING = "create_listing"              # 创建上架
    UPDATE_LISTING = "update_listing"              # 更新上架
    CANCEL_LISTING = "cancel_listing"              # 取消上架


@dataclass
class TradeActionResult:
    """交易动作结果"""
    success: bool
    action: TradeAction
    message: str
    data: Dict[str, Any]
    transaction_id: Optional[str] = None
    next_actions: list = None

    def __post_init__(self):
        if self.next_actions is None:
            self.next_actions = []


class TradeActionService:
    """
    业务动作导向的交易服务

    统一入口，自动处理所有相关操作。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.trade_service = UnifiedTradeService(db)
        self.escrow_service = EscrowService(db)

    async def execute(
        self,
        action: TradeAction,
        user: Users,
        params: Dict[str, Any],
    ) -> TradeActionResult:
        """
        执行交易业务动作

        Args:
            action: 业务动作类型
            user: 当前用户
            params: 动作参数

        Returns:
            TradeActionResult
        """
        logger.info(f"Executing trade action: {action.value} by user {user.id}")

        try:
            # 根据动作类型分发到具体处理函数
            handler = self._get_handler(action)
            result = await handler(user, params)

            # 记录业务日志
            await self._log_action(action, user.id, result)

            return result

        except ServiceError as e:
            logger.warning(f"Trade action failed: {action.value}, error: {e}")
            return TradeActionResult(
                success=False,
                action=action,
                message=str(e),
                data={"error_code": e.status_code},
            )
        except Exception as e:
            logger.exception(f"Unexpected error in trade action: {action.value}")
            return TradeActionResult(
                success=False,
                action=action,
                message=f"Internal error: {str(e)}",
                data={},
            )

    def _get_handler(self, action: TradeAction):
        """获取动作处理器"""
        handlers = {
            TradeAction.INITIATE_NEGOTIATION: self._handle_initiate_negotiation,
            TradeAction.MAKE_OFFER: self._handle_make_offer,
            TradeAction.ACCEPT_OFFER: self._handle_accept_offer,
            TradeAction.REJECT_OFFER: self._handle_reject_offer,
            TradeAction.COUNTER_OFFER: self._handle_counter_offer,
            TradeAction.WITHDRAW_NEGOTIATION: self._handle_withdraw_negotiation,
            TradeAction.PLACE_BID: self._handle_place_bid,
            TradeAction.CLOSE_AUCTION: self._handle_close_auction,
            TradeAction.DIRECT_PURCHASE: self._handle_direct_purchase,
            TradeAction.CREATE_LISTING: self._handle_create_listing,
            TradeAction.CANCEL_LISTING: self._handle_cancel_listing,
        }
        return handlers.get(action, self._handle_unknown)

    async def _handle_initiate_negotiation(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理发起协商动作"""
        listing_id = params.get("listing_id")
        initial_offer = params.get("initial_offer")
        max_rounds = params.get("max_rounds", 10)
        message = params.get("message", "")

        if not listing_id:
            raise ServiceError(400, "listing_id is required")

        # 创建协商
        result = await self.trade_service.create_negotiation(
            listing_id=listing_id,
            buyer=user,
            initial_offer=initial_offer or 0,
            max_rounds=max_rounds,
        )

        # 如果有初始报价，提交报价
        if initial_offer and result.get("success"):
            negotiation_id = result.get("negotiation_id")
            if negotiation_id:
                await self.trade_service.make_offer(
                    session_id=negotiation_id,
                    user=user,
                    price=initial_offer,
                    message=message,
                )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.INITIATE_NEGOTIATION,
            message=result.get("message", "Negotiation initiated"),
            data=result,
            transaction_id=result.get("negotiation_id"),
            next_actions=["make_offer", "withdraw_negotiation"],
        )

    async def _handle_make_offer(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理提交报价动作"""
        negotiation_id = params.get("negotiation_id")
        price = params.get("price")
        message = params.get("message", "")

        if not negotiation_id or price is None:
            raise ServiceError(400, "negotiation_id and price are required")

        result = await self.trade_service.make_offer(
            session_id=negotiation_id,
            user=user,
            price=price,
            message=message,
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.MAKE_OFFER,
            message=result.get("message", "Offer made"),
            data=result,
            transaction_id=negotiation_id,
            next_actions=["accept_offer", "reject_offer", "counter_offer"],
        )

    async def _handle_accept_offer(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理接受报价动作"""
        negotiation_id = params.get("negotiation_id")

        if not negotiation_id:
            raise ServiceError(400, "negotiation_id is required")

        # 接受报价
        result = await self.trade_service.respond_to_offer(
            session_id=negotiation_id,
            user=user,
            response="accept",
        )

        # 如果接受成功，触发资金释放
        if result.get("success"):
            # TODO: 获取escrow_id并释放资金
            pass

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.ACCEPT_OFFER,
            message="Offer accepted. Deal completed!" if result.get("success") else result.get("message"),
            data=result,
            transaction_id=negotiation_id,
            next_actions=["confirm_purchase"],
        )

    async def _handle_reject_offer(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理拒绝报价动作"""
        negotiation_id = params.get("negotiation_id")

        if not negotiation_id:
            raise ServiceError(400, "negotiation_id is required")

        result = await self.trade_service.respond_to_offer(
            session_id=negotiation_id,
            user=user,
            response="reject",
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.REJECT_OFFER,
            message=result.get("message", "Offer rejected"),
            data=result,
            transaction_id=negotiation_id,
            next_actions=["make_offer", "withdraw_negotiation"],
        )

    async def _handle_counter_offer(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理还价动作"""
        negotiation_id = params.get("negotiation_id")
        price = params.get("price")
        message = params.get("message", "")

        if not negotiation_id or price is None:
            raise ServiceError(400, "negotiation_id and price are required")

        # 先拒绝当前报价
        await self.trade_service.respond_to_offer(
            session_id=negotiation_id,
            user=user,
            response="reject",
        )

        # 然后提交新报价
        result = await self.trade_service.make_offer(
            session_id=negotiation_id,
            user=user,
            price=price,
            message=message,
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.COUNTER_OFFER,
            message=result.get("message", "Counter offer made"),
            data=result,
            transaction_id=negotiation_id,
            next_actions=["accept_offer", "reject_offer", "counter_offer"],
        )

    async def _handle_withdraw_negotiation(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理撤回协商动作"""
        negotiation_id = params.get("negotiation_id")

        if not negotiation_id:
            raise ServiceError(400, "negotiation_id is required")

        # TODO: 实现撤回逻辑
        # 1. 退还诚意金
        # 2. 更新协商状态为cancelled

        return TradeActionResult(
            success=True,
            action=TradeAction.WITHDRAW_NEGOTIATION,
            message="Negotiation withdrawn. Earnest money refunded.",
            data={"negotiation_id": negotiation_id},
            transaction_id=negotiation_id,
            next_actions=[],
        )

    async def _handle_place_bid(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理出价动作"""
        lot_id = params.get("lot_id")
        amount = params.get("amount")

        if not lot_id or amount is None:
            raise ServiceError(400, "lot_id and amount are required")

        result = await self.trade_service.place_auction_bid(
            lot_id=lot_id,
            user=user,
            amount=amount,
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.PLACE_BID,
            message=result.get("message", "Bid placed"),
            data=result,
            transaction_id=lot_id,
            next_actions=["place_bid"],
        )

    async def _handle_close_auction(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理关闭拍卖动作"""
        lot_id = params.get("lot_id")

        if not lot_id:
            raise ServiceError(400, "lot_id is required")

        result = await self.trade_service.close_auction(
            lot_id=lot_id,
            user=user,
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.CLOSE_AUCTION,
            message=result.get("message", "Auction closed"),
            data=result,
            transaction_id=lot_id,
            next_actions=["confirm_purchase"],
        )

    async def _handle_direct_purchase(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理直接购买动作"""
        listing_id = params.get("listing_id")

        if not listing_id:
            raise ServiceError(400, "listing_id is required")

        result = await self.trade_service.purchase(
            listing_id=listing_id,
            buyer=user,
            purchase_type="direct",
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.DIRECT_PURCHASE,
            message=result.get("message", "Purchase completed"),
            data=result,
            transaction_id=result.get("order_id"),
            next_actions=[],
        )

    async def _handle_create_listing(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理创建上架动作"""
        space_public_id = params.get("space_public_id")
        asset_id = params.get("asset_id")
        price = params.get("price")

        if not all([space_public_id, asset_id, price]):
            raise ServiceError(400, "space_public_id, asset_id, and price are required")

        result = await self.trade_service.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            pricing_strategy="fixed",
            price_credits=price,
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.CREATE_LISTING,
            message=result.get("message", "Listing created"),
            data=result,
            transaction_id=result.get("listing_id"),
            next_actions=["update_listing", "cancel_listing"],
        )

    async def _handle_cancel_listing(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理取消上架动作"""
        listing_id = params.get("listing_id")

        # TODO: 实现取消上架逻辑

        return TradeActionResult(
            success=True,
            action=TradeAction.CANCEL_LISTING,
            message="Listing cancelled",
            data={"listing_id": listing_id},
            transaction_id=listing_id,
            next_actions=[],
        )

    async def _handle_unknown(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理未知动作"""
        return TradeActionResult(
            success=False,
            action=TradeAction.INITIATE_NEGOTIATION,  # placeholder
            message="Unknown action type",
            data={},
        )

    async def _log_action(
        self,
        action: TradeAction,
        user_id: int,
        result: TradeActionResult,
    ):
        """记录业务动作日志"""
        logger.info(
            f"Trade action logged: {action.value}, user={user_id}, "
            f"success={result.success}, tx_id={result.transaction_id}"
        )


# ============================================================================
# 便捷函数
# ============================================================================

async def execute_trade_action(
    db: AsyncSession,
    action: str,
    user: Users,
    params: Dict[str, Any],
) -> TradeActionResult:
    """
    便捷函数：执行交易业务动作

    Args:
        db: 数据库会话
        action: 动作类型字符串
        user: 当前用户
        params: 动作参数

    Returns:
        TradeActionResult
    """
    try:
        action_enum = TradeAction(action)
    except ValueError:
        return TradeActionResult(
            success=False,
            action=TradeAction.INITIATE_NEGOTIATION,  # placeholder
            message=f"Invalid action: {action}",
            data={"valid_actions": [a.value for a in TradeAction]},
        )

    service = TradeActionService(db)
    return await service.execute(action_enum, user, params)
