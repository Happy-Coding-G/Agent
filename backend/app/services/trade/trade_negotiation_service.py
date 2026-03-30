"""
Trade Negotiation Service - Blackboard Mode

Blackboard 模式核心设计：
1. 买卖双方 Agent 在各自底线价格的限制下进行价格协商
2. 整个协商流程作为完整上下文提供给双方 Agent
3. 协商历史完整记录在 shared_board 中
4. Agent 可以看到完整的协商历史和双方策略
5. 分层上下文管理 - 解决上下文窗口爆炸问题
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_
from sqlalchemy.orm import selectinload

from app.db.models import (
    NegotiationSessions,
    AgentMessageQueue,
    UserAgentConfig,
    NegotiationHistorySummary,
    Users,
    TradeListings,
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


# =============================================================================
# Context Management Constants
# =============================================================================

# 分层上下文配置
CONTEXT_LAYERS = {
    "recent_rounds": 5,      # 最近 N 轮完整保留
    "summary_interval": 5,   # 每 N 轮生成一次摘要
    "max_token_estimate": 4000,  # 最大 token 估算
}

# 每轮对话的平均 token 数估算
TOKENS_PER_ROUND = 150


class HierarchicalContextManager:
    """
    分层上下文管理器 - 解决上下文窗口爆炸问题

    设计原则：
    1. 短期记忆：最近几轮完整保留
    2. 中期记忆：摘要压缩的历史
    3. 长期记忆：关键事件和价格轨迹
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def should_summarize(self, negotiation_id: str) -> bool:
        """检查是否需要生成摘要。"""
        current_round = await self._get_current_round(negotiation_id)
        return current_round > 0 and current_round % CONTEXT_LAYERS["summary_interval"] == 0

    async def generate_summary(
        self,
        negotiation_id: str,
        history: List[Dict],
        layer: int = 1,
    ) -> Dict[str, Any]:
        """
        生成历史摘要。

        摘要包含：
        - 压缩后的对话要点
        - 价格轨迹
        - 关键事件
        - 情绪倾向
        """
        if len(history) <= CONTEXT_LAYERS["recent_rounds"]:
            return None

        round_start = history[0].get("round", 1)
        round_end = history[-1].get("round", len(history))

        # 提取价格轨迹
        prices = [h.get("price") for h in history if h.get("price")]
        price_trajectory = None
        if len(prices) >= 2:
            price_trajectory = {
                "start": prices[0],
                "end": prices[-1],
                "trend": "converging" if abs(prices[-1] - prices[0]) < 10 else "stable",
                "volatility": max(prices) - min(prices) if prices else 0,
            }

        # 提取关键事件
        key_events = []
        for h in history:
            event_type = h.get("event", h.get("by", "offer"))
            key_events.append(f"round_{h.get('round', '?')}:{event_type}")

        # 计算让步幅度
        concession_magnitude = None
        if len(prices) >= 2:
            first_price = history[0].get("price", 0)
            last_price = history[-1].get("price", 0)
            if first_price > 0:
                concession_magnitude = abs(last_price - first_price) / first_price

        # 生成摘要文本
        summary_text = self._generate_summary_text(history, price_trajectory)

        # 存储摘要
        summary_id = str(uuid.uuid4())[:32]
        summary_record = NegotiationHistorySummary(
            summary_id=summary_id,
            negotiation_id=negotiation_id,
            layer=layer,
            round_start=round_start,
            round_end=round_end,
            summary=summary_text,
            price_trajectory=price_trajectory or {},
            key_events=key_events,
            total_rounds=len(history),
            concession_magnitude=concession_magnitude,
        )

        self.db.add(summary_record)
        await self.db.commit()

        return {
            "summary_id": summary_id,
            "round_range": f"{round_start}-{round_end}",
            "layer": layer,
            "summary": summary_text,
        }

    def _generate_summary_text(
        self,
        history: List[Dict],
        price_trajectory: Optional[Dict],
    ) -> str:
        """生成摘要文本。"""
        if not history:
            return "No negotiation history."

        total_rounds = len(history)
        buyer_count = sum(1 for h in history if h.get("by") == "buyer")
        seller_count = sum(1 for h in history if h.get("by") == "seller")

        summary_parts = [
            f"协商共 {total_rounds} 轮，",
            f"买方出价 {buyer_count} 次，卖方出价 {seller_count} 次。",
        ]

        if price_trajectory:
            summary_parts.append(
                f"价格从 {price_trajectory['start']} 变化至 {price_trajectory['end']}，"
                f"趋势: {price_trajectory['trend']}。"
            )

        # 情绪摘要
        accept_count = sum(1 for h in history if h.get("event") == "ACCEPT")
        counter_count = sum(1 for h in history if h.get("event") in ["COUNTER", "REJECT_COUNTER"])

        if accept_count > 0:
            summary_parts.append(f"存在 {accept_count} 次接受尝试。")
        if counter_count > 2:
            summary_parts.append("双方存在较多拉锯。")

        return " ".join(summary_parts)

    async def get_context_for_rounds(
        self,
        negotiation_id: str,
        max_rounds: int = 5,
    ) -> List[Dict]:
        """
        获取最近 N 轮的完整上下文。

        这是为 Agent 提供的"短期记忆"。
        """
        session = await self._get_session(negotiation_id)
        if not session:
            return []

        history = session.shared_board.get("negotiation_history", [])
        return history[-max_rounds:] if len(history) > max_rounds else history

    async def get_summaries(
        self,
        negotiation_id: str,
    ) -> List[Dict[str, Any]]:
        """获取所有摘要。"""
        stmt = select(NegotiationHistorySummary).where(
            NegotiationHistorySummary.negotiation_id == negotiation_id
        ).order_by(NegotiationHistorySummary.layer, NegotiationHistorySummary.round_start)

        result = await self.db.execute(stmt)
        summaries = result.scalars().all()

        return [
            {
                "summary_id": s.summary_id,
                "round_range": f"{s.round_start}-{s.round_end}",
                "layer": s.layer,
                "summary": s.summary,
                "price_trajectory": s.price_trajectory,
            }
            for s in summaries
        ]

    async def build_hierarchical_context(
        self,
        negotiation_id: str,
        for_user_id: int,
    ) -> Dict[str, Any]:
        """
        构建分层上下文 - 核心方法。

        返回结构：
        {
            "type": "hierarchical",
            "layers": [
                {"type": "recent", "rounds": [...recent_rounds...]},
                {"type": "summary", "layer_1": {...}},
                {"type": "summary", "layer_2": {...}},
            ],
            "total_token_estimate": xxx,
        }
        """
        session = await self._get_session(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        is_seller = session.seller_user_id == for_user_id
        is_buyer = session.buyer_user_id == for_user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        layers = []
        total_tokens = 0

        # Layer 1: 最近 N 轮完整记录
        recent_rounds = await self.get_context_for_rounds(
            negotiation_id,
            max_rounds=CONTEXT_LAYERS["recent_rounds"],
        )
        if recent_rounds:
            layers.append({
                "type": "recent",
                "description": f"最近 {len(recent_rounds)} 轮完整记录",
                "rounds": recent_rounds,
                "token_estimate": len(recent_rounds) * TOKENS_PER_ROUND,
            })
            total_tokens += len(recent_rounds) * TOKENS_PER_ROUND

        # Layer 2+: 历史摘要
        summaries = await self.get_summaries(negotiation_id)
        for s in summaries:
            token_est = len(s["summary"]) // 4  # 估算
            layers.append({
                "type": "summary",
                "layer": s["layer"],
                "description": f"轮次 {s['round_range']} 摘要",
                "content": s["summary"],
                "price_trajectory": s["price_trajectory"],
                "token_estimate": token_est,
            })
            total_tokens += token_est

        return {
            "type": "hierarchical",
            "negotiation_id": negotiation_id,
            "layers": layers,
            "total_token_estimate": total_tokens,
            "within_limit": total_tokens <= CONTEXT_LAYERS["max_token_estimate"],
        }

    # ========================================================================
    # Private Helpers
    # ========================================================================

    async def _get_session(self, negotiation_id: str) -> Optional[NegotiationSessions]:
        stmt = select(NegotiationSessions).where(
            NegotiationSessions.negotiation_id == negotiation_id
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _get_current_round(self, negotiation_id: str) -> int:
        session = await self._get_session(negotiation_id)
        return session.current_round if session else 0


class BlackboardNegotiationService:
    """
    Blackboard 模式协商服务 - 完整的上下文感知协商系统。

    核心特点：
    1. 完整上下文共享 - 双方都能看到完整的协商历史
    2. 底线价格保护 - 卖方最低价、买方最高价由系统强制执行
    3. 策略透明度 - 双方知道对方的策略范围
    4. 智能建议 - 提供价格合理性分析
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================================
    # Session Management
    # ========================================================================

    async def create_blackboard_negotiation(
        self,
        seller_user_id: int,
        buyer_user_id: Optional[int],
        listing_id: Optional[str],
        asset_id: Optional[str],
        seller_floor_price: float,  # 卖方最低接受价格
        buyer_ceiling_price: Optional[float] = None,  # 买方最高接受价格
        starting_price: Optional[float] = None,  # 起始报价
        seller_target_price: Optional[float] = None,  # 卖方期望价格
        buyer_target_price: Optional[float] = None,  # 买方期望价格
        max_rounds: int = 20,
        expires_minutes: int = 1440,
    ) -> str:
        """
        创建黑板模式协商会话。

        Args:
            seller_floor_price: 卖方最低接受价格（必须）
            buyer_ceiling_price: 买方最高接受价格（可选，买方加入时设置）
            starting_price: 起始报价
            seller_target_price: 卖方期望价格（用于决策参考）
            buyer_target_price: 买方期望价格（用于决策参考）

        Returns:
            negotiation_id: 协商会话ID
        """
        negotiation_id = str(uuid.uuid4())[:32]
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        # 验证价格关系
        if starting_price and seller_floor_price > starting_price:
            raise ServiceError(400, "Floor price cannot exceed starting price")

        if buyer_ceiling_price and seller_floor_price > buyer_ceiling_price:
            raise ServiceError(400, "No overlap between floor and ceiling prices")

        session = NegotiationSessions(
            negotiation_id=negotiation_id,
            seller_user_id=seller_user_id,
            buyer_user_id=buyer_user_id,
            listing_id=listing_id,
            asset_id=asset_id,
            mechanism_type="blackboard",
            max_rounds=max_rounds,
            status="pending",
            current_round=0,
            current_turn="seller",
            starting_price=int(starting_price * 100) if starting_price else int(seller_floor_price * 100),
            reserve_price=int(seller_floor_price * 100),
            seller_floor_price=int(seller_floor_price * 100),
            buyer_ceiling_price=int(buyer_ceiling_price * 100) if buyer_ceiling_price else None,
            seller_target_price=int(seller_target_price * 100) if seller_target_price else None,
            buyer_target_price=int(buyer_target_price * 100) if buyer_target_price else None,
            shared_board={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "negotiation_history": [],  # 完整协商历史
                "price_evolution": [],  # 价格演变
                "seller_strategy": {
                    "floor_price": seller_floor_price,
                    "target_price": seller_target_price,
                    "concessions": [],
                },
                "buyer_strategy": {
                    "ceiling_price": buyer_ceiling_price,
                    "target_price": buyer_target_price,
                    "concessions": [],
                },
                "public_notes": [],  # 公开备注
                "analysis": {},  # 系统分析
            },
            expires_at=expires_at,
        )

        self.db.add(session)
        await self.db.commit()

        logger.info(f"Created blackboard negotiation {negotiation_id}")
        logger.info(f"  Floor price: {seller_floor_price}, Ceiling: {buyer_ceiling_price}")

        return negotiation_id

    async def get_negotiation(
        self,
        negotiation_id: str,
        lock: bool = False
    ) -> Optional[NegotiationSessions]:
        """获取协商会话，可选行级锁"""
        stmt = (
            select(NegotiationSessions)
            .where(NegotiationSessions.negotiation_id == negotiation_id)
            .options(selectinload(NegotiationSessions.messages))
        )

        if lock:
            stmt = stmt.with_for_update()

        result = await self.db.execute(stmt)
        return result.scalars().first()

    # ========================================================================
    # Blackboard Context - 分层上下文获取
    # ========================================================================

    async def get_full_blackboard_context(
        self,
        negotiation_id: str,
        for_user_id: int,
        use_hierarchical: bool = True,
    ) -> Dict[str, Any]:
        """
        获取完整的黑板上下文 - 供 Agent LLM 决策使用。

        采用分层上下文管理解决上下文窗口爆炸问题：
        1. 短期记忆：最近 5 轮完整保留
        2. 摘要记忆：早期历史压缩为摘要
        3. 结构化状态：价格约束、趋势分析等

        Args:
            negotiation_id: 协商 ID
            for_user_id: 请求上下文的目标用户 ID
            use_hierarchical: 是否使用分层上下文（默认 True）

        Returns:
            包含分层上下文信息的完整上下文
        """
        session = await self.get_negotiation(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        # 确定用户角色
        is_seller = session.seller_user_id == for_user_id
        is_buyer = session.buyer_user_id == for_user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized to view this negotiation")

        # 获取原始历史
        raw_history = session.shared_board.get("negotiation_history", [])

        # 构造上下文（无论是否分层，都包含核心结构化信息）
        context = {
            "negotiation_id": negotiation_id,
            "status": session.status,
            "current_round": session.current_round,
            "max_rounds": session.max_rounds,
            "current_turn": session.current_turn,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,

            # ===== 价格约束（结构化，无关历史长度）=====
            # 当前位置信息
            "current_price": session.current_price / 100 if session.current_price else None,
            "starting_price": session.starting_price / 100 if session.starting_price else None,
            "agreed_price": session.agreed_price / 100 if session.agreed_price else None,

            # 底线价格（各自的底线）
            "my_floor_price": session.seller_floor_price / 100 if is_seller else None,
            "my_ceiling_price": session.buyer_ceiling_price / 100 if is_buyer else None,

            # 对方的价格范围（可见但不能突破）
            "opponent_floor_price": session.seller_floor_price / 100 if is_buyer else None,
            "opponent_ceiling_price": session.buyer_ceiling_price / 100 if is_seller else None,

            # 目标价格
            "my_target_price": session.seller_target_price / 100 if is_seller else session.buyer_target_price / 100,
            "opponent_target_price": session.buyer_target_price / 100 if is_seller else session.seller_target_price / 100,

            # ===== 合理性分析（结构化）=====
            "analysis": self._analyze_current_state(session, is_seller),

            # ===== 策略信息（结构化）=====
            "my_strategy": session.shared_board.get("seller_strategy" if is_seller else "buyer_strategy", {}),

            # ===== 剩余时间 ======
            "remaining_time": (session.expires_at - datetime.now(timezone.utc)).total_seconds() / 60 if session.expires_at else None,

            # ===== 历史上下文（分层处理）=====
            "context_type": "hierarchical" if use_hierarchical else "flat",
        }

        if use_hierarchical:
            # 分层上下文：只包含必要的结构化信息
            # 历史通过分层管理器获取
            context.update({
                "history_summary": self._summarize_history(raw_history),
                "total_rounds": len(raw_history),
                "price_trend": self._calculate_price_trend(raw_history),
            })
        else:
            # 扁平上下文：完整历史（可能溢出）
            context["negotiation_history"] = raw_history

        return context

    def _summarize_history(self, history: List[Dict]) -> Dict[str, Any]:
        """
        生成历史摘要 - 不使用 LLM 的快速摘要。

        用于：
        1. 快速概览历史
        2. 在分层上下文不够时提供补充
        """
        if not history:
            return {"total_rounds": 0, "summary": "暂无协商历史"}

        # 统计
        buyer_rounds = [h for h in history if h.get("by") == "buyer"]
        seller_rounds = [h for h in history if h.get("by") == "seller"]

        # 价格范围
        prices = [h.get("price") for h in history if h.get("price")]
        price_range = {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
        }

        # 方向趋势
        directions = [h.get("direction") for h in history if h.get("direction")]
        trend = "converging" if directions else "unknown"

        return {
            "total_rounds": len(history),
            "buyer_offers": len(buyer_rounds),
            "seller_offers": len(seller_rounds),
            "price_range": price_range,
            "trend": trend,
            "last_offer": history[-1] if history else None,
            "quick_summary": f"共{len(history)}轮，"
                            f"买方出{len(buyer_rounds)}次，卖方出{len(seller_rounds)}次，"
                            f"价格区间[{price_range['min']}-{price_range['max']}]，"
                            f"趋势{trend}",
        }

    def _calculate_price_trend(self, history: List[Dict]) -> Optional[Dict]:
        """计算价格趋势。"""
        if len(history) < 2:
            return None

        prices = [h.get("price") for h in history if h.get("price")]
        if len(prices) < 2:
            return None

        return {
            "start": prices[0],
            "end": prices[-1],
            "delta": prices[-1] - prices[0],
            "delta_percent": (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else 0,
            "volatility": max(prices) - min(prices),
            "volatility_percent": (max(prices) - min(prices)) / min(prices) * 100 if min(prices) else 0,
        }

    async def get_hierarchical_context(
        self,
        negotiation_id: str,
        for_user_id: int,
    ) -> Dict[str, Any]:
        """
        获取分层上下文 - 完整的分层结构。

        适用于需要完整历史但要控制 token 消耗的场景。
        """
        from .trade_negotiation_service import HierarchicalContextManager

        manager = HierarchicalContextManager(self.db)

        # 构建分层上下文
        return await manager.build_hierarchical_context(
            negotiation_id=negotiation_id,
            for_user_id=for_user_id,
        )

    async def _maybe_generate_summary(self, negotiation_id: str):
        """
        检查并生成历史摘要。

        当历史记录达到一定轮次后，自动生成摘要以控制上下文大小。
        """
        manager = HierarchicalContextManager(self.db)

        # 检查是否需要生成摘要
        should_summarize = await manager.should_summarize(negotiation_id)
        if not should_summarize:
            return

        # 获取会话
        session = await manager._get_session(negotiation_id)
        if not session:
            return

        # 获取当前历史
        history = session.shared_board.get("negotiation_history", [])
        if len(history) <= CONTEXT_LAYERS["recent_rounds"]:
            return

        # 计算当前层
        current_layer = len(history) // CONTEXT_LAYERS["summary_interval"]

        # 检查是否已有该层摘要
        existing_summaries = await manager.get_summaries(negotiation_id)
        layer_exists = any(s["layer"] == current_layer for s in existing_summaries)

        if not layer_exists:
            # 生成新摘要
            await manager.generate_summary(
                negotiation_id=negotiation_id,
                history=history,
                layer=current_layer,
            )
            logger.info(f"Generated summary for negotiation {negotiation_id}, layer {current_layer}")

    def _calculate_price_evolution(self, session: NegotiationSessions) -> List[Dict]:
        """计算价格演变趋势。"""
        history = session.shared_board.get("negotiation_history", [])
        evolution = []

        for entry in history:
            if "price" in entry:
                evolution.append({
                    "round": entry.get("round", 0),
                    "price": entry["price"],
                    "direction": entry.get("direction"),  # "up", "down", "init"
                    "by": entry.get("by"),  # "seller" or "buyer"
                })

        return evolution

    def _analyze_current_state(
        self,
        session: NegotiationSessions,
        is_seller: bool,
    ) -> Dict[str, Any]:
        """分析当前状态。"""
        analysis = {
            "deal_possible": True,
            "overlap_range": None,
            "recommendation": None,
            "risk_level": "low",
        }

        if not session.seller_floor_price or not session.buyer_ceiling_price:
            analysis["deal_possible"] = True
            analysis["recommendation"] = "Waiting for buyer to set ceiling price"
            return analysis

        floor = session.seller_floor_price / 100
        ceiling = session.buyer_ceiling_price / 100
        current = (session.current_price or session.starting_price) / 100 if session.starting_price else floor

        # 计算重叠区间
        if floor <= ceiling:
            analysis["overlap_range"] = {
                "min": floor,
                "max": ceiling,
                "midpoint": (floor + ceiling) / 2,
            }
            analysis["deal_possible"] = True

            # 给出建议
            if is_seller:
                if current < floor:
                    analysis["recommendation"] = "Price is below your floor. Consider accepting or exiting."
                    analysis["risk_level"] = "high"
                elif current < analysis["overlap_range"]["midpoint"]:
                    analysis["recommendation"] = "Current price is reasonable. You may consider a slight counter."
                    analysis["risk_level"] = "medium"
                else:
                    analysis["recommendation"] = "Price is favorable. Consider accepting soon."
                    analysis["risk_level"] = "low"
            else:
                if current > ceiling:
                    analysis["recommendation"] = "Price exceeds your ceiling. Consider lowering or exiting."
                    analysis["risk_level"] = "high"
                elif current > analysis["overlap_range"]["midpoint"]:
                    analysis["recommendation"] = "Current price is reasonable. You may consider a lower counter."
                    analysis["risk_level"] = "medium"
                else:
                    analysis["recommendation"] = "Price is favorable. Consider accepting soon."
                    analysis["risk_level"] = "low"
        else:
            analysis["deal_possible"] = False
            analysis["recommendation"] = "No overlap between floor and ceiling. Negotiation may fail."
            analysis["risk_level"] = "critical"

        return analysis

    # ========================================================================
    # Negotiation Actions
    # ========================================================================

    async def submit_offer(
        self,
        negotiation_id: str,
        from_user_id: int,
        price: float,
        message: str = "",
        reasoning: str = "",  # 出价理由
    ) -> Dict[str, Any]:
        """
        提交出价（双方通用）。

        流程：
        1. 验证出价有效性
        2. 验证底线价格约束
        3. 记录到历史
        4. 检查是否达成一致
        """
        session = await self.get_negotiation(negotiation_id, lock=True)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        # 确定角色
        is_seller = session.seller_user_id == from_user_id
        is_buyer = session.buyer_user_id == from_user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        # 检查状态
        if session.status not in ["pending", "active"]:
            raise ServiceError(400, f"Cannot submit offer in status: {session.status}")

        # 检查轮次（在锁内检查，防止竞态）
        if session.current_round >= session.max_rounds:
            session.status = "terminated"
            await self.db.commit()
            raise ServiceError(400, "Maximum rounds reached")

        # 验证底线价格
        price_cents = int(price * 100)

        if is_seller:
            # 卖方不能低于自己的底线
            if price_cents < session.seller_floor_price:
                raise ServiceError(
                    400,
                    f"Offer {price} is below your floor price {session.seller_floor_price / 100}"
                )
        else:
            # 买方不能高于自己的底线
            if session.buyer_ceiling_price and price_cents > session.buyer_ceiling_price:
                raise ServiceError(
                    400,
                    f"Offer {price} exceeds your ceiling price {session.buyer_ceiling_price / 100}"
                )

        # 更新状态
        session.current_round += 1
        session.current_price = price_cents
        session.last_activity_at = datetime.now(timezone.utc)

        # 递增 version 字段
        session.version = (session.version or 0) + 1

        # 记录到黑板历史
        direction = None
        if session.current_round > 1:
            prev_price = session.shared_board["negotiation_history"][-1]["price"] if session.shared_board["negotiation_history"] else None
            if prev_price:
                if is_seller:
                    direction = "down" if price < prev_price else "up"
                else:
                    direction = "up" if price > prev_price else "down"

        history_entry = {
            "round": session.current_round,
            "by": "seller" if is_seller else "buyer",
            "price": price,
            "message": message,
            "reasoning": reasoning,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
        }
        session.shared_board["negotiation_history"].append(history_entry)

        # 更新价格演变
        session.shared_board["price_evolution"].append({
            "round": session.current_round,
            "price": price,
            "direction": direction,
        })

        # 更新当前轮次
        session.current_turn = "buyer" if is_seller else "seller"

        # 激活会话
        if session.status == "pending":
            session.status = "active"

        # 检查是否达成一致
        if self._check_agreement(session):
            session.status = "agreed"
            session.agreed_price = price_cents

        await self.db.commit()

        # 检查是否需要生成摘要（分层上下文管理）
        await self._maybe_generate_summary(negotiation_id)

        # 通知对方
        recipient_id = session.buyer_user_id if is_seller else session.seller_user_id
        if recipient_id:
            await self._send_notification(
                negotiation_id=negotiation_id,
                to_user_id=recipient_id,
                event_type="OFFER",
                payload={
                    "price": price,
                    "message": message,
                    "reasoning": reasoning,
                    "round": session.current_round,
                },
            )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "offer_price": price,
            "round": session.current_round,
            "status": session.status,
            "agreed": session.status == "agreed",
        }

    def _check_agreement(self, session: NegotiationSessions) -> bool:
        """检查是否达成一致。"""
        if not session.current_price:
            return False

        # 简单的价格一致性检查
        # 实际上黑板模式需要双方明确确认
        return False

    async def accept_offer(
        self,
        negotiation_id: str,
        user_id: int,
        final_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        接受当前出价。

        卖方可以接受买方的出价，买方也可以接受卖方的报价。
        """
        session = await self.get_negotiation(negotiation_id, lock=True)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        is_seller = session.seller_user_id == user_id
        is_buyer = session.buyer_user_id == user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        if not session.current_price:
            raise ServiceError(400, "No current offer to accept")

        # 在锁内检查防止双重接受
        if session.status == "agreed":
            raise ServiceError(400, "Offer already accepted")

        price = final_price or (session.current_price / 100)
        price_cents = int(price * 100)

        # 验证底线
        if is_seller:
            if price_cents < session.seller_floor_price:
                raise ServiceError(400, "Cannot accept price below floor")
        else:
            if session.buyer_ceiling_price and price_cents > session.buyer_ceiling_price:
                raise ServiceError(400, "Cannot accept price above ceiling")

        # 递增 version
        session.version = (session.version or 0) + 1

        # 达成协议
        session.status = "agreed"
        session.agreed_price = price_cents
        session.last_activity_at = datetime.now(timezone.utc)

        # 记录到历史
        session.shared_board["negotiation_history"].append({
            "round": session.current_round,
            "by": "seller" if is_seller else "buyer",
            "event": "ACCEPT",
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self.db.commit()

        # 通知对方
        recipient_id = session.buyer_user_id if is_seller else session.seller_user_id
        if recipient_id:
            await self._send_notification(
                negotiation_id=negotiation_id,
                to_user_id=recipient_id,
                event_type="ACCEPT",
                payload={
                    "agreed_price": price,
                },
            )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "agreed_price": price,
            "status": "agreed",
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
        拒绝当前并反报价。

        在黑板模式下，双方都可以主动反报价。
        """
        session = await self.get_negotiation(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        is_seller = session.seller_user_id == user_id
        is_buyer = session.buyer_user_id == user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        # 验证反报价底线
        price_cents = int(counter_price * 100)

        if is_seller:
            if price_cents < session.seller_floor_price:
                raise ServiceError(400, "Counter below floor")
        else:
            if session.buyer_ceiling_price and price_cents > session.buyer_ceiling_price:
                raise ServiceError(400, "Counter above ceiling")

        # 记录反报价
        session.shared_board["negotiation_history"].append({
            "round": session.current_round,
            "by": "seller" if is_seller else "buyer",
            "event": "REJECT_COUNTER",
            "counter_price": counter_price,
            "message": message,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 更新当前价格
        session.current_price = price_cents
        session.current_round += 1
        session.last_activity_at = datetime.now(timezone.utc)
        session.current_turn = "buyer" if is_seller else "seller"

        await self.db.commit()

        # 通知对方
        recipient_id = session.buyer_user_id if is_seller else session.seller_user_id
        if recipient_id:
            await self._send_notification(
                negotiation_id=negotiation_id,
                to_user_id=recipient_id,
                event_type="COUNTER",
                payload={
                    "counter_price": counter_price,
                    "message": message,
                    "reason": reason,
                    "round": session.current_round,
                },
            )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "counter_price": counter_price,
            "round": session.current_round,
            "status": session.status,
        }

    async def withdraw_from_negotiation(
        self,
        negotiation_id: str,
        user_id: int,
        reason: str = "",
    ) -> Dict[str, Any]:
        """退出协商。"""
        session = await self.get_negotiation(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        is_seller = session.seller_user_id == user_id
        is_buyer = session.buyer_user_id == user_id

        if not is_seller and not is_buyer:
            raise ServiceError(403, "Not authorized")

        session.status = "cancelled"
        session.last_activity_at = datetime.now(timezone.utc)

        # 记录退出原因
        session.shared_board["negotiation_history"].append({
            "by": "seller" if is_seller else "buyer",
            "event": "WITHDRAW",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await self.db.commit()

        # 通知对方
        recipient_id = session.buyer_user_id if is_seller else session.seller_user_id
        if recipient_id:
            await self._send_notification(
                negotiation_id=negotiation_id,
                to_user_id=recipient_id,
                event_type="WITHDRAW",
                payload={"reason": reason},
            )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "status": "cancelled",
        }

    # ========================================================================
    # Buyer Ceiling Setting (买方设置最高价)
    # ========================================================================

    async def set_buyer_ceiling(
        self,
        negotiation_id: str,
        buyer_user_id: int,
        ceiling_price: float,
        target_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        买方设置自己的最高接受价格。

        这是黑板模式的关键：买方在加入协商时设置自己的天花板价格。
        """
        session = await self.get_negotiation(negotiation_id, lock=True)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        if session.buyer_user_id != buyer_user_id:
            raise ServiceError(403, "Not authorized as buyer")

        # 在锁内检查防止重复设置
        if session.buyer_ceiling_price:
            raise ServiceError(400, "Ceiling already set")

        ceiling_cents = int(ceiling_price * 100)

        # 检查与卖方底线的重叠
        if session.seller_floor_price and ceiling_cents < session.seller_floor_price:
            raise ServiceError(
                400,
                f"Ceiling {ceiling_price} is below seller's floor {session.seller_floor_price / 100}"
            )

        session.buyer_ceiling_price = ceiling_cents
        session.buyer_target_price = int(target_price * 100) if target_price else None

        # 递增 version
        session.version = (session.version or 0) + 1

        # 更新黑板
        session.shared_board["buyer_strategy"] = {
            "ceiling_price": ceiling_price,
            "target_price": target_price,
            "concessions": [],
        }

        # 激活协商
        if session.status == "pending":
            session.status = "active"

        # 单一提交点
        await self.db.commit()

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "ceiling_price": ceiling_price,
            "deal_possible": session.seller_floor_price <= ceiling_cents,
        }

    # ========================================================================
    # Settlement
    # ========================================================================

    async def finalize_settlement(
        self,
        negotiation_id: str,
        seller_id: int,
    ) -> Dict[str, Any]:
        """完成结算。"""
        session = await self.get_negotiation(negotiation_id)
        if not session:
            raise ServiceError(404, "Negotiation not found")

        if session.seller_user_id != seller_id:
            raise ServiceError(403, "Not authorized as seller")

        if session.status != "agreed":
            raise ServiceError(400, f"Cannot settle in status: {session.status}")

        if not session.agreed_price:
            raise ServiceError(400, "No agreed price")

        final_price = session.agreed_price / 100
        platform_fee = final_price * 0.05
        seller_income = final_price * 0.95

        session.status = "settled"
        session.settlement_result = {
            "final_price": final_price,
            "platform_fee": platform_fee,
            "seller_income": seller_income,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        }
        session.settlement_at = datetime.now(timezone.utc)

        await self.db.commit()

        # 通知买方
        if session.buyer_user_id:
            await self._send_notification(
                negotiation_id=negotiation_id,
                to_user_id=session.buyer_user_id,
                event_type="SETTLE",
                payload=session.settlement_result,
            )

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "settlement": session.settlement_result,
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    async def list_negotiations(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """列出用户的协商会话。"""
        from sqlalchemy import select

        stmt = select(NegotiationSessions).where(
            or_(
                NegotiationSessions.seller_user_id == user_id,
                NegotiationSessions.buyer_user_id == user_id,
            )
        )

        if status:
            stmt = stmt.where(NegotiationSessions.status == status)

        stmt = stmt.order_by(NegotiationSessions.updated_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        return [
            {
                "negotiation_id": s.negotiation_id,
                "status": s.status,
                "current_round": s.current_round,
                "current_price": s.current_price / 100 if s.current_price else None,
                "mechanism": s.mechanism_type,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]

    async def _send_notification(
        self,
        negotiation_id: str,
        to_user_id: int,
        event_type: str,
        payload: Dict[str, Any],
    ):
        """发送通知。"""
        # 记录到消息队列
        message_id = str(uuid.uuid4())[:32]

        message = AgentMessageQueue(
            message_id=message_id,
            negotiation_id=negotiation_id,
            from_agent_user_id=0,  # System
            to_agent_user_id=to_user_id,
            msg_type=event_type,
            payload=payload,
            status="pending",
        )

        self.db.add(message)
        await self.db.commit()

        logger.info(f"Notification {event_type} sent to user {to_user_id}")

    async def mark_message_processed(
        self,
        message_id: str,
        worker_id: str,
        error: Optional[str] = None,
    ) -> None:
        """标记消息为已处理"""
        from sqlalchemy import update

        updates = {
            "status": "failed" if error else "processed",
            "processed_at": datetime.now(timezone.utc),
            "processed_by": worker_id,
        }
        if error:
            updates["error"] = error[:500]

        stmt = (
            update(AgentMessageQueue)
            .where(AgentMessageQueue.message_id == message_id)
            .values(**updates)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_or_create_agent_config(
        self,
        user_id: int,
        agent_role: str,
    ) -> UserAgentConfig:
        """获取或创建用户Agent配置"""
        from sqlalchemy.dialects.postgresql import insert

        stmt = select(UserAgentConfig).where(
            UserAgentConfig.user_id == user_id,
            UserAgentConfig.agent_role == agent_role,
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            return config

        stmt = (
            insert(UserAgentConfig)
            .values(
                user_id=user_id,
                agent_role=agent_role,
                pricing_strategy="negotiable",
                negotiation_style="balanced",
            )
            .on_conflict_do_nothing(
                constraint="uk_user_agent_role"
            )
            .returning(UserAgentConfig)
        )

        result = await self.db.execute(stmt)
        created = result.scalar_one_or_none()

        if created:
            await self.db.commit()
            return created

        await self.db.rollback()
        result = await self.db.execute(
            select(UserAgentConfig).where(
                UserAgentConfig.user_id == user_id,
                UserAgentConfig.agent_role == agent_role,
            )
        )
        return result.scalar_one()


# =============================================================================
# Backward Compatibility - 保留原有接口
# =============================================================================

class NegotiationService(BlackboardNegotiationService):
    """
    兼容层 - 原有接口保持向后兼容。

    内部委托给 BlackboardNegotiationService 实现。
    """

    async def create_negotiation(
        self,
        seller_user_id: int,
        buyer_user_id: Optional[int],
        listing_id: Optional[str],
        asset_id: Optional[str],
        mechanism_type: str,
        starting_price: Optional[float] = None,
        reserve_price: Optional[float] = None,
        max_rounds: int = 10,
        expires_minutes: int = 1440,
    ) -> str:
        """
        创建协商会话（兼容原有接口）。

        如果是 blackboard 模式，使用新的黑板逻辑。
        """
        if mechanism_type == "blackboard":
            if not reserve_price:
                raise ServiceError(400, "Blackboard mode requires reserve_price")
            return await self.create_blackboard_negotiation(
                seller_user_id=seller_user_id,
                buyer_user_id=buyer_user_id,
                listing_id=listing_id,
                asset_id=asset_id,
                seller_floor_price=reserve_price,
                starting_price=starting_price,
                max_rounds=max_rounds,
                expires_minutes=expires_minutes,
            )

        # 非黑板模式使用原有逻辑（简化实现）
        import uuid
        negotiation_id = str(uuid.uuid4())[:32]
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        session = NegotiationSessions(
            negotiation_id=negotiation_id,
            seller_user_id=seller_user_id,
            buyer_user_id=buyer_user_id,
            listing_id=listing_id,
            asset_id=asset_id,
            mechanism_type=mechanism_type,
            max_rounds=max_rounds,
            status="pending",
            current_round=0,
            current_turn="seller",
            starting_price=int(starting_price * 100) if starting_price else None,
            reserve_price=int(reserve_price * 100) if reserve_price else None,
            shared_board={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "negotiation_history": [],
                "event_log": [],
            },
            expires_at=expires_at,
        )

        self.db.add(session)
        await self.db.commit()

        return negotiation_id
