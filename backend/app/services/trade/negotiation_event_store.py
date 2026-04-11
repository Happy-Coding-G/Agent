"""
Negotiation Event Store - 事件存储

负责将事件写入黑板（Event Sourcing Blackboard）。
这是事件溯源架构的核心组件。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.db.models import (
    BlackboardEvents,
    NegotiationSessions,
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class NegotiationEventStore:
    """
    协商事件存储

    职责：
    1. 向黑板追加事件（Append-only）
    2. 生成序列号
    3. 验证事件有效性
    4. 集成限流和审计
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def append_event(
        self,
        session_id: str,
        session_type: str,
        event_type: str,
        agent_id: int,
        agent_role: str,
        payload: Dict[str, Any],
        vector_clock: Optional[Dict[str, int]] = None,
    ) -> BlackboardEvents:
        """
        向黑板追加事件

        Args:
            session_id: 会话ID
            session_type: "negotiation" 或 "auction"
            event_type: 事件类型 (BID, OFFER, COUNTER, etc.)
            agent_id: Agent ID
            agent_role: 角色 (buyer, seller, bidder)
            payload: 事件载荷
            vector_clock: 逻辑时钟（用于分布式因果排序）

        Returns:
            创建的事件记录

        Raises:
            ServiceError: 如果事件无效或限流
        """
        # 1. 验证事件
        await self._validate_event(
            session_id, session_type, event_type, agent_id, payload
        )

        # 2. 生成序列号（原子递增）
        sequence_number = await self._get_next_sequence(session_id)

        # 3. 生成逻辑时钟（如果没有提供）
        if vector_clock is None:
            vector_clock = await self._generate_vector_clock(session_id, agent_id)

        # 4. 创建事件
        event = BlackboardEvents(
            event_id=uuid.uuid4().hex[:32],
            session_id=session_id,
            session_type=session_type,
            sequence_number=sequence_number,
            event_type=event_type,
            agent_id=agent_id,
            agent_role=agent_role,
            payload=payload,
            event_timestamp=datetime.now(timezone.utc),
            vector_clock=vector_clock,
        )

        self.db.add(event)
        await self.db.flush()

        logger.info(
            f"Event appended: {event_type} for session {session_id} "
            f"by agent {agent_id} (seq={sequence_number})"
        )

        return event

    async def append_event_with_cas(
        self,
        session_id: str,
        session_type: str,
        event_type: str,
        agent_id: int,
        agent_role: str,
        payload: Dict[str, Any],
        expected_version: int,
    ) -> BlackboardEvents:
        """
        使用 CAS 乐观锁追加事件

        用于 1对1 协商场景，确保 Agent 基于正确的版本号进行操作。

        Args:
            expected_version: 期望的当前版本号（用于乐观锁）

        Raises:
            ServiceError(409): 如果版本冲突
        """
        # 检查当前版本
        current_version = await self._get_current_version(session_id)

        if current_version != expected_version:
            raise ServiceError(
                409,
                f"Concurrent modification: expected version {expected_version}, "
                f"but current is {current_version}",
            )

        # 版本匹配，追加事件
        return await self.append_event(
            session_id=session_id,
            session_type=session_type,
            event_type=event_type,
            agent_id=agent_id,
            agent_role=agent_role,
            payload=payload,
            vector_clock={"agent": agent_id, "seq": expected_version + 1},
        )

    async def get_events(
        self,
        session_id: str,
        start_seq: int = 0,
        end_seq: Optional[int] = None,
        event_types: Optional[list] = None,
    ) -> list[BlackboardEvents]:
        """读取事件流"""
        stmt = (
            select(BlackboardEvents)
            .where(
                and_(
                    BlackboardEvents.session_id == session_id,
                    BlackboardEvents.sequence_number >= start_seq,
                )
            )
            .order_by(BlackboardEvents.sequence_number)
        )

        if end_seq:
            stmt = stmt.where(BlackboardEvents.sequence_number <= end_seq)

        if event_types:
            stmt = stmt.where(BlackboardEvents.event_type.in_(event_types))

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_latest_event(
        self, session_id: str, event_type: Optional[str] = None
    ) -> Optional[BlackboardEvents]:
        """获取最新事件"""
        stmt = (
            select(BlackboardEvents)
            .where(BlackboardEvents.session_id == session_id)
            .order_by(BlackboardEvents.sequence_number.desc())
            .limit(1)
        )

        if event_type:
            stmt = stmt.where(BlackboardEvents.event_type == event_type)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_next_sequence(self, session_id: str) -> int:
        """获取下一个序列号（原子递增）"""
        # 查询当前最大序列号
        stmt = select(func.max(BlackboardEvents.sequence_number)).where(
            BlackboardEvents.session_id == session_id
        )
        result = await self.db.execute(stmt)
        max_seq = result.scalar()

        return (max_seq or 0) + 1

    async def _get_current_version(self, session_id: str) -> int:
        """获取当前版本号（即最新事件的序列号）"""
        stmt = select(func.max(BlackboardEvents.sequence_number)).where(
            BlackboardEvents.session_id == session_id
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def _validate_event(
        self,
        session_id: str,
        session_type: str,
        event_type: str,
        agent_id: int,
        payload: Dict[str, Any],
    ) -> None:
        """验证事件有效性"""
        # INITIATE 事件是创建会话的，不需要检查会话是否存在
        if event_type != "INITIATE":
            # 1. 检查会话存在
            if session_type == "negotiation":
                stmt = select(NegotiationSessions).where(
                    NegotiationSessions.negotiation_id == session_id
                )
                result = await self.db.execute(stmt)
                session = result.scalar_one_or_none()

                if not session:
                    raise ServiceError(404, "Negotiation session not found")

                if session.status in ["completed", "cancelled", "agreed"]:
                    raise ServiceError(400, f"Negotiation already {session.status}")

        # 2. 验证事件类型
        valid_types = [
            # 传统交易事件
            "INITIATE",  # 买方发起协商
            "ANNOUNCE",  # 卖方公告
            "BID",
            "OFFER",
            "COUNTER",
            "ACCEPT",
            "REJECT",
            "WITHDRAW",
            "CEILING_SET",
            "FLOOR_SET",
            "AGREEMENT",
            "SETTLE",    # 最终结算
            "TIMEOUT",
            # 数据权益相关事件 (Phase 1)
            "DATA_ASSET_REGISTER",      # 数据资产登记
            "DATA_RIGHTS_NEGOTIATION_INIT",  # 数据权益协商发起
            "DATA_RIGHTS_GRANT",        # 数据权益授予
            "DATA_RIGHTS_COUNTER",      # 数据权益反报价
            "USAGE_SCOPE_DEFINE",       # 使用范围定义
            "COMPUTATION_AGREEMENT",    # 计算协议达成
            "DATA_ACCESS_AUDIT",        # 数据访问审计
            "POLICY_VIOLATION",         # 策略违规
            "RIGHTS_REVOKE",            # 权益撤销
        ]
        if event_type not in valid_types:
            raise ServiceError(400, f"Invalid event type: {event_type}")

        # 3. 验证载荷（使用 Pydantic）
        from app.services.trade.event_sourcing_blackboard import EVENT_PAYLOADS
        from app.services.trade.data_rights_events import DATA_RIGHTS_PAYLOADS

        # 合并所有载荷模型
        all_payload_models = {**EVENT_PAYLOADS, **DATA_RIGHTS_PAYLOADS}

        payload_model = all_payload_models.get(event_type)
        if payload_model:
            try:
                validated = payload_model(**payload)
                # 更新 payload 为验证后的数据（可能包含默认值和转换）
                payload.clear()
                payload.update(validated.model_dump())
            except Exception as e:
                raise ServiceError(400, f"Invalid payload: {e}")

    async def _generate_vector_clock(
        self, session_id: str, agent_id: int
    ) -> Dict[str, int]:
        """生成逻辑时钟"""
        # 查询该 Agent 在此会话中的事件数
        stmt = select(func.count(BlackboardEvents.id)).where(
            and_(
                BlackboardEvents.session_id == session_id,
                BlackboardEvents.agent_id == agent_id,
            )
        )
        result = await self.db.execute(stmt)
        count = result.scalar() or 0

        return {
            str(agent_id): count + 1,
            "session": await self._get_current_version(session_id) + 1,
        }

    async def check_causality(
        self, event1: BlackboardEvents, event2: BlackboardEvents
    ) -> str:
        """
        检查两个事件的因果关系

        Returns:
            "before": event1 发生在 event2 之前
            "after": event1 发生在 event2 之后
            "concurrent": 并发（无因果关系）
        """
        clock1 = event1.vector_clock
        clock2 = event2.vector_clock

        # 比较逻辑时钟
        dominates_1 = all(
            clock1.get(k, 0) <= clock2.get(k, 0) for k in set(clock1) | set(clock2)
        )
        dominates_2 = all(
            clock2.get(k, 0) <= clock1.get(k, 0) for k in set(clock1) | set(clock2)
        )

        if dominates_1 and not dominates_2:
            return "before"
        elif dominates_2 and not dominates_1:
            return "after"
        else:
            return "concurrent"
