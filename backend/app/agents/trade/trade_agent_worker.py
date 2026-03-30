"""
Trade Agent Worker - Background task processor for multi-agent negotiation.

解决不同用户Agent的异步执行问题：
- 定期轮询消息队列
- 根据用户配置自动执行Agent决策
- 支持自动模式和人工干预模式
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade import NegotiationService
from app.db.models import AgentMessageQueue, UserAgentConfig, NegotiationSessions
from app.core.errors import ServiceError
from .trade_graph import MessageType

logger = logging.getLogger(__name__)


class TradeAgentWorker:
    """
    交易Agent工作器 - 后台自动处理协商消息。

    运行逻辑：
    1. 轮询待处理消息 (AgentMessageQueue)
    2. 根据消息类型和用户配置执行决策
    3. 发送响应消息
    4. 支持自动/半自动/人工三种模式
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.negotiation_service = NegotiationService(db)
        self.running = False
        self.worker_id = f"worker_{id(self)}"

    async def start(self, poll_interval: float = 5.0):
        """启动Worker。"""
        self.running = True
        logger.info(f"TradeAgentWorker {self.worker_id} started")

        while self.running:
            try:
                await self._process_pending_messages()
                await self._check_expired_negotiations()
            except Exception as e:
                logger.exception(f"Worker error: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """停止Worker。"""
        self.running = False
        logger.info(f"TradeAgentWorker {self.worker_id} stopped")

    async def _process_pending_messages(self):
        """处理待处理消息。"""
        from sqlalchemy import select, and_

        # 获取所有待处理消息
        stmt = (
            select(AgentMessageQueue)
            .where(AgentMessageQueue.status == "pending")
            .order_by(AgentMessageQueue.priority.desc(), AgentMessageQueue.created_at.asc())
            .limit(10)
        )
        result = await self.db.execute(stmt)
        messages = result.scalars().all()

        for msg in messages:
            try:
                await self._handle_message(msg)
            except Exception as e:
                logger.exception(f"Failed to process message {msg.message_id}: {e}")
                await self.negotiation_service.mark_message_processed(
                    msg.message_id,
                    self.worker_id,
                    error=str(e),
                )

    async def _handle_message(self, msg: AgentMessageQueue):
        """处理单条消息。"""
        logger.info(f"Processing message {msg.message_id}: {msg.msg_type}")

        # 获取用户Agent配置
        config = await self.negotiation_service.get_or_create_agent_config(
            msg.to_agent_user_id,
            "buyer" if msg.msg_type in ["ANNOUNCE", "COUNTER", "ACCEPT", "REJECT"] else "seller",
        )

        # 检查是否自动处理
        if not config.use_llm_decision:
            # 人工模式 - 不自动处理，等待用户操作
            logger.info(f"User {msg.to_agent_user_id} is in manual mode, skipping auto-processing")
            return

        # 自动处理消息
        handler = self._get_handler(msg.msg_type)
        if handler:
            await handler(msg, config)

        # 标记为已处理
        await self.negotiation_service.mark_message_processed(
            msg.message_id,
            self.worker_id,
        )

    def _get_handler(self, msg_type: str):
        """获取消息处理器。"""
        handlers = {
            MessageType.ANNOUNCE.value: self._handle_announce,
            MessageType.BID.value: self._handle_bid,
            MessageType.OFFER.value: self._handle_offer,
            MessageType.COUNTER.value: self._handle_counter,
        }
        return handlers.get(msg_type)

    async def _handle_announce(self, msg: AgentMessageQueue, config: UserAgentConfig):
        """
        Buyer Agent 处理卖方公告。

        决策逻辑：
        1. 评估资产是否符合需求
        2. 评估价格是否在预算内
        3. 决定是否投标
        """
        negotiation = await self.negotiation_service.get_negotiation(msg.negotiation_id)
        if not negotiation:
            return

        payload = msg.payload
        starting_price = payload.get("starting_price", 0)

        # 检查预算
        # TODO: Get buyer's budget from config or user profile
        max_budget = config.auto_accept_threshold or 1000.0

        if starting_price > max_budget * 1.2:
            logger.info(f"Buyer {msg.to_agent_user_id}: Announcement price {starting_price} exceeds budget")
            return

        # 自动投标
        bid_amount = min(starting_price * 1.1, max_budget * 0.9)

        await self.negotiation_service.buyer_place_bid(
            negotiation_id=msg.negotiation_id,
            buyer_user_id=msg.to_agent_user_id,
            amount=bid_amount,
            qualifications={"auto": True, "agent_config": config.pricing_strategy},
        )

        logger.info(f"Buyer {msg.to_agent_user_id}: Auto-placed bid {bid_amount}")

    async def _handle_bid(self, msg: AgentMessageQueue, config: UserAgentConfig):
        """
        Seller Agent 处理买方投标。

        决策逻辑：
        1. 评估出价是否达到底价
        2. 根据策略决定接受/拒绝/反报价
        """
        negotiation = await self.negotiation_service.get_negotiation(msg.negotiation_id)
        if not negotiation:
            return

        payload = msg.payload
        bid_amount = payload.get("amount", 0)
        reserve_price = (negotiation.reserve_price or 0) / 100

        # 决策逻辑
        if bid_amount >= reserve_price * (config.auto_accept_threshold or 0.95):
            # 自动接受
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=msg.negotiation_id,
                seller_user_id=msg.to_agent_user_id,
                response="accept",
            )
            logger.info(f"Seller {msg.to_agent_user_id}: Auto-accepted bid {bid_amount}")

        elif bid_amount >= reserve_price * (config.auto_counter_threshold or 0.8):
            # 自动反报价
            counter_amount = (bid_amount + reserve_price) / 2
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=msg.negotiation_id,
                seller_user_id=msg.to_agent_user_id,
                response="counter",
                counter_amount=counter_amount,
            )
            logger.info(f"Seller {msg.to_agent_user_id}: Auto-countered bid {bid_amount} with {counter_amount}")

        else:
            # 拒绝
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=msg.negotiation_id,
                seller_user_id=msg.to_agent_user_id,
                response="reject",
            )
            logger.info(f"Seller {msg.to_agent_user_id}: Auto-rejected bid {bid_amount}")

    async def _handle_offer(self, msg: AgentMessageQueue, config: UserAgentConfig):
        """Seller Agent 处理买方主动报价（双边协商）。"""
        negotiation = await self.negotiation_service.get_negotiation(msg.negotiation_id)
        if not negotiation:
            return

        payload = msg.payload
        offer_price = payload.get("price", 0)
        reserve_price = (negotiation.reserve_price or 0) / 100

        # 类似BID的处理逻辑
        if offer_price >= reserve_price * 0.95:
            # 接受
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=msg.negotiation_id,
                seller_user_id=msg.to_agent_user_id,
                response="accept",
            )
        elif offer_price >= reserve_price * 0.8:
            # 反报价
            counter = (offer_price + reserve_price) / 2
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=msg.negotiation_id,
                seller_user_id=msg.to_agent_user_id,
                response="counter",
                counter_amount=counter,
            )

    async def _handle_counter(self, msg: AgentMessageQueue, config: UserAgentConfig):
        """
        Buyer Agent 处理卖方反报价。

        决策逻辑：
        1. 检查反报价是否在预算内
        2. 检查是否超过最大轮数
        3. 决定接受/继续协商/退出
        """
        negotiation = await self.negotiation_service.get_negotiation(msg.negotiation_id)
        if not negotiation:
            return

        payload = msg.payload
        counter_amount = payload.get("counter_amount", 0)

        # 检查是否超过最大轮数
        if negotiation.current_round >= config.max_auto_rounds:
            logger.info(f"Buyer {msg.to_agent_user_id}: Max rounds reached, stopping auto-negotiation")
            return

        # 检查预算
        max_budget = config.auto_accept_threshold or 1000.0

        if counter_amount <= max_budget * 0.95:
            # 接受反报价
            # 注意：这里需要一个新的方法buyer_accept_counter
            logger.info(f"Buyer {msg.to_agent_user_id}: Would accept counter {counter_amount}")
        elif counter_amount <= max_budget:
            # 继续出价
            new_offer = (counter_amount + max_budget) / 2
            await self.negotiation_service.buyer_make_offer(
                negotiation_id=msg.negotiation_id,
                buyer_user_id=msg.to_agent_user_id,
                price=new_offer,
            )
            logger.info(f"Buyer {msg.to_agent_user_id}: Counter-offered with {new_offer}")

    async def _check_expired_negotiations(self):
        """检查并处理过期的协商。"""
        from sqlalchemy import select, and_

        stmt = (
            select(NegotiationSessions)
            .where(
                and_(
                    NegotiationSessions.status.in_(["pending", "active"]),
                    NegotiationSessions.expires_at < datetime.now(timezone.utc),
                )
            )
        )
        result = await self.db.execute(stmt)
        expired = result.scalars().all()

        for session in expired:
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
