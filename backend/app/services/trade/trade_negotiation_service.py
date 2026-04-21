"""
Trade Negotiation Service - 事件溯源协商底座

Agent-First 架构中的事件溯源底座。
负责高并发拍卖和复杂协商的事件存储、状态投影。

核心职责：
1. 事件写入（唯一真相来源）
2. 状态投影（供查询使用）
3. 拍卖序列化（AuctionModerator）
4. 限流和审计

重要：这是 NegotiationKernel 的事件溯源底座，
主要服务于 AuctionEngine（高并发场景）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.models import (
    NegotiationSessions,
    BlackboardEvents,
    UserAgentConfig,
)
from app.core.errors import ServiceError
from app.services.trade.trade_service import TradeService
from app.services.trade.negotiation_event_store import NegotiationEventStore
from app.services.trade.event_sourcing_blackboard import (
    StateProjector,
    AuctionModerator,
    RateLimiter,
    TemporalGraphMapper,
)

# Agent-First: 导入领域结果类型
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

logger = logging.getLogger(__name__)


class TradeNegotiationService:
    """
    交易协商服务 - 事件溯源底座

    Agent-First 架构中的事件溯源协商底座。
    被 NegotiationKernel 的 AuctionEngine 内部调用。

    核心职责：
    1. 事件写入（唯一真相来源）
    2. 状态投影（供查询使用）
    3. 拍卖序列化（AuctionModerator）
    4. 限流和审计

    适用场景：
    - 1对N 拍卖（高并发）
    - 需要完整审计日志
    - 事件溯源 replay

    注意：双边协商请使用 SimpleNegotiationService。
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_store = NegotiationEventStore(db)
        self.state_projector = StateProjector(db)
        self.rate_limiter = RateLimiter(db)
        self.graph_mapper = TemporalGraphMapper(db)
        
        # 拍卖仲裁器（延迟初始化）
        self._auction_moderator: Optional[AuctionModerator] = None
    
    @property
    def auction_moderator(self) -> AuctionModerator:
        """延迟初始化拍卖仲裁器"""
        if self._auction_moderator is None:
            self._auction_moderator = AuctionModerator(self.db, self.state_projector)
        return self._auction_moderator
    
    # =========================================================================
    # 协商发起 - 由买方基于需求发起
    # =========================================================================
    
    async def initiate_negotiation_by_buyer(
        self,
        buyer_id: int,
        listing_id: str,
        requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        买方基于需求发起协商对话
        
        这是协商的标准流程：
        1. 买方看到商品，产生购买意向
        2. 买方基于自身需求发起协商请求
        3. 系统创建协商会话
        4. 卖方收到通知并响应
        
        Args:
            buyer_id: 买方用户ID
            listing_id: 商品列表ID
            requirements: 买方需求 {
                "max_budget": 1000.0,          # 最高预算
                "preferred_price": 800.0,      # 期望价格
                "quantity": 1,                 # 数量
                "delivery_time": "3_days",     # 交付时间要求
                "quality_requirements": {...}, # 质量要求
                "message": "你好，我对这个商品感兴趣...",  # 初始消息
            }
        
        Returns:
            创建的协商会话信息
        """
        import uuid
        from app.db.models import TradeListings, NegotiationSessions
        from sqlalchemy import select
        
        # 1. 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(buyer_id, "offer")
        if not allowed:
            await self.rate_limiter.record_rejection(buyer_id, "offer")
            raise ServiceError(429, f"Rate limit: {reason}")
        
        # 2. 检查商品是否存在
        stmt = select(TradeListings).where(TradeListings.public_id == listing_id)
        result = await self.db.execute(stmt)
        listing = result.scalar_one_or_none()
        
        if not listing:
            raise ServiceError(404, "Listing not found")
        
        if listing.status != "active":
            raise ServiceError(400, f"Listing is not active: {listing.status}")
        
        # 3. 检查买方是否有权限（不能和自己协商）
        if listing.seller_user_id == buyer_id:
            raise ServiceError(403, "Cannot negotiate with yourself")
        
        # 4. 检查是否已存在进行中的协商
        existing_stmt = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.listing_id == listing_id,
                NegotiationSessions.buyer_user_id == buyer_id,
                NegotiationSessions.status.in_("pending", "active"),
            )
        )
        existing_result = await self.db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        
        if existing:
            return {
                "success": True,
                "negotiation_id": existing.negotiation_id,
                "status": existing.status,
                "message": "Existing negotiation found",
                "is_new": False,
            }

        # 5. 计算并锁定诚意金（标价的5%，最低10元）
        listing_price = listing.price_credits if hasattr(listing, 'price_credits') else 0
        earnest_money = max(listing_price * 0.05, 1000)  # 5%或最低10元(1000分)

        # 检查买方余额是否足够支付诚意金
        from app.services.safety import EscrowService
        escrow_service = EscrowService(self.db)

        # 先尝试锁定诚意金，如果失败则不创建协商
        try:
            # 创建临时协商ID用于诚意金锁定
            temp_negotiation_id = uuid.uuid4().hex[:32]
            escrow = await escrow_service.lock_funds(
                negotiation_id=temp_negotiation_id,
                buyer_id=buyer_id,
                seller_id=listing.seller_user_id,
                listing_id=listing_id,
                amount=earnest_money / 100,  # 转换为元
                expiry_hours=72,  # 诚意金有效期72小时
            )
            escrow_id = escrow.escrow_id
        except Exception as e:
            logger.warning(f"Failed to lock earnest money for buyer {buyer_id}: {e}")
            raise ServiceError(
                400,
                f"无法创建协商：需要支付诚意金 {earnest_money/100:.2f} 元，" +
                "请确保账户余额充足。诚意金将在协商成功时转为部分货款，协商取消时全额退还。"
            )

        # 6. 创建协商会话
        negotiation_id = temp_negotiation_id
        
        session = NegotiationSessions(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            seller_user_id=listing.seller_user_id,
            buyer_user_id=buyer_id,
            status="pending",
            current_round=0,
            seller_floor_price=listing.reserve_price or 0,
            escrow_id=escrow_id,  # 关联托管记录
            shared_board={
                "initiated_by": "buyer",
                "buyer_requirements": requirements,
                "negotiation_history": [],
                "price_evolution": [],
                "earnest_money": {
                    "amount_cents": int(earnest_money),
                    "escrow_id": escrow_id,
                    "locked_at": datetime.utcnow().isoformat(),
                },
            },
        )
        
        self.db.add(session)
        await self.db.flush()
        
        # 6. 写入黑板事件 - 买方发起协商
        event = await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="INITIATE",
            agent_id=buyer_id,
            agent_role="buyer",
            payload={
                "listing_id": listing_id,
                "max_budget": requirements.get("max_budget"),
                "preferred_price": requirements.get("preferred_price"),
                "quantity": requirements.get("quantity", 1),
                "delivery_time": requirements.get("delivery_time"),
                "quality_requirements": requirements.get("quality_requirements"),
                "initial_message": requirements.get("message", ""),
            },
        )
        
        # 7. 如果买方有期望价格，可以立即提交初始报价
        if requirements.get("preferred_price"):
            await self.event_store.append_event(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="OFFER",
                agent_id=buyer_id,
                agent_role="buyer",
                payload={
                    "price": requirements["preferred_price"],
                    "message": requirements.get("message", ""),
                    "is_initial_offer": True,
                },
            )
        
        await self.db.commit()
        
        logger.info(
            f"Negotiation initiated by buyer {buyer_id} for listing {listing_id}, "
            f"negotiation_id={negotiation_id}"
        )
        
        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "status": "pending",
            "seller_id": listing.seller_user_id,
            "buyer_id": buyer_id,
            "event_id": event.event_id,
            "message": "Negotiation initiated successfully",
            "is_new": True,
        }
    
    async def seller_respond_to_inquiry(
        self,
        negotiation_id: str,
        seller_id: int,
        response_type: str,  # "accept", "counter", "reject"
        price: Optional[float] = None,
        message: str = "",
    ) -> Dict[str, Any]:
        """
        卖方响应买方的协商请求
        
        Args:
            negotiation_id: 协商ID
            seller_id: 卖方ID
            response_type: 响应类型 (accept/counter/reject)
            price: 报价/反报价价格
            message: 附带消息
        """
        # 1. 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")
        
        # 2. 验证权限
        if state.seller_id != seller_id:
            raise ServiceError(403, "Not authorized as seller")
        
        # 3. 验证状态
        if state.status not in ["pending", "active"]:
            raise ServiceError(400, f"Cannot respond in status: {state.status}")
        
        # 4. 根据响应类型处理
        if response_type == "accept":
            # 卖方接受买方的初始需求
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="ACCEPT",
                agent_id=seller_id,
                agent_role="seller",
                payload={
                    "response_to": "initiate",
                    "message": message,
                },
                expected_version=state.version,
            )
            
        elif response_type == "counter":
            # 卖方提供反报价
            if not price:
                raise ServiceError(400, "Price required for counter offer")
            
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="OFFER",
                agent_id=seller_id,
                agent_role="seller",
                payload={
                    "price": price,
                    "message": message,
                    "is_counter": True,
                },
                expected_version=state.version,
            )
            
        elif response_type == "reject":
            # 卖方拒绝
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="REJECT",
                agent_id=seller_id,
                agent_role="seller",
                payload={
                    "message": message,
                },
                expected_version=state.version,
            )
        else:
            raise ServiceError(400, f"Invalid response type: {response_type}")
        
        # 5. 计算新状态
        new_state = await self.state_projector.project_negotiation_state(negotiation_id)
        
        return {
            "success": True,
            "event_id": event.event_id,
            "negotiation_id": negotiation_id,
            "response_type": response_type,
            "new_state": new_state.to_dict() if new_state else None,
        }
    
    # =========================================================================
    # 1对1 协商 - 使用 CAS 乐观锁
    # =========================================================================
    
    async def submit_offer_v2(
        self,
        negotiation_id: str,
        agent_id: int,
        price: float,
        message: str = "",
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """
        提交报价 - 事件溯源版本
        
        流程：
        1. 检查限流
        2. 读取当前状态（获取 version）
        3. 使用 CAS 追加事件
        4. 返回新状态
        """
        # 1. 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(
            agent_id, "offer"
        )
        if not allowed:
            await self.rate_limiter.record_rejection(agent_id, "offer")
            raise ServiceError(429, f"Rate limit: {reason}")
        
        # 2. 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")
        
        # 3. 验证权限
        is_seller = state.seller_id == agent_id
        is_buyer = state.buyer_id == agent_id
        
        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")
        
        # 4. 验证轮到谁
        if state.current_turn:
            expected_role = "seller" if is_seller else "buyer"
            if state.current_turn != expected_role:
                raise ServiceError(400, f"Not your turn. Waiting for {state.current_turn}")
        
        # 5. 使用 CAS 追加事件
        try:
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="OFFER",
                agent_id=agent_id,
                agent_role="seller" if is_seller else "buyer",
                payload={
                    "price": price,
                    "message": message,
                    "reasoning": reasoning,
                },
                expected_version=state.version,
            )
        except ServiceError as e:
            if e.status_code == 409:
                # 版本冲突，建议重试
                raise ServiceError(
                    409,
                    "Concurrent modification detected. "
                    "Please re-read the current state and retry."
                )
            raise
        
        # 6. 计算新状态
        new_state = await self.state_projector.project_negotiation_state(negotiation_id)
        
        return {
            "success": True,
            "event_id": event.event_id,
            "negotiation_id": negotiation_id,
            "new_state": new_state.to_dict() if new_state else None,
        }
    
    async def accept_offer_v2(
        self,
        negotiation_id: str,
        agent_id: int,
    ) -> Dict[str, Any]:
        """接受报价 - 事件溯源版本"""
        # 限流检查
        allowed, _ = await self.rate_limiter.check_rate_limit(agent_id, "offer")
        if not allowed:
            raise ServiceError(429, "Rate limit exceeded")
        
        # 获取状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")
        
        # 验证权限（只能由接收方接受）
        is_seller = state.seller_id == agent_id
        is_buyer = state.buyer_id == agent_id
        
        # 检查是否轮到对方
        if state.current_turn == "seller" and is_seller:
            raise ServiceError(400, "Cannot accept your own offer")
        if state.current_turn == "buyer" and is_buyer:
            raise ServiceError(400, "Cannot accept your own offer")
        
        # 追加接受事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="ACCEPT",
            agent_id=agent_id,
            agent_role="seller" if is_seller else "buyer",
            payload={
                "final_price": state.current_price,
                "agreed_by": [state.buyer_id, state.seller_id],
            },
            expected_version=state.version,
        )
        
        return {
            "success": True,
            "event_id": event.event_id,
            "status": "agreed",
        }
    
    # =========================================================================
    # 1对多 竞拍 - 使用 AuctionModerator
    # =========================================================================
    
    async def place_bid_v2(
        self,
        auction_id: str,
        agent_id: int,
        price: float,
        priority: int = 0,
    ) -> Dict[str, Any]:
        """
        参与竞拍 - 通过仲裁器序列化处理
        
        流程：
        1. 限流检查
        2. 提交到仲裁器队列
        3. 仲裁器顺序处理，写入事件
        4. 实时推送状态更新
        """
        # 1. 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(
            agent_id, "bid"
        )
        if not allowed:
            await self.rate_limiter.record_rejection(agent_id, "bid")
            raise ServiceError(429, f"Rate limit: {reason}")
        
        # 2. 提交到仲裁器（异步队列）
        result = await self.auction_moderator.submit_bid(
            session_id=auction_id,
            agent_id=agent_id,
            price=price,
            priority=priority,
        )
        
        return result
    
    async def get_auction_state_v2(
        self,
        auction_id: str,
    ) -> Dict[str, Any]:
        """获取拍卖当前状态"""
        state = await self.state_projector.project_auction_state(auction_id)
        
        if not state:
            raise ServiceError(404, "Auction not found")
        
        return state.to_dict()
    
    # =========================================================================
    # 时序图谱分析
    # =========================================================================
    
    async def analyze_session_graph(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        分析会话的时序图谱
        
        用途：
        1. 可视化 Agent 行为
        2. 检测抢先交易
        3. 发现协同作弊
        4. 安全审计
        """
        # 生成图谱
        graph = await self.graph_mapper.map_events_to_graph(session_id)
        
        # 读取原始事件
        events = await self.event_store.get_events(session_id)
        
        return {
            "session_id": session_id,
            "graph": graph,
            "event_count": len(events),
            "analysis": {
                "anomalies": graph.get("anomalies", []),
                "time_span": graph.get("time_span"),
                "participants": len(graph.get("nodes", [])),
            },
        }
    
    async def get_event_history(
        self,
        session_id: str,
        start_version: int = 0,
        end_version: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        """获取完整的事件历史（用于审计和重放）"""
        events = await self.event_store.get_events(
            session_id,
            start_seq=start_version,
            end_seq=end_version,
        )
        
        return [
            {
                "event_id": e.event_id,
                "sequence": e.sequence_number,
                "type": e.event_type,
                "agent_id": e.agent_id,
                "role": e.agent_role,
                "payload": e.payload,
                "timestamp": e.event_timestamp.isoformat(),
                "vector_clock": e.vector_clock,
            }
            for e in events
        ]
    
    async def replay_to_version(
        self,
        session_id: str,
        target_version: int,
    ) -> Dict[str, Any]:
        """
        重放到指定版本（用于历史状态查询或审计）
        
        这是事件溯源的核心能力之一：
        - 可以随时恢复到任意历史时刻的状态
        - 支持审计和合规检查
        """
        state = await self.state_projector.project_negotiation_state(
            session_id, 
            up_to_sequence=target_version
        )
        
        if not state:
            raise ServiceError(404, "Session not found")
        
        return {
            "session_id": session_id,
            "version": target_version,
            "state": state.to_dict(),
            "note": "Historical state replay",
        }

    # =========================================================================
    # Extended Methods for TradeAgent Compatibility
    # =========================================================================

    async def create_negotiation(
        self,
        seller_user_id: Optional[int],
        buyer_id: Optional[int],
        listing_id: Optional[str],
        asset_id: Optional[str],
        mechanism_type: str,
        reserve_price: Optional[float] = None,
        max_rounds: int = 10,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建协商会话。

        Returns:
            negotiation_id: 协商会话ID
        """
        import uuid

        negotiation_id = uuid.uuid4().hex[:32]

        session = NegotiationSessions(
            negotiation_id=negotiation_id,
            listing_id=listing_id or "",
            seller_user_id=seller_user_id,
            buyer_user_id=buyer_id,
            status="pending",
            current_round=0,
            max_rounds=max_rounds,
            mechanism_type=mechanism_type,
            seller_floor_price=int((reserve_price or 0) * 100),
            shared_board={
                "initial_state": initial_state or {},
                "negotiation_history": [],
                "event_log": [],
            },
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        self.db.add(session)
        await self.db.flush()

        logger.info(f"Created negotiation session: {negotiation_id}")
        return negotiation_id

    async def seller_announce(
        self,
        negotiation_id: str,
        seller_user_id: int,
        announcement: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        卖方发布公告（拍卖）。

        Args:
            announcement: 公告内容 {
                "auction_type": "english",
                "starting_price": 100.0,
                ...
            }
        """
        # 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(seller_user_id, "offer")
        if not allowed:
            raise ServiceError(429, f"Rate limit: {reason}")

        # 获取当前版本
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        if state.seller_id != seller_user_id:
            raise ServiceError(403, "Not authorized as seller")

        # 追加ANNOUNCE事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="auction" if announcement.get("auction_type") else "negotiation",
            event_type="ANNOUNCE",
            agent_id=seller_user_id,
            agent_role="seller",
            payload=announcement,
            expected_version=state.version,
        )

        # 更新session状态为active
        stmt = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            session.status = "active"

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "negotiation_id": negotiation_id,
            "status": "active",
        }

    async def buyer_place_bid(
        self,
        negotiation_id: str,
        buyer_user_id: int,
        amount: float,
        qualifications: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        买方投标/出价（拍卖场景）。
        """
        # 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(buyer_user_id, "bid")
        if not allowed:
            raise ServiceError(429, f"Rate limit: {reason}")

        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 追加BID事件
        event = await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="auction",
            event_type="BID",
            agent_id=buyer_user_id,
            agent_role="bidder",
            payload={
                "price": amount,
                "qualifications": qualifications or {},
            },
        )

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "negotiation_id": negotiation_id,
            "bid_amount": amount,
        }

    async def buyer_make_offer(
        self,
        negotiation_id: str,
        buyer_user_id: int,
        price: float,
        terms: Optional[Dict[str, Any]] = None,
        message: str = "",
    ) -> Dict[str, Any]:
        """
        买方主动报价（双边协商）。
        """
        # 限流检查
        allowed, reason = await self.rate_limiter.check_rate_limit(buyer_user_id, "offer")
        if not allowed:
            raise ServiceError(429, f"Rate limit: {reason}")

        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 使用CAS追加OFFER事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="OFFER",
            agent_id=buyer_user_id,
            agent_role="buyer",
            payload={
                "price": price,
                "terms": terms or {},
                "message": message,
            },
            expected_version=state.version,
        )

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "negotiation_id": negotiation_id,
            "offer_price": price,
        }

    async def seller_respond_to_bid(
        self,
        negotiation_id: str,
        seller_user_id: int,
        response: str,  # "accept", "reject", "counter"
        counter_amount: Optional[float] = None,
        message: str = "",
    ) -> Dict[str, Any]:
        """
        卖方响应投标（接受/拒绝/反报价）。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        if state.seller_id != seller_user_id:
            raise ServiceError(403, "Not authorized as seller")

        # 根据响应类型处理
        if response == "accept":
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="ACCEPT",
                agent_id=seller_user_id,
                agent_role="seller",
                payload={"message": message},
                expected_version=state.version,
            )
        elif response == "reject":
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="REJECT",
                agent_id=seller_user_id,
                agent_role="seller",
                payload={"message": message},
                expected_version=state.version,
            )
        elif response == "counter":
            if not counter_amount:
                raise ServiceError(400, "Counter amount required for counter response")
            event = await self.event_store.append_event_with_cas(
                session_id=negotiation_id,
                session_type="negotiation",
                event_type="COUNTER",
                agent_id=seller_user_id,
                agent_role="seller",
                payload={
                    "counter_price": counter_amount,
                    "message": message,
                },
                expected_version=state.version,
            )
        else:
            raise ServiceError(400, f"Invalid response type: {response}")

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "response": response,
            "negotiation_id": negotiation_id,
        }

    async def get_negotiation(
        self, negotiation_id: str
    ) -> Optional[NegotiationSessions]:
        """
        获取协商会话ORM对象。
        """
        stmt = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_negotiations(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[NegotiationSessions]:
        """
        列出用户的协商会话。
        """
        stmt = select(NegotiationSessions).where(
            or_(
                NegotiationSessions.seller_user_id == user_id,
                NegotiationSessions.buyer_user_id == user_id,
            )
        ).limit(limit)

        if status:
            stmt = stmt.where(NegotiationSessions.status == status)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_negotiations(
        self,
        user_id: int,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        列出协商（简化格式）。
        """
        sessions = await self.list_user_negotiations(user_id, status)
        return [
            {
                "negotiation_id": s.negotiation_id,
                "listing_id": s.listing_id,
                "status": s.status,
                "mechanism_type": s.mechanism_type,
                "current_round": s.current_round,
                "seller_id": s.seller_user_id,
                "buyer_id": s.buyer_user_id,
            }
            for s in sessions
        ]

    async def get_or_create_agent_config(
        self,
        user_id: int,
        agent_role: str,
    ) -> UserAgentConfig:
        """
        获取或创建Agent配置。
        """
        from sqlalchemy import select

        stmt = select(UserAgentConfig).where(
            and_(
                UserAgentConfig.user_id == user_id,
                UserAgentConfig.agent_role == agent_role,
            )
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if not config:
            config = UserAgentConfig(
                user_id=user_id,
                agent_role=agent_role,
                pricing_strategy="balanced",
                auto_accept_threshold=0.95,
                auto_counter_threshold=0.8,
                max_auto_rounds=5,
                use_llm_decision=False,
            )
            self.db.add(config)
            await self.db.flush()

        return config

    async def update_agent_config(
        self,
        user_id: int,
        agent_role: str,
        **kwargs,
    ) -> UserAgentConfig:
        """
        更新Agent配置。
        """
        config = await self.get_or_create_agent_config(user_id, agent_role)

        allowed_fields = [
            "pricing_strategy",
            "auto_accept_threshold",
            "auto_counter_threshold",
            "max_auto_rounds",
            "use_llm_decision",
            "webhook_url",
        ]

        for field, value in kwargs.items():
            if field in allowed_fields and hasattr(config, field):
                setattr(config, field, value)

        await self.db.flush()
        return config

    async def create_blackboard_negotiation(
        self,
        seller_user_id: int,
        buyer_user_id: Optional[int],
        listing_id: str,
        asset_id: str,
        seller_floor_price: float,
        seller_target_price: float,
        starting_price: Optional[float] = None,
    ) -> str:
        """
        创建黑板模式协商会话。
        """
        negotiation_id = await self.create_negotiation(
            seller_user_id=seller_user_id,
            buyer_id=buyer_user_id,
            listing_id=listing_id,
            asset_id=asset_id,
            mechanism_type="blackboard",
            reserve_price=seller_floor_price,
        )

        # 追加FLOOR_SET事件
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="FLOOR_SET",
            agent_id=seller_user_id,
            agent_role="seller",
            payload={
                "floor_price": seller_floor_price,
                "target_price": seller_target_price,
                "starting_price": starting_price,
            },
        )

        await self.db.commit()
        return negotiation_id

    async def set_buyer_ceiling(
        self,
        negotiation_id: str,
        buyer_user_id: int,
        ceiling_price: float,
        target_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        设置买方天花板价格。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 追加CEILING_SET事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="CEILING_SET",
            agent_id=buyer_user_id,
            agent_role="buyer",
            payload={
                "ceiling_price": ceiling_price,
                "target_price": target_price,
            },
            expected_version=state.version,
        )

        # 更新session
        stmt = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            session.buyer_user_id = buyer_user_id
            session.buyer_ceiling_price = int(ceiling_price * 100)

        # 检查是否有交易可能
        deal_possible = True
        if state.seller_floor and ceiling_price < state.seller_floor / 100:
            deal_possible = False

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "deal_possible": deal_possible,
        }

    async def submit_offer(
        self,
        negotiation_id: str,
        from_user_id: int,
        price: float,
        message: str = "",
        reasoning: str = "",
    ) -> Dict[str, Any]:
        """
        黑板模式提交出价（兼容旧接口）。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 验证价格约束
        is_seller = state.seller_id == from_user_id
        is_buyer = state.buyer_id == from_user_id

        if is_seller and state.seller_floor:
            if price < state.seller_floor / 100:
                raise ServiceError(400, "Offer below seller floor price")

        if is_buyer and state.buyer_ceiling:
            if price > state.buyer_ceiling / 100:
                raise ServiceError(400, "Offer above buyer ceiling price")

        # 使用CAS追加OFFER事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="OFFER",
            agent_id=from_user_id,
            agent_role="seller" if is_seller else "buyer",
            payload={
                "price": price,
                "message": message,
                "reasoning": reasoning,
            },
            expected_version=state.version,
        )

        # 计算新状态
        new_state = await self.state_projector.project_negotiation_state(negotiation_id)

        return {
            "success": True,
            "event_id": event.event_id,
            "round": new_state.current_round if new_state else 0,
            "status": new_state.status if new_state else "unknown",
            "current_price": new_state.current_price / 100 if new_state and new_state.current_price else None,
        }

    async def accept_offer(
        self,
        negotiation_id: str,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        接受当前出价。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 验证权限（只能由接收方接受）
        is_seller = state.seller_id == user_id
        is_buyer = state.buyer_id == user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        # 检查不能接受自己的报价
        if state.current_turn == "seller" and is_seller:
            raise ServiceError(400, "Cannot accept your own offer")
        if state.current_turn == "buyer" and is_buyer:
            raise ServiceError(400, "Cannot accept your own offer")

        # 追加ACCEPT事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="ACCEPT",
            agent_id=user_id,
            agent_role="seller" if is_seller else "buyer",
            payload={
                "final_price": state.current_price,
                "agreed_by": [state.buyer_id, state.seller_id],
            },
            expected_version=state.version,
        )

        # 更新session
        stmt = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            session.status = "agreed"
            session.agreed_price = state.current_price

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "status": "agreed",
            "agreed_price": state.current_price / 100 if state.current_price else None,
        }

    async def reject_and_counter(
        self,
        negotiation_id: str,
        user_id: int,
        counter_price: float,
        message: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        拒绝并反报价。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        is_seller = state.seller_id == user_id
        is_buyer = state.buyer_id == user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        # 追加COUNTER事件
        event = await self.event_store.append_event_with_cas(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="COUNTER",
            agent_id=user_id,
            agent_role="seller" if is_seller else "buyer",
            payload={
                "counter_price": counter_price,
                "message": message,
                "reason": reason,
            },
            expected_version=state.version,
        )

        # 计算新状态
        new_state = await self.state_projector.project_negotiation_state(negotiation_id)

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "counter_price": counter_price,
            "round": new_state.current_round if new_state else 0,
            "status": new_state.status if new_state else "unknown",
        }

    async def get_full_blackboard_context(
        self,
        negotiation_id: str,
        for_user_id: int,
    ) -> Dict[str, Any]:
        """
        获取完整的黑板上下文。
        """
        # 获取投影状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 获取事件历史
        events = await self.event_store.get_events(negotiation_id)

        # 获取session详情
        session = await self.get_negotiation(negotiation_id)

        return {
            "negotiation_id": negotiation_id,
            "status": state.status,
            "current_round": state.current_round,
            "current_price": state.current_price / 100 if state.current_price else None,
            "seller_floor": state.seller_floor / 100 if state.seller_floor else None,
            "buyer_ceiling": state.buyer_ceiling / 100 if state.buyer_ceiling else None,
            "current_turn": state.current_turn,
            "history": state.history,
            "event_count": len(events),
            "expires_at": session.expires_at.isoformat() if session and session.expires_at else None,
        }

    async def finalize_settlement(
        self,
        negotiation_id: str,
        seller_id: Optional[int] = None,
        final_price: Optional[float] = None,
        buyer_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        最终结算。
        """
        # 获取当前状态
        state = await self.state_projector.project_negotiation_state(negotiation_id)
        if not state:
            raise ServiceError(404, "Negotiation not found")

        # 获取session
        session = await self.get_negotiation(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation session not found")

        # 验证权限
        if seller_id and session.seller_user_id != seller_id:
            raise ServiceError(403, "Not authorized as seller")

        # 确定最终价格
        settle_price = final_price or (state.current_price / 100 if state.current_price else 0)
        actual_buyer_id = buyer_id or session.buyer_user_id

        # 实际扣款和创建订单
        order_id = None
        if session.listing_id and actual_buyer_id:
            from app.db.models import Users
            from sqlalchemy import select

            buyer_result = await self.db.execute(
                select(Users).where(Users.id == actual_buyer_id)
            )
            buyer_user = buyer_result.scalar_one_or_none()
            if buyer_user:
                try:
                    trade_service = TradeService(self.db)
                    settlement_result = await trade_service.purchase_negotiated(
                        listing_id=session.listing_id,
                        buyer=buyer_user,
                        agreed_price_credits=settle_price,
                    )
                    if settlement_result.get("status") == "completed":
                        order_id = settlement_result.get("order", {}).get("order_id")
                    elif settlement_result.get("status") == "already_purchased":
                        order_id = settlement_result.get("order", {}).get("order_id")
                    else:
                        raise ServiceError(500, settlement_result.get("message", "Settlement failed"))
                except Exception as e:
                    await self.db.rollback()
                    logger.error(f"Settlement failed in finalize_settlement: {e}")
                    raise ServiceError(500, f"Settlement failed: {str(e)}")
            else:
                raise ServiceError(404, "Buyer user not found")

        # 追加SETTLE事件
        event = await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="negotiation",
            event_type="SETTLE",
            agent_id=seller_id or session.seller_user_id or 0,
            agent_role="seller",
            payload={
                "final_price": settle_price,
                "buyer_id": actual_buyer_id,
                "seller_id": session.seller_user_id,
                "order_id": order_id,
            },
        )

        # 更新session状态
        session.status = "settled"
        if not session.agreed_price:
            session.agreed_price = int(settle_price * 100)

        await self.db.commit()

        return {
            "success": True,
            "event_id": event.event_id,
            "status": "settled",
            "settlement": {
                "final_price": settle_price,
                "buyer_id": buyer_id or session.buyer_user_id,
                "seller_id": session.seller_user_id,
                "platform_fee": settle_price * 0.05,
                "seller_proceeds": settle_price * 0.95,
            },
        }

    async def poll_events(
        self,
        user_id: int,
        negotiation_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[BlackboardEvents]:
        """
        轮询事件（替代poll_messages）。

        返回用户参与的协商中的最新事件。
        """
        # 获取用户参与的协商
        if negotiation_id:
            # 检查用户是否有权限查看此协商
            session = await self.get_negotiation(negotiation_id)
            if not session:
                return []
            if session.seller_user_id != user_id and session.buyer_user_id != user_id:
                return []

            # 获取该协商的事件
            events = await self.event_store.get_events(negotiation_id)
            return events[-limit:]
        else:
            # 获取用户所有协商的事件
            sessions = await self.list_user_negotiations(user_id, limit=limit)
            all_events = []
            for session in sessions:
                events = await self.event_store.get_events(session.negotiation_id)
                all_events.extend(events)

            # 按时间排序并限制数量
            all_events.sort(key=lambda e: e.event_timestamp, reverse=True)
            return all_events[:limit]

    # =====================================================================
    # Agent-First: Domain Model Conversions
    # =====================================================================

    def to_negotiation_result(self, session: NegotiationSessions) -> NegotiationResult:
        """转换为领域结果对象"""
        return NegotiationResult(
            success=True,
            session_id=session.negotiation_id,
            status=NegotiationStatus(session.status),
            mechanism=MechanismType.DIRECT,
            engine=EngineType.SIMPLE,
            seller_id=session.seller_user_id,
            buyer_id=session.buyer_user_id,
            winner_id=session.winner_user_id,
            current_price=session.current_price / 100 if session.current_price else None,
            agreed_price=session.agreed_price / 100 if session.agreed_price else None,
            starting_price=session.starting_price / 100 if session.starting_price else None,
            reserve_price=session.reserve_price / 100 if session.reserve_price else None,
            current_round=session.current_round,
            message="Event-sourced negotiation",
            metadata={
                "engine_type": "event_sourced",
                "escrow_id": session.escrow_id,
            },
        )

    def to_session_state(self, session: NegotiationSessions) -> SessionState:
        """转换为会话状态对象"""
        shared_board = session.shared_board or {}

        return SessionState(
            session_id=session.negotiation_id,
            mechanism=MechanismType.DIRECT,
            engine=EngineType.SIMPLE,
            status=NegotiationStatus(session.status),
            seller_id=session.seller_user_id,
            buyer_id=session.buyer_user_id,
            listing_id=session.listing_id,
            current_price=session.current_price / 100 if session.current_price else None,
            agreed_price=session.agreed_price / 100 if session.agreed_price else None,
            starting_price=session.starting_price / 100 if session.starting_price else None,
            reserve_price=session.reserve_price / 100 if session.reserve_price else None,
            current_round=session.current_round,
            max_rounds=session.max_rounds,
            shared_board=shared_board,
            engine_type="event_sourced",
            selection_reason="Event-sourced engine selected for high concurrency",
        )

    def get_engine_capabilities(self) -> Dict[str, Any]:
        """获取引擎能力描述"""
        return {
            "engine_type": "event_sourced",
            "supports_concurrent_bids": True,
            "supports_full_audit": True,
            "optimistic_locking": True,
            "max_participants": 1000,
            "best_for": "1对N拍卖，高并发场景",
        }


# =========================================================================
# 使用示例和最佳实践
# =========================================================================

"""
## 使用示例

### 1. 1对1 协商

```python
service = TradeNegotiationService(db)

# 卖方报价
result = await service.submit_offer_v2(
    negotiation_id="neg_123",
    agent_id=seller_id,
    price=100.0,
    message="Initial offer",
    reasoning="Based on market analysis",
)

# 买方接受
result = await service.accept_offer_v2(
    negotiation_id="neg_123",
    agent_id=buyer_id,
)

# 获取当前状态（通过 StateProjector 计算）
state = await service.state_projector.project_negotiation_state("neg_123")
print(f"Current price: {state.current_price}")
print(f"Status: {state.status}")
```

### 2. 1对多 竞拍

```python
service = TradeNegotiationService(db)

# 多个 Agent 同时出价
# 这些出价会被 AuctionModerator 序列化处理

# Agent A 出价
task1 = service.place_bid_v2("auc_456", agent_a_id, 110.0, priority=1)

# Agent B 出价（几乎同时）
task2 = service.place_bid_v2("auc_456", agent_b_id, 120.0, priority=0)

# Agent C 出价（VIP，高优先级）
task3 = service.place_bid_v2("auc_456", agent_c_id, 115.0, priority=5)

# 所有出价按到达顺序被处理，无冲突
```

### 3. 时序图谱分析

```python
# 分析拍卖过程
analysis = await service.analyze_session_graph("auc_456")

# 检查异常行为
for anomaly in analysis["analysis"]["anomalies"]:
    if anomaly["type"] == "front_running_suspected":
        print(f"Detected front-running: {anomaly}")
    elif anomaly["type"] == "excessive_bidding":
        print(f"Possible attack: {anomaly}")

# 生成可视化图谱（可导出到 Neo4j）
graph = analysis["graph"]
```

### 4. 历史状态重放（审计）

```python
# 查看第10轮时的状态
historical_state = await service.replay_to_version("neg_123", 10)

# 获取完整事件历史
history = await service.get_event_history("neg_123")
for event in history:
    print(f"Round {event['sequence']}: {event['type']} by {event['agent_id']}")
```

## 架构优势

1. **不可否认性**: 所有事件永久记录，无法篡改
2. **可审计**: 完整的历史追溯能力
3. **无冲突**: 1对多场景通过仲裁器消除抢写
4. **高性能**: 1对1场景使用乐观锁，无锁争用
5. **安全性**: 限流和异常检测防止恶意 Agent
6. **可扩展**: 支持时序图谱分析和多模态审计
"""
