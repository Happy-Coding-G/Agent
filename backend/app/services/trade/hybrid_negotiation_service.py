"""
Hybrid Negotiation Service - 混合事件溯源架构

根据场景自动选择最优实现：
- 双边协商 (1对1): 使用简化版，直接存储状态
- 拍卖场景 (1对N): 使用事件溯源，处理高并发

核心设计：
1. 统一接口层 - 用户无感知切换
2. 场景路由器 - 自动检测并路由
3. 双引擎实现 - 各取所长
4. 状态同步器 - 拍卖结束后同步到主表

使用方式:
    service = HybridNegotiationService(db)

    # 自动检测场景并路由
    result = await service.create_negotiation(
        mechanism_type="bilateral",  # → 简化版
        ...
    )

    result = await service.create_negotiation(
        mechanism_type="auction",    # → 事件溯源版
        ...
    )
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List, Union
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.errors import ServiceError
from app.db.models import (
    NegotiationSessions,
    BlackboardEvents,
    TradeListings,
)

logger = logging.getLogger(__name__)


class NegotiationMechanism(str, Enum):
    """协商机制类型"""
    BILATERAL = "bilateral"      # 双边协商（1对1）
    AUCTION = "auction"          # 拍卖（1对N）


class ConcurrencyLevel(str, Enum):
    """并发级别"""
    LOW = "low"          # 低并发：双边协商
    MEDIUM = "medium"    # 中并发：少量竞拍者
    HIGH = "high"        # 高并发：公开拍卖


@dataclass
class ScenarioProfile:
    """场景画像"""
    mechanism_type: NegotiationMechanism
    participant_count: int
    expected_concurrency: ConcurrencyLevel
    requires_full_audit: bool
    recommended_engine: str  # "simple" | "event_sourced"


class ScenarioRouter:
    """
    场景路由器

    根据协商参数自动选择最优引擎。
    """

    # 并发阈值配置
    CONCURRENCY_THRESHOLDS = {
        "low": 2,      # 2个参与者 = 双边
        "medium": 10,  # 3-10个参与者 = 中并发
        "high": 100,   # >10个参与者 = 高并发
    }

    @classmethod
    def analyze_scenario(
        cls,
        mechanism_type: str,
        expected_participants: int = 2,
        requires_audit: bool = False,
    ) -> ScenarioProfile:
        """
        分析场景并推荐引擎

        决策逻辑：
        1. 双边协商 (mechanism=bilateral) → 简化版
        2. 拍卖且参与者 <= 2 → 简化版（小范围拍卖）
        3. 拍卖且参与者 > 2 → 事件溯源版
        4. 默认使用简化版
        """
        mechanism = NegotiationMechanism(mechanism_type)

        # 双边协商一律使用简化版
        if mechanism == NegotiationMechanism.BILATERAL:
            return ScenarioProfile(
                mechanism_type=mechanism,
                participant_count=expected_participants,
                expected_concurrency=ConcurrencyLevel.LOW,
                requires_full_audit=requires_audit,
                recommended_engine="simple",
            )

        # 拍卖场景根据参与者数量判断
        if mechanism == NegotiationMechanism.AUCTION:
            if expected_participants <= 2:
                # 小范围拍卖（如双方议价式拍卖）
                return ScenarioProfile(
                    mechanism_type=mechanism,
                    participant_count=expected_participants,
                    expected_concurrency=ConcurrencyLevel.LOW,
                    requires_full_audit=requires_audit,
                    recommended_engine="simple",
                )
            elif expected_participants <= 10:
                return ScenarioProfile(
                    mechanism_type=mechanism,
                    participant_count=expected_participants,
                    expected_concurrency=ConcurrencyLevel.MEDIUM,
                    requires_full_audit=True,
                    recommended_engine="event_sourced",
                )
            else:
                return ScenarioProfile(
                    mechanism_type=mechanism,
                    participant_count=expected_participants,
                    expected_concurrency=ConcurrencyLevel.HIGH,
                    requires_full_audit=True,
                    recommended_engine="event_sourced",
                )

        # 默认使用简化版
        return ScenarioProfile(
            mechanism_type=mechanism,
            participant_count=expected_participants,
            expected_concurrency=ConcurrencyLevel.LOW,
            requires_full_audit=requires_audit,
            recommended_engine="simple",
        )


class BilateralEngine:
    """
    双边协商引擎（简化版）

    适用于：
    - 1对1协商
    - 低并发
    - 需要快速查询
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        session_id: str,
        seller_id: int,
        buyer_id: int,
        listing_id: str,
        initial_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建协商会话"""
        from app.services.trade.simple_negotiation_service import SimpleNegotiationService

        service = SimpleNegotiationService(self.db)
        result = await service.create_negotiation(
            buyer_id=buyer_id,
            listing_id=listing_id,
            requirements=initial_data,
        )

        return {
            "engine": "bilateral",
            "session_id": result.get("negotiation_id"),
            "result": result,
        }

    async def submit_offer(
        self,
        session_id: str,
        user_id: int,
        price: float,
        message: str = "",
    ) -> Dict[str, Any]:
        """提交报价"""
        from app.services.trade.simple_negotiation_service import SimpleNegotiationService

        service = SimpleNegotiationService(self.db)
        return await service.make_offer(
            negotiation_id=session_id,
            user_id=user_id,
            price=price,
            message=message,
        )

    async def get_state(self, session_id: str) -> Dict[str, Any]:
        """获取当前状态（O(1)查询）"""
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise ServiceError(404, "Session not found")

        return {
            "engine": "bilateral",
            "session_id": session_id,
            "status": session.status,
            "current_round": session.current_round,
            "current_price": session.current_price,
            "shared_board": session.shared_board,
        }


class AuctionEngine:
    """
    拍卖引擎（事件溯源版）

    适用于：
    - 1对N拍卖
    - 高并发出价
    - 需要完整审计和顺序保证

    核心机制：
    1. 所有出价作为事件追加
    2. 使用乐观锁/CAS防止冲突
    3. 异步投影更新当前状态
    4. 拍卖结束后同步到主表
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        session_id: str,
        seller_id: int,
        listing_id: str,
        auction_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        创建拍卖会话

        初始化事件溯源结构：
        1. 创建 NegotiationSessions 记录（主表）
        2. 写入初始事件（AUCTION_CREATED）
        3. 设置投影状态
        """
        from app.services.trade.negotiation_event_store import NegotiationEventStore

        # 1. 创建主表记录
        session = NegotiationSessions(
            negotiation_id=session_id,
            listing_id=listing_id,
            seller_user_id=seller_id,
            buyer_user_id=None,  # 拍卖无固定买方
            status="active",
            mechanism_type="auction",
            current_round=0,
            starting_price=int(auction_config.get("starting_price", 0) * 100),
            reserve_price=int(auction_config.get("reserve_price", 0) * 100),
            shared_board={
                "mechanism": "auction",
                "auction_type": auction_config.get("auction_type", "english"),
                "starting_price": auction_config.get("starting_price"),
                "reserve_price": auction_config.get("reserve_price"),
                "current_highest_bid": None,
                "current_highest_bidder": None,
                "bid_history": [],  # 出价历史（摘要）
                "bid_count": 0,
            },
        )
        self.db.add(session)

        # 2. 写入初始事件
        event_store = NegotiationEventStore(self.db)
        await event_store.append_event(
            session_id=session_id,
            session_type="auction",
            event_type="AUCTION_CREATED",
            agent_id=seller_id,
            agent_role="seller",
            payload={
                "starting_price": auction_config.get("starting_price"),
                "reserve_price": auction_config.get("reserve_price"),
                "auction_type": auction_config.get("auction_type"),
                "duration_minutes": auction_config.get("duration_minutes", 60),
            },
        )

        await self.db.commit()

        return {
            "engine": "auction_event_sourced",
            "session_id": session_id,
            "status": "active",
            "message": "Auction created with event sourcing",
        }

    async def submit_bid(
        self,
        session_id: str,
        bidder_id: int,
        amount: float,
    ) -> Dict[str, Any]:
        """
        提交出价

        使用事件溯源保证顺序：
        1. 验证出价有效性
        2. 追加 BID_PLACED 事件
        3. 乐观锁更新投影状态
        4. 返回带序列号的结果
        """
        from app.services.trade.negotiation_event_store import NegotiationEventStore

        # 1. 获取当前状态（用于验证）
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session or session.status != "active":
            raise ServiceError(400, "Auction is not active")

        shared_board = dict(session.shared_board)

        # 2. 验证出价（必须高于当前最高价）
        current_highest = shared_board.get("current_highest_bid", 0) or 0
        if amount <= current_highest:
            raise ServiceError(
                400,
                f"Bid must be higher than current highest: {current_highest}"
            )

        # 3. 追加事件（带乐观锁）
        event_store = NegotiationEventStore(self.db)
        event = await event_store.append_event(
            session_id=session_id,
            session_type="auction",
            event_type="BID_PLACED",
            agent_id=bidder_id,
            agent_role="bidder",
            payload={
                "amount": amount,
                "previous_highest": current_highest,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # 4. 更新投影状态（乐观锁）
        session.version += 1  # 乐观锁版本号
        shared_board["current_highest_bid"] = amount
        shared_board["current_highest_bidder"] = bidder_id
        shared_board["bid_count"] = shared_board.get("bid_count", 0) + 1

        # 追加到出价历史（仅保留最近20条，完整记录在事件表）
        bid_history = shared_board.get("bid_history", [])
        bid_history.append({
            "bidder_id": bidder_id,
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        shared_board["bid_history"] = bid_history[-20:]  # 保留最近20条

        session.shared_board = shared_board
        session.current_price = int(amount * 100)

        await self.db.commit()

        return {
            "engine": "auction_event_sourced",
            "success": True,
            "bid_sequence": event.sequence_number,  # 事件序列号（顺序证明）
            "amount": amount,
            "is_highest": True,
            "message": f"Bid placed successfully. Sequence: {event.sequence_number}",
        }

    async def close_auction(
        self,
        session_id: str,
        seller_id: int,
    ) -> Dict[str, Any]:
        """
        关闭拍卖

        1. 写入 AUCTION_CLOSED 事件
        2. 确定胜出者
        3. 同步最终状态到主表
        4. 生成完整审计报告
        """
        from app.services.trade.negotiation_event_store import NegotiationEventStore

        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise ServiceError(404, "Auction not found")

        if session.seller_user_id != seller_id:
            raise ServiceError(403, "Only seller can close auction")

        shared_board = dict(session.shared_board)

        # 1. 写入关闭事件
        event_store = NegotiationEventStore(self.db)
        await event_store.append_event(
            session_id=session_id,
            session_type="auction",
            event_type="AUCTION_CLOSED",
            agent_id=seller_id,
            agent_role="seller",
            payload={
                "final_price": shared_board.get("current_highest_bid"),
                "winner_id": shared_board.get("current_highest_bidder"),
                "total_bids": shared_board.get("bid_count", 0),
                "closed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # 2. 更新状态
        session.status = "accepted"
        session.agreed_price = int(shared_board.get("current_highest_bid", 0) * 100)
        session.winner_user_id = shared_board.get("current_highest_bidder")
        session.settlement_at = datetime.now(timezone.utc)

        await self.db.commit()

        return {
            "engine": "auction_event_sourced",
            "success": True,
            "winner_id": session.winner_user_id,
            "final_price": shared_board.get("current_highest_bid"),
            "total_bids": shared_board.get("bid_count", 0),
            "message": "Auction closed successfully",
        }

    async def get_state(self, session_id: str) -> Dict[str, Any]:
        """
        获取拍卖状态

        对于拍卖场景，直接从投影表读取（足够实时）
        如需完整历史，查询事件表
        """
        result = await self.db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise ServiceError(404, "Auction not found")

        # 获取事件数量（用于显示完整性）
        from sqlalchemy import func
        from app.db.models import BlackboardEvents

        bid_count_result = await self.db.execute(
            select(func.count(BlackboardEvents.id)).where(
                and_(
                    BlackboardEvents.session_id == session_id,
                    BlackboardEvents.event_type == "BID_PLACED",
                )
            )
        )
        total_bids = bid_count_result.scalar() or 0

        return {
            "engine": "auction_event_sourced",
            "session_id": session_id,
            "status": session.status,
            "current_highest_bid": session.shared_board.get("current_highest_bid"),
            "current_highest_bidder": session.shared_board.get("current_highest_bidder"),
            "bid_count": total_bids,  # 从事件表统计，更准确
            "shared_board": session.shared_board,
        }

    async def get_full_audit_log(
        self,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """
        获取完整审计日志（从事件表重放）

        这是事件溯源的核心优势：完整的、不可篡改的历史记录。
        """
        from app.db.models import BlackboardEvents

        result = await self.db.execute(
            select(BlackboardEvents).where(
                BlackboardEvents.session_id == session_id
            ).order_by(BlackboardEvents.sequence_number)
        )
        events = result.scalars().all()

        return [
            {
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


class HybridNegotiationService:
    """
    混合协商服务（统一入口）

    根据场景自动路由到最合适的引擎。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.bilateral_engine = BilateralEngine(db)
        self.auction_engine = AuctionEngine(db)

    @staticmethod
    def analyze_scenario(
        mechanism_type: str,
        expected_participants: int = 2,
        requires_audit: bool = False,
    ) -> ScenarioProfile:
        """
        静态方法：分析场景并推荐引擎

        供 API 端点直接调用，无需实例化服务。
        """
        return ScenarioRouter.analyze_scenario(
            mechanism_type=mechanism_type,
            expected_participants=expected_participants,
            requires_audit=requires_audit,
        )

    def _get_engine(self, profile: ScenarioProfile) -> Union[BilateralEngine, AuctionEngine]:
        """根据场景获取引擎"""
        if profile.recommended_engine == "event_sourced":
            return self.auction_engine
        return self.bilateral_engine

    async def create_negotiation(
        self,
        mechanism_type: str,
        seller_id: int,
        buyer_id: Optional[int],
        listing_id: str,
        config: Dict[str, Any],
        expected_participants: int = 2,
    ) -> Dict[str, Any]:
        """
        创建协商/拍卖

        自动检测场景并路由。
        """
        # 分析场景
        profile = ScenarioRouter.analyze_scenario(
            mechanism_type=mechanism_type,
            expected_participants=expected_participants,
            requires_audit=config.get("requires_audit", False),
        )

        logger.info(
            f"Creating negotiation: mechanism={mechanism_type}, "
            f"participants={expected_participants}, "
            f"recommended_engine={profile.recommended_engine}"
        )

        # 路由到对应引擎
        if profile.recommended_engine == "event_sourced":
            # 拍卖场景
            return await self.auction_engine.create_session(
                session_id=config.get("session_id"),  # 可外部指定或内部生成
                seller_id=seller_id,
                listing_id=listing_id,
                auction_config=config,
            )
        else:
            # 双边协商场景
            if not buyer_id:
                raise ServiceError(400, "buyer_id is required for bilateral negotiation")

            return await self.bilateral_engine.create_session(
                session_id=config.get("session_id"),
                seller_id=seller_id,
                buyer_id=buyer_id,
                listing_id=listing_id,
                initial_data=config,
            )

    async def submit_offer(
        self,
        session_id: str,
        mechanism_type: str,
        user_id: int,
        price: float,
        message: str = "",
    ) -> Dict[str, Any]:
        """
        提交报价/出价

        根据场景自动路由。
        """
        # 查询当前机制类型（如果未提供）
        if not mechanism_type:
            result = await self.db.execute(
                select(NegotiationSessions.mechanism_type).where(
                    NegotiationSessions.negotiation_id == session_id
                )
            )
            mechanism_type = result.scalar() or "bilateral"

        profile = ScenarioRouter.analyze_scenario(mechanism_type)

        if profile.recommended_engine == "event_sourced":
            return await self.auction_engine.submit_bid(
                session_id=session_id,
                bidder_id=user_id,
                amount=price,
            )
        else:
            return await self.bilateral_engine.submit_offer(
                session_id=session_id,
                user_id=user_id,
                price=price,
                message=message,
            )

    async def get_state(
        self,
        session_id: str,
        include_audit_log: bool = False,
    ) -> Dict[str, Any]:
        """
        获取协商状态

        Args:
            include_audit_log: 是否包含完整审计日志（仅事件溯源场景）
        """
        # 先查询机制类型
        result = await self.db.execute(
            select(
                NegotiationSessions.mechanism_type,
                NegotiationSessions.shared_board,
            ).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        row = result.one_or_none()

        if not row:
            raise ServiceError(404, "Session not found")

        mechanism_type, shared_board = row
        profile = ScenarioRouter.analyze_scenario(mechanism_type)

        # 获取状态
        if profile.recommended_engine == "event_sourced":
            state = await self.auction_engine.get_state(session_id)

            # 可选：包含完整审计日志
            if include_audit_log:
                state["full_audit_log"] = await self.auction_engine.get_full_audit_log(session_id)

            return state
        else:
            return await self.bilateral_engine.get_state(session_id)

    async def close_auction(
        self,
        session_id: str,
        seller_id: int,
    ) -> Dict[str, Any]:
        """关闭拍卖（仅拍卖场景）"""
        return await self.auction_engine.close_auction(session_id, seller_id)


# ============================================================================
# 便捷函数
# ============================================================================

async def create_negotiation_with_smart_routing(
    db: AsyncSession,
    mechanism_type: str,
    seller_id: int,
    buyer_id: Optional[int],
    listing_id: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    便捷函数：智能路由创建协商

    自动选择最优架构。
    """
    service = HybridNegotiationService(db)
    return await service.create_negotiation(
        mechanism_type=mechanism_type,
        seller_id=seller_id,
        buyer_id=buyer_id,
        listing_id=listing_id,
        config=config,
        expected_participants=config.get("expected_participants", 2),
    )
