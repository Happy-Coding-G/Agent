"""
Trade Batch Operations Service - 交易批量操作服务

提供批量操作功能，提高管理效率：
- 批量更新价格
- 批量取消上架
- 批量处理协商
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import TradeListings, NegotiationSessions, Users
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


@dataclass
class BatchOperationResult:
    """批量操作结果"""
    success: bool
    total: int
    succeeded: int
    failed: int
    results: List[Dict[str, Any]]


class TradeBatchOperationsService:
    """
    交易批量操作服务
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def batch_update_listing_prices(
        self,
        user_id: int,
        listing_ids: List[str],
        new_price: float,
        price_adjustment: Optional[float] = None,  # 百分比调整，如 0.1 = +10%
    ) -> BatchOperationResult:
        """
        批量更新上架价格

        Args:
            user_id: 用户ID（必须是卖方）
            listing_ids: 上架ID列表
            new_price: 新价格（绝对值）
            price_adjustment: 价格调整百分比（相对值）

        Returns:
            BatchOperationResult
        """
        results = []
        succeeded = 0
        failed = 0

        for listing_id in listing_ids:
            try:
                result = await self._update_single_price(
                    user_id, listing_id, new_price, price_adjustment
                )
                results.append({
                    "listing_id": listing_id,
                    "success": True,
                    "data": result,
                })
                succeeded += 1

            except Exception as e:
                results.append({
                    "listing_id": listing_id,
                    "success": False,
                    "error": str(e),
                })
                failed += 1

        await self.db.commit()

        return BatchOperationResult(
            success=failed == 0,
            total=len(listing_ids),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    async def _update_single_price(
        self,
        user_id: int,
        listing_id: str,
        new_price: Optional[float],
        price_adjustment: Optional[float],
    ) -> Dict[str, Any]:
        """更新单个上架价格"""
        result = await self.db.execute(
            select(TradeListings).where(
                and_(
                    TradeListings.public_id == listing_id,
                    TradeListings.seller_user_id == user_id,
                )
            )
        )
        listing = result.scalar_one_or_none()

        if not listing:
            raise ServiceError(404, f"Listing {listing_id} not found or not owned by you")

        if listing.status != "active":
            raise ServiceError(400, f"Listing {listing_id} is not active")

        old_price = listing.price_credits / 100

        if price_adjustment is not None:
            # 相对调整
            current_price = listing.price_credits / 100
            final_price = current_price * (1 + price_adjustment)
        else:
            # 绝对值
            final_price = new_price

        listing.price_credits = int(final_price * 100)

        return {
            "listing_id": listing_id,
            "old_price": old_price,
            "new_price": final_price,
        }

    async def batch_cancel_listings(
        self,
        user_id: int,
        listing_ids: List[str],
    ) -> BatchOperationResult:
        """
        批量取消上架

        Args:
            user_id: 用户ID（必须是卖方）
            listing_ids: 上架ID列表

        Returns:
            BatchOperationResult
        """
        results = []
        succeeded = 0
        failed = 0

        for listing_id in listing_ids:
            try:
                result = await self._cancel_single_listing(user_id, listing_id)
                results.append({
                    "listing_id": listing_id,
                    "success": True,
                    "data": result,
                })
                succeeded += 1

            except Exception as e:
                results.append({
                    "listing_id": listing_id,
                    "success": False,
                    "error": str(e),
                })
                failed += 1

        await self.db.commit()

        return BatchOperationResult(
            success=failed == 0,
            total=len(listing_ids),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    async def _cancel_single_listing(
        self,
        user_id: int,
        listing_id: str,
    ) -> Dict[str, Any]:
        """取消单个上架"""
        result = await self.db.execute(
            select(TradeListings).where(
                and_(
                    TradeListings.public_id == listing_id,
                    TradeListings.seller_user_id == user_id,
                )
            )
        )
        listing = result.scalar_one_or_none()

        if not listing:
            raise ServiceError(404, f"Listing {listing_id} not found")

        if listing.status != "active":
            raise ServiceError(400, f"Listing {listing_id} is already {listing.status}")

        listing.status = "cancelled"

        return {
            "listing_id": listing_id,
            "previous_status": "active",
            "new_status": "cancelled",
        }

    async def batch_withdraw_negotiations(
        self,
        user_id: int,
        negotiation_ids: List[str],
    ) -> BatchOperationResult:
        """
        批量撤回协商

        Args:
            user_id: 用户ID（必须是买方）
            negotiation_ids: 协商ID列表

        Returns:
            BatchOperationResult
        """
        results = []
        succeeded = 0
        failed = 0

        for negotiation_id in negotiation_ids:
            try:
                result = await self._withdraw_single_negotiation(user_id, negotiation_id)
                results.append({
                    "negotiation_id": negotiation_id,
                    "success": True,
                    "data": result,
                })
                succeeded += 1

            except Exception as e:
                results.append({
                    "negotiation_id": negotiation_id,
                    "success": False,
                    "error": str(e),
                })
                failed += 1

        await self.db.commit()

        return BatchOperationResult(
            success=failed == 0,
            total=len(negotiation_ids),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    async def _withdraw_single_negotiation(
        self,
        user_id: int,
        negotiation_id: str,
    ) -> Dict[str, Any]:
        """撤回单个协商"""
        from app.services.trade.simple_negotiation_service import SimpleNegotiationService

        service = SimpleNegotiationService(self.db)
        result = await service.withdraw_negotiation(negotiation_id, user_id)
        return result

    async def batch_reject_offers(
        self,
        user_id: int,
        negotiation_ids: List[str],
    ) -> BatchOperationResult:
        """
        批量拒绝报价

        Args:
            user_id: 用户ID
            negotiation_ids: 协商ID列表

        Returns:
            BatchOperationResult
        """
        results = []
        succeeded = 0
        failed = 0

        from app.services.trade.simple_negotiation_service import SimpleNegotiationService
        service = SimpleNegotiationService(self.db)

        for negotiation_id in negotiation_ids:
            try:
                result = await service.respond_to_offer(
                    negotiation_id=negotiation_id,
                    user_id=user_id,
                    response="reject",
                )
                results.append({
                    "negotiation_id": negotiation_id,
                    "success": True,
                    "data": result,
                })
                succeeded += 1

            except Exception as e:
                results.append({
                    "negotiation_id": negotiation_id,
                    "success": False,
                    "error": str(e),
                })
                failed += 1

        await self.db.commit()

        return BatchOperationResult(
            success=failed == 0,
            total=len(negotiation_ids),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    async def get_listings_summary(
        self,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        获取上架汇总统计

        用于批量操作前的概览。
        """
        result = await self.db.execute(
            select(TradeListings).where(
                TradeListings.seller_user_id == user_id
            )
        )
        listings = result.scalars().all()

        active = [l for l in listings if l.status == "active"]
        sold = [l for l in listings if l.status == "sold"]
        cancelled = [l for l in listings if l.status == "cancelled"]

        total_value = sum(l.price_credits for l in active) / 100

        return {
            "total": len(listings),
            "active": len(active),
            "sold": len(sold),
            "cancelled": len(cancelled),
            "active_total_value": total_value,
            "active_listing_ids": [l.public_id for l in active],
        }

    async def get_negotiations_summary(
        self,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        获取协商汇总统计

        用于批量操作前的概览。
        """
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.buyer_user_id == user_id
            )
        )
        negotiations = result.scalars().all()

        active = [n for n in negotiations if n.status in ["pending", "active"]]
        accepted = [n for n in negotiations if n.status == "accepted"]
        others = [n for n in negotiations if n.status not in ["pending", "active", "accepted"]]

        return {
            "total": len(negotiations),
            "active": len(active),
            "accepted": len(accepted),
            "others": len(others),
            "active_negotiation_ids": [n.negotiation_id for n in active],
        }
