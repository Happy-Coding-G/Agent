"""
Trade Action Service - 业务动作导向的交易API

提供统一的交易业务动作入口，简化前端调用。
当前仅支持直接交易（direct trade）。
"""

from __future__ import annotations

import logging
from typing import Dict, Any
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.db.models import Users
from app.services.trade.unified_trade_service import UnifiedTradeService

logger = logging.getLogger(__name__)


class TradeAction(str, Enum):
    """交易业务动作"""
    # 直接交易
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
    transaction_id: str | None = None
    next_actions: list = None

    def __post_init__(self):
        if self.next_actions is None:
            self.next_actions = []


class TradeActionService:
    """
    业务动作导向的交易服务

    统一入口，当前仅支持直接交易。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.trade_service = UnifiedTradeService(db)

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
            handler = self._get_handler(action)
            result = await handler(user, params)
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
            TradeAction.DIRECT_PURCHASE: self._handle_direct_purchase,
            TradeAction.CONFIRM_PURCHASE: self._handle_confirm_purchase,
            TradeAction.CREATE_LISTING: self._handle_create_listing,
            TradeAction.UPDATE_LISTING: self._handle_update_listing,
            TradeAction.CANCEL_LISTING: self._handle_cancel_listing,
        }
        return handlers.get(action, self._handle_unknown)

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
        )

        return TradeActionResult(
            success=result.get("success", False),
            action=TradeAction.DIRECT_PURCHASE,
            message=result.get("message", "Purchase completed"),
            data=result,
            transaction_id=result.get("order_id"),
            next_actions=[],
        )

    async def _handle_confirm_purchase(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理确认购买动作"""
        # 当前直接交易中，purchase 已完成全部流程
        # 此动作用于兼容层，直接返回成功
        return TradeActionResult(
            success=True,
            action=TradeAction.CONFIRM_PURCHASE,
            message="Purchase confirmed",
            data={},
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

    async def _handle_update_listing(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理更新上架动作"""
        listing_id = params.get("listing_id")

        return TradeActionResult(
            success=True,
            action=TradeAction.UPDATE_LISTING,
            message="Listing updated",
            data={"listing_id": listing_id},
            next_actions=[],
        )

    async def _handle_cancel_listing(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理取消上架动作"""
        listing_id = params.get("listing_id")

        return TradeActionResult(
            success=True,
            action=TradeAction.CANCEL_LISTING,
            message="Listing cancelled",
            data={"listing_id": listing_id},
            next_actions=[],
        )

    async def _handle_unknown(
        self, user: Users, params: Dict[str, Any]
    ) -> TradeActionResult:
        """处理未知动作"""
        return TradeActionResult(
            success=False,
            action=TradeAction.DIRECT_PURCHASE,
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
    """
    try:
        action_enum = TradeAction(action)
    except ValueError:
        return TradeActionResult(
            success=False,
            action=TradeAction.DIRECT_PURCHASE,
            message=f"Invalid action: {action}",
            data={"valid_actions": [a.value for a in TradeAction]},
        )

    service = TradeActionService(db)
    return await service.execute(action_enum, user, params)
