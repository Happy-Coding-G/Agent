"""
Trade Agent Worker V2 - Event-driven background task processor.

基于事件溯源的Agent自动决策：
- 轮询活跃协商会话
- 获取最新BlackboardEvents
- 根据状态投影和用户配置自动响应
- 防止自循环（不对自己发出的事件响应）
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.trade_negotiation_service import TradeNegotiationService
from app.db.models import UserAgentConfig, NegotiationSessions
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class TradeAgentWorker:
    """
    交易Agent工作器V2 - 基于事件溯源的后台自动处理。

    运行逻辑：
    1. 轮询活跃协商会话 (status in ["pending", "active"])
    2. 获取每个会话的最新BlackboardEvents
    3. 通过state_projector计算current_turn
    4. 加载用户AgentConfig
    5. 若use_llm_decision=True且轮到该用户，自动响应
    6. 防止自循环：不对自己发出的事件做响应
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.negotiation_service = TradeNegotiationService(db)
        self.running = False
        self.worker_id = f"worker_{id(self)}"

    async def start(self, poll_interval: float = 5.0):
        """启动Worker。"""
        self.running = True
        logger.info(f"TradeAgentWorkerV2 {self.worker_id} started")

        while self.running:
            try:
                await self._process_new_events()
                await self._check_expired_negotiations()
            except Exception as e:
                logger.exception(f"Worker error: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """停止Worker。"""
        self.running = False
        logger.info(f"TradeAgentWorkerV2 {self.worker_id} stopped")

    async def _process_new_events(self):
        """
        处理新事件 - 事件驱动核心逻辑。

        流程：
        1. 查询活跃协商会话
        2. 对每个会话获取最新事件
        3. 根据状态决定是否需要自动响应
        4. 加载用户配置
        5. 执行自动决策
        """
        from sqlalchemy import select, and_

        # 查询活跃协商
        stmt = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.status.in_(["pending", "active"]),
                NegotiationSessions.expires_at > datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        if not sessions:
            return

        logger.debug(f"Processing {len(sessions)} active sessions")

        for session in sessions:
            try:
                await self._process_session(session)
            except Exception as e:
                logger.exception(f"Failed to process session {session.negotiation_id}: {e}")

    async def _process_session(self, session: NegotiationSessions):
        """处理单个协商会话。"""
        negotiation_id = session.negotiation_id

        # 获取当前状态投影
        state = await self.negotiation_service.state_projector.project_negotiation_state(
            negotiation_id
        )
        if not state:
            return

        # 确定当前轮到谁
        current_turn = state.current_turn
        if not current_turn:
            return

        # 确定当前应该行动的用户ID
        if current_turn == "seller":
            current_user_id = state.seller_id
        elif current_turn == "buyer":
            current_user_id = state.buyer_id
        else:
            return

        if not current_user_id:
            return

        # 获取最新事件（用于防止自循环）
        latest_events = await self.negotiation_service.event_store.get_events(
            negotiation_id, start_seq=0
        )
        if not latest_events:
            return

        latest_event = latest_events[-1]

        # 防止自循环：如果最新事件就是自己发出的，不响应
        if latest_event.agent_id == current_user_id:
            logger.debug(f"Skipping self-event for user {current_user_id}")
            return

        # 加载用户Agent配置
        config = await self.negotiation_service.get_or_create_agent_config(
            current_user_id, current_turn
        )

        # 检查是否自动处理
        if not config.use_llm_decision:
            logger.debug(f"User {current_user_id} is in manual mode, skipping")
            return

        # 根据事件类型和当前回合执行自动决策
        await self._execute_auto_decision(
            negotiation_id=negotiation_id,
            session=session,
            state=state,
            latest_event=latest_event,
            current_user_id=current_user_id,
            current_turn=current_turn,
            config=config,
        )

    async def _execute_auto_decision(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        latest_event,
        current_user_id: int,
        current_turn: str,
        config: UserAgentConfig,
    ):
        """执行自动决策。"""
        event_type = latest_event.event_type

        try:
            # 买方决策场景
            if current_turn == "buyer":
                if event_type in ["ANNOUNCE", "COUNTER"]:
                    # 评估并投标/出价
                    await self._buyer_respond_to_offer(
                        negotiation_id, session, state, current_user_id, config
                    )
                elif event_type == "OFFER" and latest_event.agent_role == "seller":
                    # 卖方出价，买方决定接受/拒绝/反报价
                    await self._buyer_evaluate_offer(
                        negotiation_id, state, current_user_id, config
                    )

            # 卖方决策场景
            elif current_turn == "seller":
                if event_type in ["BID", "OFFER"] and latest_event.agent_role == "buyer":
                    # 买方投标/出价，卖方决定接受/拒绝/反报价
                    await self._seller_evaluate_bid(
                        negotiation_id, session, state, latest_event, current_user_id, config
                    )

        except ServiceError as e:
            logger.warning(f"Auto-decision failed for {negotiation_id}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in auto-decision: {e}")

    async def _buyer_respond_to_offer(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        buyer_id: int,
        config: UserAgentConfig,
    ):
        """买方响应卖方公告或反报价。"""
        # 获取当前价格
        current_price = state.current_price / 100 if state.current_price else 0

        # 检查预算
        max_budget = config.auto_accept_threshold or 1000.0

        if current_price > max_budget * 1.2:
            logger.info(f"Buyer {buyer_id}: Price {current_price} exceeds budget")
            return

        # 自动出价
        if session.mechanism_type == "auction":
            # 拍卖：出价略高于当前价格
            bid_amount = min(current_price * 1.1, max_budget * 0.9)
            if bid_amount <= current_price:
                bid_amount = current_price + 1.0

            await self.negotiation_service.buyer_place_bid(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                amount=bid_amount,
                qualifications={"auto": True, "agent_config": config.pricing_strategy},
            )
            logger.info(f"Buyer {buyer_id}: Auto-placed bid {bid_amount}")

        else:
            # 协商：提出初始报价
            offer_price = min(current_price * 0.95, max_budget * 0.9)
            if offer_price <= 0:
                offer_price = max_budget * 0.8

            await self.negotiation_service.buyer_make_offer(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                price=offer_price,
                message="Auto-generated offer",
            )
            logger.info(f"Buyer {buyer_id}: Auto-made offer {offer_price}")

    async def _buyer_evaluate_offer(
        self,
        negotiation_id: str,
        state,
        buyer_id: int,
        config: UserAgentConfig,
    ):
        """买方评估卖方报价。"""
        current_price = state.current_price / 100 if state.current_price else 0
        max_budget = config.auto_accept_threshold or 1000.0

        # 检查轮数限制
        if state.current_round >= config.max_auto_rounds:
            logger.info(f"Buyer {buyer_id}: Max rounds reached, stopping auto-negotiation")
            return

        # 决策逻辑
        if current_price <= max_budget * 0.95:
            # 接受报价
            await self.negotiation_service.accept_offer_v2(
                negotiation_id=negotiation_id,
                agent_id=buyer_id,
            )
            logger.info(f"Buyer {buyer_id}: Auto-accepted offer at {current_price}")

        elif current_price <= max_budget:
            # 反报价
            counter_price = (current_price + max_budget) / 2
            await self.negotiation_service.buyer_make_offer(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                price=counter_price,
                message="Counter offer",
            )
            logger.info(f"Buyer {buyer_id}: Auto-countered with {counter_price}")

        else:
            logger.info(f"Buyer {buyer_id}: Offer {current_price} exceeds budget, no action")

    async def _seller_evaluate_bid(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        latest_event,
        seller_id: int,
        config: UserAgentConfig,
    ):
        """卖方评估买方投标/出价。"""
        # 获取报价
        payload = latest_event.payload
        bid_amount = payload.get("price", 0)
        reserve_price = (session.reserve_price or 0) / 100

        if bid_amount <= 0:
            bid_amount = state.current_price / 100 if state.current_price else 0

        # 决策逻辑
        if bid_amount >= reserve_price * (config.auto_accept_threshold or 0.95):
            # 自动接受
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="accept",
            )
            logger.info(f"Seller {seller_id}: Auto-accepted bid {bid_amount}")

        elif bid_amount >= reserve_price * (config.auto_counter_threshold or 0.8):
            # 自动反报价
            counter_amount = (bid_amount + reserve_price) / 2
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="counter",
                counter_amount=counter_amount,
            )
            logger.info(f"Seller {seller_id}: Auto-countered bid {bid_amount} with {counter_amount}")

        else:
            # 拒绝
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="reject",
            )
            logger.info(f"Seller {seller_id}: Auto-rejected bid {bid_amount}")

    async def _check_expired_negotiations(self):
        """检查并处理过期的协商。"""
        from sqlalchemy import select, and_

        stmt = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.status.in_(["pending", "active"]),
                NegotiationSessions.expires_at < datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(stmt)
        expired = result.scalars().all()

        for session in expired:
            # 追加TIMEOUT事件
            try:
                await self.negotiation_service.event_store.append_event(
                    session_id=session.negotiation_id,
                    session_type="negotiation",
                    event_type="TIMEOUT",
                    agent_id=0,
                    agent_role="system",
                    payload={"reason": "negotiation_expired"},
                )
            except Exception as e:
                logger.warning(f"Failed to append TIMEOUT event: {e}")

            session.status = "terminated"
            logger.info(f"Negotiation {session.negotiation_id} expired and terminated")

        await self.db.commit()


# ========================================================================
# Factory and Runner
# ========================================================================

_agent_worker: Optional[TradeAgentWorker] = None


async def start_agent_worker(db: AsyncSession, poll_interval: float = 5.0):
    """启动全局Agent Worker。"""
    global _agent_worker
    _agent_worker = TradeAgentWorker(db)
    await _agent_worker.start(poll_interval)


def stop_agent_worker():
    """停止全局Agent Worker。"""
    global _agent_worker
    if _agent_worker:
        _agent_worker.stop()
        _agent_worker = None
