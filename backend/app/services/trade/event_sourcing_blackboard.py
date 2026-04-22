"""
Event Sourcing Blackboard - 事件溯源黑板模式

核心组件：
1. StateProjector: 状态投影仪，将事件流折叠为当前状态
2. AuctionModerator: 拍卖仲裁器，序列化处理多 Agent 竞拍
3. RateLimiter: 频率限流器，防止恶意 Agent
4. TemporalGraphMapper: 时序图谱映射器

设计原则：
- 只追加事件，不修改历史
- 通过重放事件计算状态
- 支持时序分析和审计
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.db.models import (
    BlackboardEvents,
    BlackboardSnapshots,
    AgentRateLimit,
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Event Models - 强类型事件定义
# ============================================================================


class BidPayload(BaseModel):
    """竞拍事件载荷"""

    price: float = Field(..., gt=0, description="出价金额")
    currency: str = Field(default="CNY", description="货币类型")
    strategy_hint: Optional[str] = Field(None, description="出价策略提示")

    @validator("price")
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be positive")
        return v


class OfferPayload(BaseModel):
    """协商报价事件载荷"""

    price: float = Field(..., gt=0)
    message: str = Field(default="", max_length=1000)
    reasoning: str = Field(default="", max_length=2000)
    is_final: bool = Field(default=False, description="是否为最终报价")


class CounterPayload(BaseModel):
    """反报价事件载荷"""

    counter_price: float = Field(..., gt=0)
    original_offer_id: str = Field(..., description="原始报价ID")
    message: str = Field(default="")


class AgreementPayload(BaseModel):
    """协议达成事件载荷"""

    final_price: float = Field(..., gt=0)
    agreed_by: List[int] = Field(..., description="双方Agent ID")


# 事件载荷类型映射
EVENT_PAYLOADS = {
    "BID": BidPayload,
    "OFFER": OfferPayload,
    "COUNTER": CounterPayload,
    "ACCEPT": AgreementPayload,
}

# 导入并合并数据权益事件载荷
from app.services.trade.data_rights_events import (
    DATA_RIGHTS_PAYLOADS,
    DataAssetRegisterPayload,
    DataRightsPayload,
    DataRightsCounterPayload,
    ComputationAgreementPayload,
    DataAccessAuditPayload,
    PolicyViolationPayload,
    RightsRevokePayload,
)

# 合并所有事件载荷
ALL_EVENT_PAYLOADS = {**EVENT_PAYLOADS, **DATA_RIGHTS_PAYLOADS}


# ============================================================================
# State Models - 投影状态
# ============================================================================


@dataclass
class NegotiationState:
    """协商会话的当前状态（由 StateProjector 计算得出）"""

    session_id: str
    current_round: int = 0
    current_price: Optional[int] = None
    status: str = "pending"  # pending, active, agreed, rejected, cancelled

    # 双方信息
    buyer_id: int = 0
    seller_id: int = 0
    buyer_ceiling: Optional[int] = None
    seller_floor: Optional[int] = None

    # 当前轮到谁
    current_turn: str = "seller"  # seller, buyer

    # 历史
    history: List[Dict[str, Any]] = field(default_factory=list)

    # 版本号（用于乐观锁）
    version: int = 0

    # 最后更新时间
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "current_round": self.current_round,
            "current_price": self.current_price,
            "status": self.status,
            "buyer_id": self.buyer_id,
            "seller_id": self.seller_id,
            "buyer_ceiling": self.buyer_ceiling,
            "seller_floor": self.seller_floor,
            "current_turn": self.current_turn,
            "history": self.history[-5:],  # 只保留最近5条
            "version": self.version,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class AuctionState:
    """拍卖会话的当前状态"""

    session_id: str
    current_price: int = 0
    highest_bidder: Optional[int] = None
    bid_count: int = 0
    status: str = "active"  # active, ended, cancelled

    # 出价历史（按时间排序）
    bid_history: List[Dict[str, Any]] = field(default_factory=list)

    # 参与者
    participants: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "current_price": self.current_price,
            "highest_bidder": self.highest_bidder,
            "bid_count": self.bid_count,
            "status": self.status,
            "bid_history": self.bid_history[-10:],  # 最近10条
            "participant_count": len(self.participants),
        }


# ============================================================================
# State Projector - 状态投影仪
# ============================================================================


class StateProjector:
    """
    状态投影仪 - 将事件流折叠为当前状态

    职责：
    1. 读取事件流
    2. 应用事件到状态
    3. 管理快照优化
    4. 支持时序查询
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._snapshot_interval = 50  # 每50个事件生成快照

    async def project_negotiation_state(
        self, session_id: str, up_to_sequence: Optional[int] = None
    ) -> Optional[NegotiationState]:
        """
        计算协商会话的当前状态

        Args:
            session_id: 会话ID
            up_to_sequence: 计算到指定序列号的状态（用于历史查询）

        Returns:
            NegotiationState 或 None（如果会话不存在）
        """
        # 1. 查找最近的快照
        snapshot = await self._get_latest_snapshot(session_id)

        # 2. 从快照之后读取事件
        start_seq = snapshot.sequence_number + 1 if snapshot else 0
        events = await self._get_events(session_id, start_seq, up_to_sequence)

        if not events and not snapshot:
            return None

        # 3. 初始化状态
        if snapshot:
            state = self._state_from_snapshot(snapshot)
        else:
            state = await self._init_negotiation_state(session_id)

        # 4. 应用事件
        for event in events:
            state = self._apply_negotiation_event(state, event)

        # 5. 检查是否需要生成新快照
        if len(events) >= self._snapshot_interval:
            await self._create_snapshot(session_id, state)

        return state

    async def project_auction_state(
        self, session_id: str, up_to_sequence: Optional[int] = None
    ) -> Optional[AuctionState]:
        """计算拍卖会话的当前状态"""
        events = await self._get_events(session_id, 0, up_to_sequence)

        if not events:
            return None

        state = AuctionState(session_id=session_id)

        for event in events:
            state = self._apply_auction_event(state, event)

        return state

    async def _get_latest_snapshot(
        self, session_id: str
    ) -> Optional[BlackboardSnapshots]:
        """获取最新的状态快照"""
        stmt = (
            select(BlackboardSnapshots)
            .where(BlackboardSnapshots.session_id == session_id)
            .order_by(desc(BlackboardSnapshots.sequence_number))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_events(
        self, session_id: str, start_seq: int, end_seq: Optional[int] = None
    ) -> List[BlackboardEvents]:
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

        result = await self.db.execute(stmt)
        return result.scalars().all()

    def _apply_negotiation_event(
        self, state: NegotiationState, event: BlackboardEvents
    ) -> NegotiationState:
        """应用单个事件到协商状态"""
        payload = event.payload

        if event.event_type == "INITIATE":
            # 买方发起协商
            state.buyer_id = event.agent_id
            state.status = "pending"
            state.current_round = 0
            # 记录买方预算
            if payload.get("max_budget"):
                state.buyer_ceiling = int(payload.get("max_budget", 0) * 100)

        elif event.event_type == "OFFER":
            state.current_price = int(payload.get("price", 0) * 100)
            state.current_round += 1
            state.current_turn = "buyer" if event.agent_role == "seller" else "seller"
            state.status = "active"

        elif event.event_type == "COUNTER":
            state.current_price = int(payload.get("counter_price", 0) * 100)
            state.current_round += 1
            state.current_turn = "buyer" if event.agent_role == "seller" else "seller"

        elif event.event_type == "ACCEPT":
            state.status = "agreed"
            state.current_turn = None

        elif event.event_type == "REJECT":
            state.status = "rejected"

        elif event.event_type == "WITHDRAW":
            state.status = "cancelled"

        elif event.event_type == "CEILING_SET":
            if event.agent_role == "buyer":
                state.buyer_ceiling = int(payload.get("ceiling_price", 0) * 100)
                state.buyer_id = event.agent_id

        elif event.event_type == "FLOOR_SET":
            if event.agent_role == "seller":
                state.seller_floor = int(payload.get("floor_price", 0) * 100)
                state.seller_id = event.agent_id

        # 记录历史
        state.history.append(
            {
                "round": state.current_round,
                "event": event.event_type,
                "by": event.agent_role,
                "price": state.current_price,
                "timestamp": event.event_timestamp.isoformat(),
            }
        )

        state.version = event.sequence_number
        state.last_updated = event.event_timestamp

        return state

    def _apply_auction_event(
        self, state: AuctionState, event: BlackboardEvents
    ) -> AuctionState:
        """应用单个事件到拍卖状态"""
        if event.event_type == "BID":
            price_cents = int(event.payload.get("price", 0) * 100)

            if price_cents > state.current_price:
                state.current_price = price_cents
                state.highest_bidder = event.agent_id
                state.bid_count += 1

                state.bid_history.append(
                    {
                        "bidder": event.agent_id,
                        "price": price_cents,
                        "timestamp": event.event_timestamp.isoformat(),
                    }
                )

            if event.agent_id not in state.participants:
                state.participants.append(event.agent_id)

        elif event.event_type == "TIMEOUT":
            state.status = "ended"

        elif event.event_type == "WITHDRAW":
            if event.agent_id in state.participants:
                state.participants.remove(event.agent_id)

        return state

    async def _init_negotiation_state(self, session_id: str) -> NegotiationState:
        """初始化会话状态（NegotiationSessions 表已移除，返回默认状态）"""
        return NegotiationState(session_id=session_id)

    def _state_from_snapshot(self, snapshot: BlackboardSnapshots) -> NegotiationState:
        """从快照恢复状态"""
        state_dict = snapshot.state
        return NegotiationState(session_id=snapshot.session_id, **state_dict)

    async def _create_snapshot(self, session_id: str, state: NegotiationState) -> None:
        """创建状态快照"""
        snapshot = BlackboardSnapshots(
            session_id=session_id,
            sequence_number=state.version,
            state=state.to_dict(),
            event_count=state.version,
        )
        self.db.add(snapshot)
        await self.db.commit()
        logger.info(
            f"Created snapshot for session {session_id} at version {state.version}"
        )


# ============================================================================
# Auction Moderator - 拍卖仲裁器
# ============================================================================


class AuctionModerator:
    """
    拍卖仲裁器 - 序列化处理竞拍请求

    在1对多竞拍场景下，多个 Agent 同时出价会导致严重的乐观锁冲突。
    拍卖仲裁器通过单线程队列确保出价按到达顺序处理，消除物理层面的抢写。

    特性：
    1. asyncio.Queue 保证 FIFO
    2. 支持优先级出价（VIP Agent）
    3. 批量处理减少数据库往返
    4. 实时推送状态更新
    """

    def __init__(self, db: AsyncSession, state_projector: StateProjector):
        self.db = db
        self.state_projector = state_projector

        # 每个拍卖会话一个队列
        self._queues: Dict[str, asyncio.Queue] = {}
        self._processing: Dict[str, asyncio.Task] = {}

        # 实时订阅者（用于 SSE 推送）
        self._subscribers: Dict[str, List[Callable]] = {}

    async def submit_bid(
        self,
        session_id: str,
        agent_id: int,
        price: float,
        priority: int = 0,
        strategy_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        提交出价到仲裁器

        Args:
            session_id: 拍卖会话ID
            agent_id: 出价者ID
            price: 出价金额
            priority: 优先级（0-9，越大越优先）
            strategy_hint: 策略提示

        Returns:
            出价结果
        """
        # 获取或创建队列
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.PriorityQueue()
            self._processing[session_id] = asyncio.create_task(
                self._process_auction_queue(session_id)
            )

        queue = self._queues[session_id]

        # 创建出价请求
        bid_request = {
            "agent_id": agent_id,
            "price": price,
            "strategy_hint": strategy_hint,
            "submitted_at": datetime.now(timezone.utc),
        }

        # 放入队列（优先级越小越先处理，所以取反）
        await queue.put((-priority, bid_request))

        logger.info(
            f"Bid queued: session={session_id}, agent={agent_id}, price={price}"
        )

        # 等待处理完成（或者设置超时）
        # 实际实现中可以用 Event 或 Future 来异步通知
        return {
            "status": "queued",
            "message": "Bid submitted to moderator queue",
        }

    async def _process_auction_queue(self, session_id: str):
        """处理拍卖队列 - 单线程顺序处理"""
        queue = self._queues[session_id]

        while True:
            try:
                # 等待出价（超时检查是否结束）
                priority, bid_request = await asyncio.wait_for(queue.get(), timeout=1.0)

                # 处理出价
                result = await self._execute_bid(session_id, bid_request)

                # 通知订阅者
                await self._notify_subscribers(session_id, result)

            except asyncio.TimeoutError:
                # 检查拍卖是否结束
                if await self._is_auction_ended(session_id):
                    break
            except Exception as e:
                logger.exception(f"Error processing auction queue: {e}")

        # 清理
        del self._queues[session_id]
        del self._processing[session_id]
        logger.info(f"Auction queue stopped: {session_id}")

    async def _execute_bid(
        self, session_id: str, bid_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行出价 - 写入事件溯源黑板"""
        from app.services.trade.negotiation_event_store import NegotiationEventStore

        event_store = NegotiationEventStore(self.db)

        # 1. 写入事件
        event = await event_store.append_event(
            session_id=session_id,
            session_type="auction",
            event_type="BID",
            agent_id=bid_request["agent_id"],
            agent_role="bidder",
            payload={
                "price": bid_request["price"],
                "strategy_hint": bid_request.get("strategy_hint"),
            },
        )

        # 2. 计算最新状态
        state = await self.state_projector.project_auction_state(session_id)

        # 3. 判断是否有效
        is_winning = state.highest_bidder == bid_request["agent_id"]

        result = {
            "event_id": event.event_id,
            "session_id": session_id,
            "agent_id": bid_request["agent_id"],
            "price": bid_request["price"],
            "is_winning": is_winning,
            "current_highest": state.current_price,
            "bid_count": state.bid_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"Bid executed: {result}")
        return result

    async def _is_auction_ended(self, session_id: str) -> bool:
        """检查拍卖是否结束"""
        state = await self.state_projector.project_auction_state(session_id)
        return state is None or state.status in ["ended", "cancelled"]

    def subscribe(self, session_id: str, callback: Callable):
        """订阅拍卖状态更新"""
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        self._subscribers[session_id].append(callback)

    async def _notify_subscribers(self, session_id: str, event: Dict[str, Any]):
        """通知订阅者"""
        callbacks = self._subscribers.get(session_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")


# ============================================================================
# Rate Limiter - 频率限流器
# ============================================================================


class RateLimiter:
    """
    Agent 频率限流器 - 防止恶意 Agent

    策略：
    1. 滑动窗口计数
    2. 冲突检测（短时间内多次乐观锁冲突）
    3. 渐进式惩罚（警告 -> 限速 -> 封禁）
    """

    def __init__(self, db: AsyncSession):
        self.db = db

        # 限流配置
        self._limits = {
            "bid": {"window_seconds": 60, "max_requests": 10, "max_rejected": 5},
            "offer": {"window_seconds": 60, "max_requests": 5, "max_rejected": 3},
            "message": {"window_seconds": 60, "max_requests": 20, "max_rejected": 10},
        }

    async def check_rate_limit(
        self, agent_id: int, limit_type: str, increment: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        检查频率限制

        Returns:
            (是否允许, 拒绝原因)
        """
        config = self._limits.get(limit_type)
        if not config:
            return True, None

        window_start = datetime.now(timezone.utc) - timedelta(
            seconds=config["window_seconds"]
        )

        # 查询当前窗口
        stmt = select(AgentRateLimit).where(
            and_(
                AgentRateLimit.agent_id == agent_id,
                AgentRateLimit.limit_type == limit_type,
                AgentRateLimit.window_start >= window_start,
            )
        )
        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()

        # 检查是否被限速
        if record and record.is_throttled:
            if record.throttle_until and record.throttle_until > datetime.now(
                timezone.utc
            ):
                return False, f"Throttled until {record.throttle_until}"
            else:
                # 解除限速
                record.is_throttled = False
                record.throttle_until = None

        if record:
            # 检查请求数
            if record.request_count >= config["max_requests"]:
                # 触发限速
                record.is_throttled = True
                record.throttle_until = datetime.now(timezone.utc) + timedelta(
                    minutes=5
                )
                await self.db.commit()
                return False, f"Rate limit exceeded. Throttled for 5 minutes."

            # 检查冲突率（被拒绝的请求过多说明可能有攻击）
            if record.rejected_count >= config["max_rejected"]:
                record.is_throttled = True
                record.throttle_until = datetime.now(timezone.utc) + timedelta(
                    minutes=10
                )
                await self.db.commit()
                return False, f"Too many conflicts. Throttled for 10 minutes."

            if increment:
                record.request_count += 1
        else:
            if increment:
                # 创建新记录
                record = AgentRateLimit(
                    agent_id=agent_id,
                    limit_type=limit_type,
                    window_start=datetime.now(timezone.utc),
                    request_count=1,
                )
                self.db.add(record)

        if increment:
            await self.db.commit()

        return True, None

    async def record_rejection(self, agent_id: int, limit_type: str):
        """记录一次被拒绝的请求（用于检测攻击）"""
        window_start = datetime.now(timezone.utc) - timedelta(seconds=60)

        stmt = select(AgentRateLimit).where(
            and_(
                AgentRateLimit.agent_id == agent_id,
                AgentRateLimit.limit_type == limit_type,
                AgentRateLimit.window_start >= window_start,
            )
        )
        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.rejected_count += 1
            await self.db.commit()


# ============================================================================
# Temporal Graph Mapper - 时序图谱映射器
# ============================================================================


class TemporalGraphMapper:
    """
    时序图谱映射器 - 将黑板事件映射为时序知识图谱

    用途：
    1. 可视化 Agent 行为轨迹
    2. 检测抢先交易（Front-running）
    3. 发现协同作弊（Collusion）
    4. 安全审计和溯源
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def map_events_to_graph(
        self, session_id: str, neo4j_driver=None
    ) -> Dict[str, Any]:
        """
        将黑板事件映射为时序图谱

        图谱结构：
        - 节点：Agent (user_id)
        - 边：BID/OFFER/COUNTER (带时间戳和价格)
        """
        from app.db.models import BlackboardEvents

        # 读取事件流
        stmt = (
            select(BlackboardEvents)
            .where(BlackboardEvents.session_id == session_id)
            .order_by(BlackboardEvents.event_timestamp)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()

        if not events:
            return {"nodes": [], "edges": []}

        # 构建图谱
        nodes = {}
        edges = []

        for i, event in enumerate(events):
            # Agent 节点
            if event.agent_id not in nodes:
                nodes[event.agent_id] = {
                    "id": event.agent_id,
                    "role": event.agent_role,
                    "first_seen": event.event_timestamp.isoformat(),
                    "event_count": 0,
                }
            nodes[event.agent_id]["event_count"] += 1

            # 事件边
            edge = {
                "id": f"{session_id}_{i}",
                "source": event.agent_id,
                "target": "auction_state"
                if event.session_type == "auction"
                else "negotiation_state",
                "type": event.event_type,
                "timestamp": event.event_timestamp.isoformat(),
                "sequence": event.sequence_number,
                "payload": event.payload,
            }
            edges.append(edge)

        # 分析可疑行为
        anomalies = self._detect_anomalies(events)

        return {
            "session_id": session_id,
            "nodes": list(nodes.values()),
            "edges": edges,
            "anomalies": anomalies,
            "event_count": len(events),
            "time_span": {
                "start": events[0].event_timestamp.isoformat(),
                "end": events[-1].event_timestamp.isoformat(),
            },
        }

    def _detect_anomalies(self, events: List[BlackboardEvents]) -> List[Dict[str, Any]]:
        """检测异常行为"""
        anomalies = []

        # 1. 检测抢先交易（Front-running）
        # 模式：Agent B 在 Agent A 出价后极短时间内出更高价
        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]

            if prev.event_type == "BID" and curr.event_type == "BID":
                time_diff = (
                    curr.event_timestamp - prev.event_timestamp
                ).total_seconds()

                if time_diff < 0.1:  # 100ms 内
                    anomalies.append(
                        {
                            "type": "front_running_suspected",
                            "description": f"Agent {curr.agent_id} bid within {time_diff}s after Agent {prev.agent_id}",
                            "timestamp": curr.event_timestamp.isoformat(),
                            "agents": [prev.agent_id, curr.agent_id],
                        }
                    )

        # 2. 检测频繁出价（可能是攻击）
        agent_counts = {}
        for event in events:
            agent_counts[event.agent_id] = agent_counts.get(event.agent_id, 0) + 1

        for agent_id, count in agent_counts.items():
            if count > 20:  # 单次拍卖超过20次出价
                anomalies.append(
                    {
                        "type": "excessive_bidding",
                        "description": f"Agent {agent_id} placed {count} bids",
                        "agent_id": agent_id,
                        "bid_count": count,
                    }
                )

        return anomalies
