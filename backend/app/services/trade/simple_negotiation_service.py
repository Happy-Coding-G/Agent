"""
Simple Negotiation Service - 双边协商引擎（简化版）

Agent-First 架构中的 Bilateral Engine：
1. 当前状态存储在 NegotiationSessions 表中
2. 历史记录存储在 shared_board JSONB 字段中
3. 乐观锁（version字段）防并发冲突
4. O(1) 查询性能，无需事件重放

适用场景：
- 1对1双边协商
- 低并发场景
- 快速查询当前状态

重要：这是 NegotiationKernel 的内部引擎，不直接对外暴露。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.db.models import (
    NegotiationSessions,
    TradeListings,
    TradeWallets,
)
from app.core.errors import ServiceError
from app.services.safety import EscrowService

# Agent-First: 导入领域结果类型
from app.services.trade.result_types import (
    NegotiationResult,
    OfferResult,
    SessionState,
    AuditEvent,
    MechanismType,
    EngineType,
    NegotiationStatus,
    create_success_result,
    create_error_result,
)

logger = logging.getLogger(__name__)


class SimpleNegotiationService:
    """
    双边协商引擎（简化版）

    Agent-First 架构中的 Bilateral Engine。
    被 NegotiationKernel 内部调用，不直接对外暴露。

    核心设计：
    - 直接读写当前状态
    - 历史记录追加到 JSONB
    - 乐观锁（version字段）防并发冲突
    - 返回领域结果对象（NegotiationResult/OfferResult）
    """

    # 默认协商过期时间（小时）
    DEFAULT_EXPIRY_HOURS = 72

    # 诚意金比例（5%）
    EARNEST_MONEY_RATE = 0.05

    # 最低诚意金（10元 = 1000分）
    MIN_EARNEST_MONEY = 1000

    def __init__(self, db: AsyncSession):
        self.db = db
        self.escrow_service = EscrowService(db)

    async def create_negotiation(
        self,
        buyer_id: int,
        listing_id: str,
        requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        创建协商会话

        流程：
        1. 检查商品和权限
        2. 计算并锁定诚意金
        3. 创建协商记录
        4. 如果有初始报价，记录到历史
        """
        # 1. 检查商品
        listing_result = await self.db.execute(
            select(TradeListings).where(TradeListings.public_id == listing_id)
        )
        listing = listing_result.scalar_one_or_none()

        if not listing:
            raise ServiceError(404, "Listing not found")

        if listing.status != "active":
            raise ServiceError(400, f"Listing is not active: {listing.status}")

        if listing.seller_user_id == buyer_id:
            raise ServiceError(403, "Cannot negotiate with yourself")

        # 2. 检查是否已存在进行中的协商
        existing_result = await self.db.execute(
            select(NegotiationSessions).where(
                and_(
                    NegotiationSessions.listing_id == listing_id,
                    NegotiationSessions.buyer_user_id == buyer_id,
                    NegotiationSessions.status.in_(["pending", "active"]),
                )
            )
        )
        if existing_result.scalar_one_or_none():
            return {
                "success": True,
                "message": "Existing negotiation found",
                "is_new": False,
            }

        # 3. 计算诚意金
        listing_price = getattr(listing, 'price_credits', 0) or 0
        earnest_money = max(
            int(listing_price * self.EARNEST_MONEY_RATE),
            self.MIN_EARNEST_MONEY
        )

        # 4. 锁定诚意金
        try:
            negotiation_id = uuid.uuid4().hex[:32]
            escrow = await self.escrow_service.lock_funds(
                negotiation_id=negotiation_id,
                buyer_id=buyer_id,
                seller_id=listing.seller_user_id,
                listing_id=listing_id,
                amount=earnest_money / 100,  # 转换为元
                expiry_hours=self.DEFAULT_EXPIRY_HOURS,
            )
            escrow_id = escrow.escrow_id
        except Exception as e:
            logger.warning(f"Failed to lock earnest money: {e}")
            raise ServiceError(
                400,
                f"需要支付诚意金 {earnest_money / 100:.2f} 元，请确保账户余额充足。"
            )

        # 5. 构建历史记录
        initial_offer = requirements.get("preferred_price")
        history = []

        if initial_offer:
            history.append({
                "round": 1,
                "action": "offer",
                "price": initial_offer,
                "by": "buyer",
                "by_id": buyer_id,
                "message": requirements.get("message", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # 6. 创建协商记录
        session = NegotiationSessions(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            seller_user_id=listing.seller_user_id,
            buyer_user_id=buyer_id,
            status="active" if initial_offer else "pending",
            current_round=1 if initial_offer else 0,
            seller_floor_price=listing.reserve_price or 0,
            escrow_id=escrow_id,
            agreed_price=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=self.DEFAULT_EXPIRY_HOURS),
            shared_board={
                "initiated_by": "buyer",
                "buyer_requirements": requirements,
                "history": history,
                "price_evolution": [initial_offer] if initial_offer else [],
                "earnest_money": {
                    "amount_cents": earnest_money,
                    "escrow_id": escrow_id,
                    "locked_at": datetime.now(timezone.utc).isoformat(),
                },
                "current_offer": {
                    "price": initial_offer,
                    "by": "buyer",
                } if initial_offer else None,
            },
        )

        self.db.add(session)
        await self.db.commit()

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "status": session.status,
            "earnest_money": earnest_money / 100,
            "message": "Negotiation created" + (" with initial offer" if initial_offer else ""),
            "is_new": True,
        }

    async def make_offer(
        self,
        negotiation_id: str,
        user_id: int,
        price: float,
        message: str = "",
        expected_version: Optional[int] = None,
    ) -> OfferResult:
        """
        提交报价

        使用乐观锁（version字段）防止并发冲突。

        Args:
            negotiation_id: 协商会话ID
            user_id: 用户ID
            price: 报价
            message: 附言
            expected_version: 预期的版本号（乐观锁）

        Returns:
            OfferResult: 领域结果对象
        """
        # 1. 获取协商记录（带版本检查）
        query = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )

        # 如果提供了预期版本，添加版本检查
        if expected_version is not None:
            query = query.where(NegotiationSessions.version == expected_version)

        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if not session:
            if expected_version is not None:
                # 版本不匹配或记录不存在
                return OfferResult(
                    success=False,
                    session_id=negotiation_id,
                    error="Concurrent modification detected. Please refresh and try again.",
                )
            raise ServiceError(404, "Negotiation not found")

        if session.status not in ["pending", "active"]:
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error=f"Negotiation is {session.status}",
            )

        # 2. 检查是否是该用户的回合
        shared_board = dict(session.shared_board)
        history = shared_board.get("history", [])

        # 确定角色
        is_buyer = user_id == session.buyer_user_id
        is_seller = user_id == session.seller_user_id

        if not is_buyer and not is_seller:
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error="Not a participant in this negotiation",
            )

        role = "buyer" if is_buyer else "seller"

        # 简单回合检查：不能连续报价
        if history and history[-1]["by"] == role:
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error="Cannot make consecutive offers, wait for the other party",
            )

        # 3. 更新状态和版本
        new_round = session.current_round + 1
        new_version = session.version + 1

        # 4. 追加历史记录
        history.append({
            "round": new_round,
            "action": "offer",
            "price": price,
            "by": role,
            "by_id": user_id,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": new_version,  # 记录版本
        })

        # 5. 更新价格演进
        price_evolution = shared_board.get("price_evolution", [])
        price_evolution.append(price)

        # 6. 更新共享板
        shared_board["history"] = history
        shared_board["price_evolution"] = price_evolution
        shared_board["current_offer"] = {
            "price": price,
            "by": role,
            "message": message,
            "version": new_version,
        }

        # 7. 更新会话（乐观锁：version 自动递增）
        session.status = "active"
        session.current_round = new_round
        session.current_price = int(price * 100)  # 转换为分
        session.shared_board = shared_board
        session.last_activity_at = datetime.now(timezone.utc)
        session.version = new_version  # 递增版本

        await self.db.commit()

        return OfferResult(
            success=True,
            session_id=negotiation_id,
            offer_accepted=False,
            new_price=price,
            message=f"Offer of {price} made by {role}",
            status=NegotiationStatus.ACTIVE,
            current_round=new_round,
            remaining_rounds=session.max_rounds - new_round,
        )

    async def respond_to_offer(
        self,
        negotiation_id: str,
        user_id: int,
        response: str,  # "accept", "reject"
        expected_version: Optional[int] = None,
    ) -> OfferResult:
        """
        响应报价（接受或拒绝）

        使用乐观锁防止并发冲突。

        Args:
            negotiation_id: 协商会话ID
            user_id: 用户ID
            response: 响应类型（"accept" 或 "reject"）
            expected_version: 预期的版本号

        Returns:
            OfferResult: 领域结果对象
        """
        query = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )

        if expected_version is not None:
            query = query.where(NegotiationSessions.version == expected_version)

        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if not session:
            if expected_version is not None:
                return OfferResult(
                    success=False,
                    session_id=negotiation_id,
                    error="Concurrent modification detected. Please refresh and try again.",
                )
            raise ServiceError(404, "Negotiation not found")

        if session.status != "active":
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error=f"Negotiation is {session.status}",
            )

        # 确定角色
        is_buyer = user_id == session.buyer_user_id
        is_seller = user_id == session.seller_user_id

        if not is_buyer and not is_seller:
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error="Not a participant",
            )

        role = "buyer" if is_buyer else "seller"

        shared_board = dict(session.shared_board)
        history = shared_board.get("history", [])

        # 新版本号
        new_version = session.version + 1

        if response == "accept":
            # 接受报价
            current_offer = shared_board.get("current_offer", {})
            agreed_price = current_offer.get("price", 0)

            session.status = "accepted"
            session.agreed_price = int(agreed_price * 100)
            session.settlement_at = datetime.now(timezone.utc)

            # 追加历史
            history.append({
                "round": session.current_round + 1,
                "action": "accept",
                "price": agreed_price,
                "by": role,
                "by_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": new_version,
            })

            message = f"Offer accepted! Deal closed at {agreed_price}"
            status = NegotiationStatus.ACCEPTED

        elif response == "reject":
            # 拒绝报价
            history.append({
                "round": session.current_round + 1,
                "action": "reject",
                "by": role,
                "by_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": new_version,
            })

            message = "Offer rejected"
            status = NegotiationStatus.ACTIVE  # 保持活跃，可继续协商

        else:
            return OfferResult(
                success=False,
                session_id=negotiation_id,
                error=f"Invalid response: {response}",
            )

        shared_board["history"] = history
        session.shared_board = shared_board
        session.last_activity_at = datetime.now(timezone.utc)
        session.version = new_version  # 递增版本

        await self.db.commit()

        return OfferResult(
            success=True,
            session_id=negotiation_id,
            offer_accepted=(response == "accept"),
            new_price=agreed_price if response == "accept" else None,
            message=message,
            status=status,
            current_round=session.current_round + 1,
        )

    async def get_negotiation_status(
        self,
        negotiation_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        获取协商状态

        直接返回当前状态，无需重放事件。
        """
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == negotiation_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise ServiceError(404, "Negotiation not found")

        # 权限检查
        if user_id not in [session.buyer_user_id, session.seller_user_id]:
            raise ServiceError(403, "Access denied")

        shared_board = session.shared_board or {}

        return {
            "negotiation_id": negotiation_id,
            "status": session.status,
            "listing_id": session.listing_id,
            "buyer_id": session.buyer_user_id,
            "seller_id": session.seller_user_id,
            "current_round": session.current_round,
            "current_price": session.current_price / 100 if session.current_price else None,
            "agreed_price": session.agreed_price / 100 if session.agreed_price else None,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "history": shared_board.get("history", []),
            "price_evolution": shared_board.get("price_evolution", []),
            "current_offer": shared_board.get("current_offer"),
        }

    async def list_user_negotiations(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        列出用户的协商
        """
        query = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.buyer_user_id == user_id,
            )
        )

        if status:
            query = query.where(NegotiationSessions.status == status)

        query = query.order_by(NegotiationSessions.last_activity_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        sessions = result.scalars().all()

        return [
            {
                "negotiation_id": s.negotiation_id,
                "listing_id": s.listing_id,
                "status": s.status,
                "current_round": s.current_round,
                "current_price": s.current_price / 100 if s.current_price else None,
                "agreed_price": s.agreed_price / 100 if s.agreed_price else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
            }
            for s in sessions
        ]

    async def withdraw_negotiation(
        self,
        negotiation_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        撤回协商

        退还诚意金，更新状态。
        """
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == negotiation_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise ServiceError(404, "Negotiation not found")

        if session.buyer_user_id != user_id:
            raise ServiceError(403, "Only buyer can withdraw")

        if session.status not in ["pending", "active"]:
            raise ServiceError(400, f"Cannot withdraw: negotiation is {session.status}")

        # 1. 退还诚意金
        if session.escrow_id:
            try:
                await self.escrow_service.refund_to_buyer(session.escrow_id)
            except Exception as e:
                logger.error(f"Failed to refund earnest money: {e}")
                # 继续处理，但记录错误

        # 2. 更新状态
        session.status = "cancelled"
        session.shared_board["withdrawn_at"] = datetime.now(timezone.utc).isoformat()
        session.shared_board["withdrawn_by"] = user_id

        await self.db.commit()

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "status": "cancelled",
            "message": "Negotiation withdrawn. Earnest money refunded.",
        }

    # ========================================================================
    # Domain Model Conversions (Agent-First)
    # ========================================================================

    def to_negotiation_result(self, session: NegotiationSessions) -> NegotiationResult:
        """转换为领域结果对象"""
        shared_board = session.shared_board or {}

        return NegotiationResult(
            success=True,
            session_id=session.negotiation_id,
            status=NegotiationStatus(session.status),
            mechanism=MechanismType.BILATERAL,
            engine=EngineType.SIMPLE,
            seller_id=session.seller_user_id,
            buyer_id=session.buyer_user_id,
            current_price=session.current_price / 100 if session.current_price else None,
            agreed_price=session.agreed_price / 100 if session.agreed_price else None,
            current_round=session.current_round,
            max_rounds=session.max_rounds,
            message="Bilateral negotiation",
            metadata={
                "engine_type": "simple",
                "version": session.version,
                "shared_board": shared_board,
            },
        )

    def to_session_state(self, session: NegotiationSessions) -> SessionState:
        """转换为会话状态对象"""
        shared_board = session.shared_board or {}

        return SessionState(
            session_id=session.negotiation_id,
            mechanism=MechanismType.BILATERAL,
            engine=EngineType.SIMPLE,
            status=NegotiationStatus(session.status),
            seller_id=session.seller_user_id,
            buyer_id=session.buyer_user_id,
            listing_id=session.listing_id,
            current_price=session.current_price / 100 if session.current_price else None,
            agreed_price=session.agreed_price / 100 if session.agreed_price else None,
            current_round=session.current_round,
            max_rounds=session.max_rounds,
            version=session.version,
            shared_board=shared_board,
            engine_type="simple",
            selection_reason="Bilateral engine selected for 1-on-1 negotiation",
        )

    def get_engine_capabilities(self) -> Dict[str, Any]:
        """获取引擎能力描述"""
        return {
            "engine_type": "simple",
            "supports_concurrent_bids": False,
            "supports_full_audit": False,
            "optimistic_locking": True,
            "max_participants": 2,
            "best_for": "1对1双边协商，低并发场景",
        }
