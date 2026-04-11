"""
Round-Based English Auction - 轮次英式拍卖

解决传统英式拍卖的"价格过时"问题：
- 每轮收集所有出价，取最高值统一更新
- 确保同轮出价基于相同版本
- 轮次间快速切换，保持实时性

使用场景：
- 需要快速响应但又要避免无效出价
- Agent可以在几秒内做出决策的数据资产拍卖
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.services.trade.negotiation_event_store import NegotiationEventStore
from app.services.trade.event_sourcing_blackboard import StateProjector

logger = logging.getLogger(__name__)


class RoundStatus(str, Enum):
    """轮次状态"""
    COLLECTING = "collecting"    # 收集中
    PROCESSING = "processing"    # 处理中
    SETTLED = "settled"          # 已结算


class AuctionStatus(str, Enum):
    """拍卖状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"
    CANCELLED = "cancelled"


@dataclass
class RoundResult:
    """轮次结果"""
    round_number: int
    bids: List[Dict[str, Any]]          # 本轮所有出价
    winning_bid: Optional[Dict]         # 获胜出价
    winning_price: float
    previous_price: float
    status: RoundStatus
    started_at: datetime
    ended_at: Optional[datetime] = None


@dataclass
class BidInRound:
    """轮次内的出价"""
    bid_id: str
    agent_id: int
    price: float
    based_on_version: int              # 基于哪个版本出价
    submitted_at: datetime
    strategy_hint: Optional[str] = None


class RoundBasedAuctionService:
    """
    轮次英式拍卖服务

    核心机制：
    1. 每轮固定时长（如5-10秒）收集出价
    2. 轮次结束取最高出价，统一更新状态
    3. 通知所有Agent本轮结果
    4. 立即开始下一轮，直到无更高出价或超时
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_store = NegotiationEventStore(db)
        self.state_projector = StateProjector(db)

        # 活跃拍卖管理
        self._active_auctions: Dict[str, Dict] = {}
        self._round_timers: Dict[str, asyncio.Task] = {}

    # ========================================================================
    # 拍卖创建与管理
    # ========================================================================

    async def create_auction(
        self,
        auction_id: str,
        seller_id: int,
        asset_id: str,
        starting_price: float,
        reserve_price: float,
        round_duration_seconds: int = 10,   # 每轮时长
        max_rounds: int = 20,                # 最大轮次
        min_increment: float = 10.0,         # 最小加价幅度
    ) -> Dict[str, Any]:
        """
        创建轮次拍卖

        Args:
            round_duration_seconds: 每轮收集出价的时长
            max_rounds: 防止无限轮次
            min_increment: 新出价必须比当前价高多少
        """
        auction_data = {
            "auction_id": auction_id,
            "seller_id": seller_id,
            "asset_id": asset_id,
            "starting_price": starting_price,
            "reserve_price": reserve_price,
            "current_price": starting_price,
            "current_winner": None,
            "round_duration": round_duration_seconds,
            "max_rounds": max_rounds,
            "min_increment": min_increment,
            "current_round": 0,
            "status": AuctionStatus.ACTIVE,
            "round_history": [],
            "current_bids": [],  # 当前轮次收集中
        }

        self._active_auctions[auction_id] = auction_data

        # 启动第一轮
        await self._start_round(auction_id)

        logger.info(
            f"Created round-based auction: {auction_id}, "
            f"round_duration={round_duration_seconds}s"
        )

        return {
            "auction_id": auction_id,
            "status": "active",
            "current_price": starting_price,
            "round": 0,
            "message": f"Auction started. Round duration: {round_duration_seconds}s",
        }

    # ========================================================================
    # 出价提交
    # ========================================================================

    async def submit_bid(
        self,
        auction_id: str,
        agent_id: int,
        price: float,
        strategy_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        提交出价到当前轮次

        与实时拍卖的区别：
        - 出价不会立即生效
        - 加入当前轮次的收集队列
        - 等待轮次结束后统一处理
        """
        auction = self._get_auction(auction_id)

        if auction["status"] != AuctionStatus.ACTIVE:
            raise ServiceError(400, "Auction is not active")

        # 检查是否已经在当前轮次出过价（可以更新）
        current_bids = auction["current_bids"]
        existing_bid = next(
            (b for b in current_bids if b["agent_id"] == agent_id),
            None
        )

        # 验证出价有效性
        current_price = auction["current_price"]
        min_increment = auction["min_increment"]

        if price < current_price + min_increment:
            raise ServiceError(
                400,
                f"Bid must be at least {current_price + min_increment} "
                f"(current {current_price} + increment {min_increment})"
            )

        bid_data = {
            "bid_id": f"{auction_id}_R{auction['current_round']}_{agent_id}",
            "agent_id": agent_id,
            "price": price,
            "based_on_version": auction["current_round"],
            "submitted_at": datetime.now(timezone.utc),
            "strategy_hint": strategy_hint,
        }

        if existing_bid:
            # 更新出价（如果更高）
            if price > existing_bid["price"]:
                existing_bid["price"] = price
                existing_bid["submitted_at"] = bid_data["submitted_at"]
                message = "Bid updated for current round"
            else:
                message = "New bid not higher than existing, keeping original"
        else:
            current_bids.append(bid_data)
            message = "Bid submitted for current round"

        return {
            "success": True,
            "auction_id": auction_id,
            "round": auction["current_round"],
            "your_bid": price,
            "current_price": current_price,
            "message": message,
            "note": "Bid will be processed when round ends",
        }

    # ========================================================================
    # 轮次管理（核心）
    # ========================================================================

    async def _start_round(self, auction_id: str):
        """开始新一轮"""
        auction = self._active_auctions[auction_id]

        auction["current_round"] += 1
        auction["current_bids"] = []
        auction["round_start_time"] = datetime.now(timezone.utc)

        round_num = auction["current_round"]
        duration = auction["round_duration"]

        logger.info(f"Auction {auction_id}: Round {round_num} started")

        # 设置轮次结束定时器
        timer = asyncio.create_task(
            self._round_timer(auction_id, round_num, duration)
        )
        self._round_timers[auction_id] = timer

    async def _round_timer(self, auction_id: str, round_num: int, duration: int):
        """轮次定时器"""
        await asyncio.sleep(duration)

        auction = self._active_auctions.get(auction_id)
        if not auction or auction["current_round"] != round_num:
            return  # 已经进行了下一轮

        await self._end_round(auction_id)

    async def _end_round(self, auction_id: str):
        """结束当前轮次，处理出价"""
        auction = self._active_auctions[auction_id]

        round_num = auction["current_round"]
        current_bids = auction["current_bids"]
        previous_price = auction["current_price"]

        logger.info(
            f"Auction {auction_id}: Round {round_num} ended, "
            f"bids received: {len(current_bids)}"
        )

        # 处理本轮出价
        if len(current_bids) == 0:
            # 本轮无人出价
            await self._handle_empty_round(auction_id)
            return

        # 找出本轮最高出价
        winning_bid = max(current_bids, key=lambda x: x["price"])
        winning_price = winning_bid["price"]

        # 验证是否高于当前价
        if winning_price <= previous_price:
            # 没有有效提升
            await self._handle_no_improvement(auction_id)
            return

        # 更新拍卖状态
        auction["current_price"] = winning_price
        auction["current_winner"] = winning_bid["agent_id"]

        # 记录轮次结果
        round_result = {
            "round": round_num,
            "winning_bid": winning_bid,
            "previous_price": previous_price,
            "new_price": winning_price,
            "total_bids": len(current_bids),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }
        auction["round_history"].append(round_result)

        # 写入事件溯源
        await self._record_round_result(auction_id, round_result)

        # 通知所有订阅者
        await self._notify_round_result(auction_id, round_result)

        # 检查是否达到最大轮次
        if round_num >= auction["max_rounds"]:
            await self._finalize_auction(auction_id, "max_rounds_reached")
            return

        # 检查是否满足结束条件（可配置）
        if await self._should_end_auction(auction_id):
            return

        # 开始下一轮
        await self._start_round(auction_id)

    async def _handle_empty_round(self, auction_id: str):
        """处理空轮次（无人出价）"""
        auction = self._active_auctions[auction_id]

        # 连续空轮次达到一定数量则结束
        empty_rounds = getattr(auction, "_empty_rounds", 0) + 1
        auction["_empty_rounds"] = empty_rounds

        if empty_rounds >= 2:  # 连续2轮无人出价
            await self._finalize_auction(auction_id, "no_bids")
        else:
            # 再给一轮机会
            await self._start_round(auction_id)

    async def _handle_no_improvement(self, auction_id: str):
        """处理无提升轮次"""
        auction = self._active_auctions[auction_id]

        # 连续无提升达到一定数量则结束
        no_improve_rounds = getattr(auction, "_no_improve_rounds", 0) + 1
        auction["_no_improve_rounds"] = no_improve_rounds

        if no_improve_rounds >= 2:
            await self._finalize_auction(auction_id, "no_improvement")
        else:
            await self._start_round(auction_id)

    async def _should_end_auction(self, auction_id: str) -> bool:
        """判断是否应该结束拍卖"""
        # 可以配置更多结束条件
        # 例如：达到目标价格、总时长超限等
        return False

    async def _finalize_auction(self, auction_id: str, reason: str):
        """结束拍卖"""
        auction = self._active_auctions[auction_id]
        auction["status"] = AuctionStatus.ENDED

        winner = auction["current_winner"]
        final_price = auction["current_price"]
        reserve_price = auction["reserve_price"]

        # 检查保留价
        if final_price < reserve_price:
            result = {
                "status": "failed",
                "reason": "below_reserve",
                "final_price": final_price,
                "reserve_price": reserve_price,
            }
        else:
            result = {
                "status": "success",
                "winner_id": winner,
                "final_price": final_price,
                "total_rounds": auction["current_round"],
            }

        await self._record_auction_end(auction_id, result)

        logger.info(
            f"Auction {auction_id} ended: {reason}, winner={winner}, price={final_price}"
        )

        # 清理定时器
        if auction_id in self._round_timers:
            self._round_timers[auction_id].cancel()
            del self._round_timers[auction_id]

    # ========================================================================
    # 事件记录
    # ========================================================================

    async def _record_round_result(self, auction_id: str, result: Dict):
        """记录轮次结果到事件溯源"""
        await self.event_store.append_event(
            session_id=auction_id,
            session_type="round_auction",
            event_type="ROUND_SETTLED",
            agent_id=result["winning_bid"]["agent_id"],
            agent_role="bidder",
            payload=result,
        )

    async def _record_auction_end(self, auction_id: str, result: Dict):
        """记录拍卖结束"""
        await self.event_store.append_event(
            session_id=auction_id,
            session_type="round_auction",
            event_type="AUCTION_END",
            agent_id=0,
            agent_role="system",
            payload=result,
        )

    # ========================================================================
    # 通知机制
    # ========================================================================

    async def _notify_round_result(self, auction_id: str, result: Dict):
        """通知所有Agent轮次结果"""
        # 可以通过WebSocket、SSE等推送
        auction = self._active_auctions[auction_id]

        notification = {
            "type": "round_result",
            "auction_id": auction_id,
            "round": result["round"],
            "new_price": result["new_price"],
            "winner_id": result["winning_bid"]["agent_id"],
            "total_bids": result["total_bids"],
            "next_round_starts": "immediately",
        }

        # 这里可以调用WebSocket广播
        logger.info(f"Notifying round result: {notification}")

    # ========================================================================
    # 查询接口
    # ========================================================================

    def _get_auction(self, auction_id: str) -> Dict:
        """获取拍卖数据"""
        auction = self._active_auctions.get(auction_id)
        if not auction:
            raise ServiceError(404, "Auction not found")
        return auction

    async def get_auction_state(self, auction_id: str) -> Dict[str, Any]:
        """获取拍卖当前状态"""
        auction = self._get_auction(auction_id)

        # 计算本轮剩余时间
        elapsed = (datetime.now(timezone.utc) - auction["round_start_time"]).total_seconds()
        remaining = max(0, auction["round_duration"] - elapsed)

        return {
            "auction_id": auction_id,
            "status": auction["status"],
            "current_round": auction["current_round"],
            "current_price": auction["current_price"],
            "current_winner": auction["current_winner"],
            "round_time_remaining": int(remaining),
            "current_bids_count": len(auction["current_bids"]),
            "round_history": auction["round_history"][-5:],  # 最近5轮
        }

    async def get_round_history(self, auction_id: str) -> List[Dict]:
        """获取完整轮次历史"""
        auction = self._get_auction(auction_id)
        return auction["round_history"]

    async def force_end_round(self, auction_id: str) -> Dict[str, Any]:
        """
        强制结束当前轮次（用于测试或紧急情况）
        """
        auction = self._get_auction(auction_id)

        # 取消当前定时器
        if auction_id in self._round_timers:
            self._round_timers[auction_id].cancel()

        await self._end_round(auction_id)

        return {
            "success": True,
            "message": f"Round {auction['current_round']} force ended",
        }

    async def end_auction(self, auction_id: str, seller_id: int) -> Dict[str, Any]:
        """
        卖方提前结束拍卖
        """
        auction = self._get_auction(auction_id)

        if auction["seller_id"] != seller_id:
            raise ServiceError(403, "Only seller can end auction")

        await self._finalize_auction(auction_id, "seller_ended")

        return {
            "success": True,
            "final_price": auction["current_price"],
            "winner": auction["current_winner"],
        }


# ============================================================================
# Agent 策略建议
# ============================================================================

class BiddingStrategy:
    """
    Agent出价策略建议

    在轮次拍卖中，Agent可以采用不同策略：
    """

    @staticmethod
    def aggressive(current_price: float, min_increment: float) -> float:
        """
        激进策略：大幅加价，震慑对手
        适合：非常想要该资产，希望快速结束
        """
        return current_price + max(min_increment * 3, current_price * 0.1)

    @staticmethod
    def conservative(current_price: float, min_increment: float, max_budget: float) -> float:
        """
        保守策略：最小加价，试探对手
        适合：预算有限，希望拖长拍卖观察对手
        """
        increment = min(min_increment * 1.5, max_budget - current_price)
        return current_price + max(increment, min_increment)

    @staticmethod
    def truthful(current_price: float, true_value: float, min_increment: float) -> float:
        """
        诚实策略：直接出真实估价
        适合：时间宝贵，不想拖长拍卖
        """
        if current_price + min_increment > true_value:
            return 0  # 放弃
        return true_value  # 直接出真实估价
