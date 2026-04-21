"""
Negotiation Kernel - 协商执行内核

统一 simple 和 event_sourced 两种内部执行引擎的上层接口。

这是 Agent-first 架构的核心组件：
- TradeAgent 只调用 NegotiationKernel
- NegotiationKernel 负责路由到 BilateralEngine 或 AuctionEngine
- 引擎类型在 create_session 时确定，后续固定不变

提供能力：
1. create_session
2. submit_action
3. get_state
4. close_session
5. get_audit_log
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import NegotiationSessions
from app.services.trade.result_types import (
    NegotiationResult,
    OfferResult,
    BidResult,
    SessionState,
    AuditEvent,
    MechanismType,
    EngineType,
    NegotiationStatus,
    create_success_result,
    create_error_result,
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class NegotiationKernel:
    """
    协商执行内核

    TradeAgent 的内部执行内核。
    统一调度 BilateralEngine 和 AuctionEngine。

    重要设计原则：
    1. engine_type 一旦在 create_session 时确定，后续固定不变
    2. 从 NegotiationSessions 表读取 engine_type 进行路由
    3. 不提供修改 engine_type 的接口
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._bilateral = _BilateralEngine(db)
        self._auction = _AuctionEngine(db)

    async def create_session(
        self,
        mechanism: MechanismType,
        engine: EngineType,
        seller_id: int,
        listing_id: str,
        buyer_id: Optional[int] = None,
        starting_price: Optional[float] = None,
        reserve_price: Optional[float] = None,
        max_rounds: int = 10,
        expected_participants: int = 2,
        selection_reason: str = "",
    ) -> NegotiationResult:
        """
        创建协商会话

        这是唯一确定 engine_type 的时机。
        后续所有操作都根据 session 中固化的 engine_type 路由。

        Args:
            mechanism: 机制类型 (bilateral/auction)
            engine: 引擎类型 (simple/event_sourced)
            seller_id: 卖方ID
            listing_id: 上架ID
            buyer_id: 买方ID（双边协商时必需）
            starting_price: 起始价格
            reserve_price: 保留价格
            max_rounds: 最大轮数
            expected_participants: 预期参与者数量
            selection_reason: 选择原因

        Returns:
            NegotiationResult
        """
        logger.info(
            f"Creating session: mechanism={mechanism.value}, "
            f"engine={engine.value}, seller={seller_id}"
        )

        # 参数验证
        if mechanism == MechanismType.DIRECT and not buyer_id:
            return create_error_result(
                "buyer_id is required for bilateral negotiation"
            )

        try:
            # 路由到对应引擎
            if engine == EngineType.SIMPLE or mechanism == MechanismType.DIRECT:
                return await self._bilateral.create_session(
                    seller_id=seller_id,
                    buyer_id=buyer_id,
                    listing_id=listing_id,
                    starting_price=starting_price,
                    reserve_price=reserve_price,
                    max_rounds=max_rounds,
                    selection_reason=selection_reason,
                )
            else:
                return await self._auction.create_session(
                    seller_id=seller_id,
                    listing_id=listing_id,
                    starting_price=starting_price,
                    reserve_price=reserve_price,
                    max_rounds=max_rounds,
                    expected_participants=expected_participants,
                    selection_reason=selection_reason,
                )

        except Exception as e:
            logger.exception(f"Session creation failed: {e}")
            return create_error_result(str(e))

    async def submit_offer(
        self,
        session_id: str,
        user_id: int,
        price: float,
        message: str = "",
    ) -> OfferResult:
        """
        提交报价

        根据 session 固化的 engine_type 自动路由。

        Args:
            session_id: 会话ID
            user_id: 用户ID
            price: 报价
            message: 附言

        Returns:
            OfferResult
        """
        try:
            # 读取 session 获取固化的 engine_type
            session = await self._get_session(session_id)
            if not session:
                return OfferResult(
                    success=False,
                    session_id=session_id,
                    error="Session not found",
                )

            # 根据固化的 engine_type 路由
            engine_type = session.engine_type

            if engine_type == EngineType.SIMPLE.value:
                return await self._bilateral.submit_offer(
                    session_id=session_id,
                    user_id=user_id,
                    price=price,
                    message=message,
                )
            else:
                # 拍卖场景
                bid_result = await self._auction.submit_bid(
                    session_id=session_id,
                    bidder_id=user_id,
                    amount=price,
                )

                # 转换为 OfferResult
                return OfferResult(
                    success=bid_result.success,
                    session_id=session_id,
                    offer_accepted=bid_result.is_highest,
                    new_price=bid_result.amount if bid_result.is_highest else None,
                    message=bid_result.message,
                    error=bid_result.error,
                )

        except Exception as e:
            logger.exception(f"Offer submission failed: {e}")
            return OfferResult(
                success=False,
                session_id=session_id,
                error=str(e),
            )

    async def submit_bid(
        self,
        session_id: str,
        bidder_id: int,
        amount: float,
    ) -> BidResult:
        """
        提交出价（仅拍卖场景）

        Args:
            session_id: 会话ID
            bidder_id: 出价人ID
            amount: 出价金额

        Returns:
            BidResult
        """
        try:
            session = await self._get_session(session_id)
            if not session:
                return BidResult(
                    success=False,
                    session_id=session_id,
                    error="Session not found",
                )

            engine_type = session.engine_type

            if engine_type == EngineType.SIMPLE.value:
                # 简化版引擎不支持出价
                return BidResult(
                    success=False,
                    session_id=session_id,
                    error="Bidding not supported in simple engine",
                )

            return await self._auction.submit_bid(
                session_id=session_id,
                bidder_id=bidder_id,
                amount=amount,
            )

        except Exception as e:
            logger.exception(f"Bid submission failed: {e}")
            return BidResult(
                success=False,
                session_id=session_id,
                error=str(e),
            )

    async def get_state(self, session_id: str) -> Optional[SessionState]:
        """
        获取会话状态

        Args:
            session_id: 会话ID

        Returns:
            SessionState
        """
        try:
            session = await self._get_session(session_id)
            if not session:
                return None

            # 根据 engine_type 获取详细状态
            engine_type = session.engine_type

            if engine_type == EngineType.SIMPLE.value:
                return await self._bilateral.get_state(session_id)
            else:
                return await self._auction.get_state(session_id)

        except Exception as e:
            logger.exception(f"Get state failed: {e}")
            return None

    async def close_session(
        self,
        session_id: str,
        user_id: int,
    ) -> NegotiationResult:
        """
        关闭会话

        Args:
            session_id: 会话ID
            user_id: 用户ID（必须是卖方）

        Returns:
            NegotiationResult
        """
        try:
            session = await self._get_session(session_id)
            if not session:
                return create_error_result("Session not found", session_id)

            # 权限检查
            if session.seller_id != user_id:
                return create_error_result(
                    "Only seller can close session", session_id
                )

            engine_type = session.engine_type

            if engine_type == EngineType.SIMPLE.value:
                return await self._bilateral.close_session(session_id)
            else:
                return await self._auction.close_auction(session_id, user_id)

        except Exception as e:
            logger.exception(f"Close session failed: {e}")
            return create_error_result(str(e), session_id)

    async def get_audit_log(
        self,
        session_id: str,
    ) -> List[AuditEvent]:
        """
        获取审计日志

        Args:
            session_id: 会话ID

        Returns:
            List[AuditEvent]
        """
        try:
            session = await self._get_session(session_id)
            if not session:
                return []

            engine_type = session.engine_type

            if engine_type == EngineType.SIMPLE.value:
                return await self._bilateral.get_audit_log(session_id)
            else:
                return await self._auction.get_audit_log(session_id)

        except Exception as e:
            logger.exception(f"Get audit log failed: {e}")
            return []

    async def _get_session(
        self,
        session_id: str,
    ) -> Optional[NegotiationSessions]:
        """内部方法：获取会话记录"""
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        return result.scalar_one_or_none()


# ============================================================================
# Bilateral Engine (简化版)
# ============================================================================

class _BilateralEngine:
    """双边协商引擎（简化版）- 内部使用"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._simple_service = None

    def _get_service(self):
        """延迟初始化服务"""
        if self._simple_service is None:
            from app.services.trade.simple_negotiation_service import (
                SimpleNegotiationService,
            )
            self._simple_service = SimpleNegotiationService(self.db)
        return self._simple_service

    async def create_session(
        self,
        seller_id: int,
        buyer_id: int,
        listing_id: str,
        starting_price: Optional[float],
        reserve_price: Optional[float],
        max_rounds: int,
        selection_reason: str,
    ) -> NegotiationResult:
        """创建双边协商会话"""
        service = self._get_service()

        result = await service.create_negotiation(
            buyer_id=buyer_id,
            listing_id=listing_id,
            requirements={
                "max_budget": starting_price,
                "preferred_price": reserve_price or starting_price,
                "max_rounds": max_rounds,
            },
        )

        if result.get("success"):
            return create_success_result(
                session_id=result.get("negotiation_id"),
                message="Bilateral session created",
                mechanism=MechanismType.DIRECT,
                engine=EngineType.SIMPLE,
                seller_id=seller_id,
                buyer_id=buyer_id,
                current_price=reserve_price or starting_price,
            )
        else:
            return create_error_result(
                result.get("message", "Unknown error"),
            )

    async def submit_offer(
        self,
        session_id: str,
        user_id: int,
        price: float,
        message: str,
    ) -> OfferResult:
        """提交报价"""
        service = self._get_service()

        result = await service.make_offer(
            negotiation_id=session_id,
            user_id=user_id,
            price=price,
            message=message,
        )

        return OfferResult(
            success=result.get("success", False),
            session_id=session_id,
            offer_accepted=result.get("status") == "accepted",
            message=result.get("message", ""),
            error=result.get("error"),
            status=NegotiationStatus(result.get("status", "active")),
            current_round=result.get("current_round", 0),
        )

    async def get_state(self, session_id: str) -> Optional[SessionState]:
        """获取状态"""
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return None

        return SessionState(
            session_id=session_id,
            mechanism=MechanismType.DIRECT,
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
            shared_board=session.shared_board or {},
            engine_type="simple",
        )

    async def close_session(self, session_id: str) -> NegotiationResult:
        """关闭会话"""
        # 简化版引擎不需要显式关闭
        state = await self.get_state(session_id)
        if state:
            return create_success_result(
                session_id=session_id,
                message="Session closed",
                status=state.status,
            )
        return create_error_result("Session not found", session_id)

    async def get_audit_log(self, session_id: str) -> List[AuditEvent]:
        """获取审计日志（简化版有限）"""
        state = await self.get_state(session_id)
        if not state:
            return []

        # 简化版只返回 shared_board 中的历史
        history = state.shared_board.get("history", [])
        events = []

        for i, item in enumerate(history):
            events.append(AuditEvent(
                sequence=i,
                event_type=item.get("action", "unknown"),
                agent_id=item.get("user_id", 0),
                role=item.get("role", "unknown"),
                payload=item,
                timestamp=datetime.fromisoformat(item.get("timestamp", datetime.utcnow().isoformat())),
            ))

        return events


# ============================================================================
# Auction Engine (事件溯源版)
# ============================================================================

class _AuctionEngine:
    """拍卖引擎（事件溯源版）- 内部使用"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._hybrid_service = None

    def _get_service(self):
        """延迟初始化服务"""
        if self._hybrid_service is None:
            from app.services.trade.hybrid_negotiation_service import (
                HybridNegotiationService,
                AuctionEngine as HybridAuctionEngine,
            )
            self._hybrid_service = HybridAuctionEngine(self.db)
        return self._hybrid_service

    async def create_session(
        self,
        seller_id: int,
        listing_id: str,
        starting_price: Optional[float],
        reserve_price: Optional[float],
        max_rounds: int,
        expected_participants: int,
        selection_reason: str,
    ) -> NegotiationResult:
        """创建拍卖会话"""
        service = self._get_service()

        result = await service.create_session(
            session_id=None,  # 让系统生成
            seller_id=seller_id,
            listing_id=listing_id,
            auction_config={
                "starting_price": starting_price or 0,
                "reserve_price": reserve_price or 0,
                "auction_type": "english",
                "duration_minutes": max_rounds * 10,
            },
        )

        if result.get("engine") == "auction_event_sourced":
            return create_success_result(
                session_id=result.get("session_id"),
                message="Auction session created",
                mechanism=MechanismType.DIRECT,
                engine=EngineType.SIMPLE,
                seller_id=seller_id,
                starting_price=starting_price,
                reserve_price=reserve_price,
            )
        else:
            return create_error_result(
                result.get("message", "Failed to create auction"),
            )

    async def submit_bid(
        self,
        session_id: str,
        bidder_id: int,
        amount: float,
    ) -> BidResult:
        """提交出价"""
        service = self._get_service()

        result = await service.submit_bid(
            session_id=session_id,
            bidder_id=bidder_id,
            amount=amount,
        )

        return BidResult(
            success=result.get("success", False),
            session_id=session_id,
            bid_sequence=result.get("bid_sequence", 0),
            amount=result.get("amount", 0),
            is_highest=result.get("is_highest", False),
            message=result.get("message", ""),
            error=result.get("error"),
            current_highest_bid=result.get("amount"),
        )

    async def get_state(self, session_id: str) -> Optional[SessionState]:
        """获取状态"""
        service = self._get_service()

        result = await service.get_state(session_id)

        if not result:
            return None

        shared_board = result.get("shared_board", {})

        return SessionState(
            session_id=session_id,
            mechanism=MechanismType.DIRECT,
            engine=EngineType.SIMPLE,
            status=NegotiationStatus(result.get("status", "active")),
            seller_id=0,
            listing_id=None,
            current_price=result.get("current_highest_bid"),
            current_round=0,  # 拍卖使用不同计数
            bid_count=result.get("bid_count", 0),
            shared_board=shared_board,
            engine_type="event_sourced",
        )

    async def close_auction(
        self,
        session_id: str,
        seller_id: int,
    ) -> NegotiationResult:
        """关闭拍卖"""
        service = self._get_service()

        result = await service.close_auction(session_id, seller_id)

        if result.get("success"):
            return create_success_result(
                session_id=session_id,
                message="Auction closed",
                winner_id=result.get("winner_id"),
                agreed_price=result.get("final_price"),
            )
        else:
            return create_error_result(
                result.get("message", "Failed to close auction"),
                session_id,
            )

    async def get_audit_log(self, session_id: str) -> List[AuditEvent]:
        """获取完整审计日志"""
        service = self._get_service()

        events_data = await service.get_full_audit_log(session_id)

        events = []
        for item in events_data:
            events.append(AuditEvent(
                sequence=item.get("sequence", 0),
                event_type=item.get("type", "unknown"),
                agent_id=item.get("agent_id", 0),
                role=item.get("role", "unknown"),
                payload=item.get("payload", {}),
                timestamp=datetime.fromisoformat(item.get("timestamp", datetime.utcnow().isoformat())),
                vector_clock=item.get("vector_clock"),
            ))

        return events
