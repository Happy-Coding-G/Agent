"""
Escrow Service - 资金托管服务

提供交易资金托管功能：
1. 协商开始前锁定买方资金
2. 协商成功释放给卖方
3. 协商失败退还给买方
4. 超时自动退还
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload

from app.db.models import (
    EscrowRecord, EscrowStatus, EscrowTransactionLog,
    TradeWallets, NegotiationSessions, TradeListings
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class InsufficientFundsError(ServiceError):
    """资金不足错误"""
    def __init__(self, required: int, available: int):
        super().__init__(
            400,
            f"Insufficient funds: required {required/100:.2f}, available {available/100:.2f}"
        )
        self.required = required
        self.available = available


class EscrowNotFoundError(ServiceError):
    """托管记录不存在"""
    def __init__(self, escrow_id: str):
        super().__init__(404, f"Escrow record not found: {escrow_id}")


class InvalidEscrowStateError(ServiceError):
    """无效的托管状态"""
    def __init__(self, escrow_id: str, current_status: str, expected_status: str):
        super().__init__(
            400,
            f"Invalid escrow state: {escrow_id} is {current_status}, expected {expected_status}"
        )


class EscrowService:
    """
    资金托管服务

    核心流程：
    1. 买方发起协商 → 调用lock_funds锁定资金
    2. 协商成功 → 调用release_to_seller释放资金
    3. 协商失败/超时 → 调用refund_to_buyer退还资金
    """

    # 默认托管过期时间（小时）
    DEFAULT_EXPIRY_HOURS = 24

    # 平台手续费率（5%）
    PLATFORM_FEE_RATE = 0.05

    def __init__(self, db: AsyncSession):
        self.db = db

    def _generate_id(self) -> str:
        """生成唯一ID"""
        return uuid.uuid4().hex[:16]

    async def lock_funds(
        self,
        negotiation_id: str,
        buyer_id: int,
        seller_id: int,
        listing_id: str,
        amount: float,
        expiry_hours: Optional[int] = None,
    ) -> EscrowRecord:
        """
        锁定买方资金

        Args:
            negotiation_id: 协商会话ID
            buyer_id: 买方用户ID
            seller_id: 卖方用户ID
            listing_id: 上架ID
            amount: 锁定金额（元）
            expiry_hours: 过期时间（小时），默认24小时

        Returns:
            EscrowRecord

        Raises:
            InsufficientFundsError: 买方余额不足
            ServiceError: 其他错误
        """
        amount_cents = int(amount * 100)

        # 1. 检查买方钱包余额
        buyer_wallet = await self._get_wallet(buyer_id)
        if buyer_wallet.liquid_credits < amount_cents:
            raise InsufficientFundsError(
                required=amount_cents,
                available=buyer_wallet.liquid_credits
            )

        # 2. 计算平台手续费和卖方收入
        platform_fee_cents = int(amount_cents * self.PLATFORM_FEE_RATE)
        seller_income_cents = amount_cents - platform_fee_cents

        # 3. 原子操作：扣减余额并创建托管记录
        async with self.db.begin():
            # 扣减买方余额
            buyer_wallet.liquid_credits -= amount_cents
            buyer_wallet.version += 1

            # 创建托管记录
            expires_at = datetime.utcnow() + timedelta(
                hours=expiry_hours or self.DEFAULT_EXPIRY_HOURS
            )

            escrow = EscrowRecord(
                escrow_id=self._generate_id(),
                negotiation_id=negotiation_id,
                listing_id=listing_id,
                buyer_id=buyer_id,
                seller_id=seller_id,
                amount_cents=amount_cents,
                platform_fee_cents=platform_fee_cents,
                seller_income_cents=seller_income_cents,
                status=EscrowStatus.LOCKED,
                expires_at=expires_at,
                metadata_json={
                    "locked_at": datetime.utcnow().isoformat(),
                    "original_amount": amount,
                }
            )
            self.db.add(escrow)

            # 创建交易日志
            log = EscrowTransactionLog(
                log_id=self._generate_id(),
                escrow_id=escrow.escrow_id,
                user_id=buyer_id,
                transaction_type="lock",
                amount_cents=-amount_cents,  # 负数表示出账
                wallet_balance_before_cents=buyer_wallet.liquid_credits + amount_cents,
                wallet_balance_after_cents=buyer_wallet.liquid_credits,
                escrow_balance_before_cents=0,
                escrow_balance_after_cents=amount_cents,
                description=f"Locked {amount} credits for negotiation {negotiation_id}",
            )
            self.db.add(log)

        await self.db.commit()
        await self.db.refresh(escrow)

        logger.info(
            f"Funds locked: escrow={escrow.escrow_id}, "
            f"buyer={buyer_id}, seller={seller_id}, amount={amount}"
        )

        return escrow

    async def release_to_seller(
        self,
        escrow_id: str,
        released_by: str = "system",
    ) -> EscrowRecord:
        """
        协商成功，释放资金给卖方

        Args:
            escrow_id: 托管记录ID
            released_by: 释放操作者（system/buyer/seller/arbitrator）

        Returns:
            EscrowRecord

        Raises:
            EscrowNotFoundError: 托管记录不存在
            InvalidEscrowStateError: 状态不正确
        """
        escrow = await self._get_escrow(escrow_id)

        if escrow.status != EscrowStatus.LOCKED:
            raise InvalidEscrowStateError(
                escrow_id=escrow_id,
                current_status=escrow.status.value,
                expected_status="locked"
            )

        # 原子操作：更新托管状态并增加卖方余额
        async with self.db.begin():
            # 更新托管记录
            escrow.status = EscrowStatus.RELEASED
            escrow.released_at = datetime.utcnow()
            escrow.released_by = released_by
            escrow.version += 1

            # 增加卖方余额
            seller_wallet = await self._get_wallet(escrow.seller_id)
            seller_wallet.liquid_credits += escrow.seller_income_cents
            seller_wallet.cumulative_sales_earnings += escrow.seller_income_cents
            seller_wallet.version += 1

            # 创建交易日志（卖方入账）
            log_seller = EscrowTransactionLog(
                log_id=self._generate_id(),
                escrow_id=escrow.escrow_id,
                user_id=escrow.seller_id,
                transaction_type="release",
                amount_cents=escrow.seller_income_cents,
                wallet_balance_before_cents=seller_wallet.liquid_credits - escrow.seller_income_cents,
                wallet_balance_after_cents=seller_wallet.liquid_credits,
                escrow_balance_before_cents=escrow.amount_cents,
                escrow_balance_after_cents=0,
                description=f"Released funds to seller for negotiation {escrow.negotiation_id}",
                metadata_json={"platform_fee": escrow.platform_fee_cents},
            )
            self.db.add(log_seller)

            # 平台手续费处理（可选：记录到平台收入账户）
            if escrow.platform_fee_cents > 0:
                log_fee = EscrowTransactionLog(
                    log_id=self._generate_id(),
                    escrow_id=escrow.escrow_id,
                    user_id=0,  # 平台账户
                    transaction_type="fee",
                    amount_cents=escrow.platform_fee_cents,
                    wallet_balance_before_cents=0,
                    wallet_balance_after_cents=escrow.platform_fee_cents,
                    escrow_balance_before_cents=escrow.amount_cents,
                    escrow_balance_after_cents=0,
                    description=f"Platform fee for negotiation {escrow.negotiation_id}",
                )
                self.db.add(log_fee)

        await self.db.commit()
        await self.db.refresh(escrow)

        logger.info(
            f"Funds released to seller: escrow={escrow_id}, "
            f"seller={escrow.seller_id}, amount={escrow.seller_income_cents/100}"
        )

        return escrow

    async def refund_to_buyer(
        self,
        escrow_id: str,
        reason: str,
        refunded_by: str = "system",
    ) -> EscrowRecord:
        """
        协商失败或取消，退还资金给买方

        Args:
            escrow_id: 托管记录ID
            reason: 退款原因
            refunded_by: 退款操作者

        Returns:
            EscrowRecord
        """
        escrow = await self._get_escrow(escrow_id)

        if escrow.status not in [EscrowStatus.LOCKED, EscrowStatus.DISPUTED]:
            raise InvalidEscrowStateError(
                escrow_id=escrow_id,
                current_status=escrow.status.value,
                expected_status="locked or disputed"
            )

        # 原子操作：更新托管状态并退还买方余额
        async with self.db.begin():
            # 更新托管记录
            escrow.status = EscrowStatus.REFUNDED
            escrow.refunded_at = datetime.utcnow()
            escrow.released_by = refunded_by
            escrow.refund_reason = reason
            escrow.version += 1

            # 退还买方余额
            buyer_wallet = await self._get_wallet(escrow.buyer_id)
            buyer_wallet.liquid_credits += escrow.amount_cents
            buyer_wallet.version += 1

            # 创建交易日志
            log = EscrowTransactionLog(
                log_id=self._generate_id(),
                escrow_id=escrow.escrow_id,
                user_id=escrow.buyer_id,
                transaction_type="refund",
                amount_cents=escrow.amount_cents,
                wallet_balance_before_cents=buyer_wallet.liquid_credits - escrow.amount_cents,
                wallet_balance_after_cents=buyer_wallet.liquid_credits,
                escrow_balance_before_cents=escrow.amount_cents,
                escrow_balance_after_cents=0,
                description=f"Refunded to buyer: {reason}",
            )
            self.db.add(log)

        await self.db.commit()
        await self.db.refresh(escrow)

        logger.info(
            f"Funds refunded to buyer: escrow={escrow_id}, "
            f"buyer={escrow.buyer_id}, reason={reason}"
        )

        return escrow

    async def process_expired_escrows(self) -> List[EscrowRecord]:
        """
        处理过期托管资金

        自动退还已过期但状态仍为LOCKED的资金

        Returns:
            处理的托管记录列表
        """
        now = datetime.utcnow()

        # 查询所有过期且未处理的托管记录
        result = await self.db.execute(
            select(EscrowRecord).where(
                and_(
                    EscrowRecord.status == EscrowStatus.LOCKED,
                    EscrowRecord.expires_at < now,
                )
            )
        )
        expired_records = result.scalars().all()

        processed = []
        for escrow in expired_records:
            try:
                await self.refund_to_buyer(
                    escrow_id=escrow.escrow_id,
                    reason="Escrow expired - automatic refund",
                    refunded_by="system",
                )
                processed.append(escrow)
            except Exception as e:
                logger.error(
                    f"Failed to process expired escrow {escrow.escrow_id}: {e}"
                )

        if processed:
            logger.info(f"Processed {len(processed)} expired escrows")

        return processed

    async def get_escrow_by_negotiation(
        self,
        negotiation_id: str,
    ) -> Optional[EscrowRecord]:
        """根据协商ID获取托管记录"""
        result = await self.db.execute(
            select(EscrowRecord).where(
                EscrowRecord.negotiation_id == negotiation_id
            )
        )
        return result.scalar_one_or_none()

    async def get_user_escrows(
        self,
        user_id: int,
        role: Optional[str] = None,  # buyer/seller/all
        status: Optional[EscrowStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[EscrowRecord]:
        """
        获取用户的托管记录

        Args:
            user_id: 用户ID
            role: 角色筛选（buyer/seller/all）
            status: 状态筛选
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            EscrowRecord列表
        """
        query = select(EscrowRecord)

        if role == "buyer":
            query = query.where(EscrowRecord.buyer_id == user_id)
        elif role == "seller":
            query = query.where(EscrowRecord.seller_id == user_id)
        else:
            query = query.where(
                (EscrowRecord.buyer_id == user_id) | (EscrowRecord.seller_id == user_id)
            )

        if status:
            query = query.where(EscrowRecord.status == status)

        query = query.order_by(desc(EscrowRecord.created_at))
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_escrow_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        获取用户托管统计信息

        Args:
            user_id: 用户ID

        Returns:
            统计信息字典
        """
        from sqlalchemy import func

        # 作为买方的统计
        buyer_stats = await self.db.execute(
            select(
                EscrowRecord.status,
                func.count(EscrowRecord.id).label("count"),
                func.sum(EscrowRecord.amount_cents).label("total"),
            ).where(
                EscrowRecord.buyer_id == user_id
            ).group_by(EscrowRecord.status)
        )

        # 作为卖方的统计
        seller_stats = await self.db.execute(
            select(
                EscrowRecord.status,
                func.count(EscrowRecord.id).label("count"),
                func.sum(EscrowRecord.seller_income_cents).label("total"),
            ).where(
                EscrowRecord.seller_id == user_id
            ).group_by(EscrowRecord.status)
        )

        return {
            "as_buyer": [
                {
                    "status": row.status.value,
                    "count": row.count,
                    "total": row.total / 100 if row.total else 0,
                }
                for row in buyer_stats.all()
            ],
            "as_seller": [
                {
                    "status": row.status.value,
                    "count": row.count,
                    "total": row.total / 100 if row.total else 0,
                }
                for row in seller_stats.all()
            ],
        }

    async def _get_escrow(self, escrow_id: str) -> EscrowRecord:
        """获取托管记录，不存在时抛出异常"""
        result = await self.db.execute(
            select(EscrowRecord).where(EscrowRecord.escrow_id == escrow_id)
        )
        escrow = result.scalar_one_or_none()

        if not escrow:
            raise EscrowNotFoundError(escrow_id)

        return escrow

    async def _get_wallet(self, user_id: int) -> TradeWallets:
        """获取用户钱包，不存在时创建"""
        result = await self.db.execute(
            select(TradeWallets).where(TradeWallets.user_id == user_id)
        )
        wallet = result.scalar_one_or_none()

        if not wallet:
            # 创建新钱包
            wallet = TradeWallets(
                user_id=user_id,
                liquid_credits=100000,  # 默认1000元
            )
            self.db.add(wallet)
            await self.db.commit()
            await self.db.refresh(wallet)

        return wallet


# 便捷函数
async def create_escrow(
    db: AsyncSession,
    negotiation_id: str,
    buyer_id: int,
    seller_id: int,
    listing_id: str,
    amount: float,
) -> EscrowRecord:
    """
    便捷函数：创建资金托管

    Args:
        db: 数据库会话
        negotiation_id: 协商ID
        buyer_id: 买方ID
        seller_id: 卖方ID
        listing_id: 上架ID
        amount: 金额（元）

    Returns:
        EscrowRecord
    """
    service = EscrowService(db)
    return await service.lock_funds(
        negotiation_id=negotiation_id,
        buyer_id=buyer_id,
        seller_id=seller_id,
        listing_id=listing_id,
        amount=amount,
    )
