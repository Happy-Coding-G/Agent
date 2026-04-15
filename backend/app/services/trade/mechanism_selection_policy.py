"""
Mechanism Selection Policy - 机制选择策略

全项目唯一机制选择策略。

输入：
1. 交易目标
2. 用户配置
3. 市场状态
4. 风控等级
5. 预期参与人数

输出：
1. mechanism_type
2. engine_type
3. selection_reason
4. requires_approval
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from app.schemas.trade_goal import (
    TradeGoal,
    TradeConstraints,
    MechanismSelection,
    TradeIntent,
    AutonomyMode,
    NegotiationMechanism,
    EngineType,
)

# Backward-compatible re-exports
__all__ = [
    "MechanismSelectionPolicy",
    "select_mechanism",
    "MechanismSelection",
    "NegotiationMechanism",
    "EngineType",
    "MarketContext",
    "RiskContext",
    "SelectionInput",
]

logger = logging.getLogger(__name__)


@dataclass
class MarketContext:
    """市场上下文"""
    current_avg_price: Optional[float] = None
    price_volatility: float = 0.0  # 价格波动率
    market_liquidity: str = "medium"  # low/medium/high
    recent_trades_count: int = 0
    active_listings_count: int = 0


@dataclass
class RiskContext:
    """风控上下文"""
    risk_level: str = "low"  # low/medium/high
    user_trust_score: float = 1.0
    is_first_transaction: bool = False
    requires_manual_review: bool = False


@dataclass
class SelectionInput:
    """机制选择输入"""
    goal: TradeGoal
    constraints: TradeConstraints
    market: MarketContext
    risk: RiskContext
    user_config: Dict[str, Any]


class MechanismSelectionPolicy:
    """
    机制选择策略

    这是全项目唯一的机制选择决策点。
    所有机制选择逻辑必须集中在这里。
    """

    # 并发阈值配置
    BILATERAL_MAX_PARTICIPANTS = 2
    AUCTION_MIN_PARTICIPANTS = 3
    HIGH_CONCURRENCY_THRESHOLD = 10

    # 价格阈值（相对于目标价格的偏差比例）
    HIGH_VALUE_THRESHOLD = 0.3  # 30%

    @classmethod
    def select_mechanism(cls, input_data: SelectionInput) -> MechanismSelection:
        """
        选择机制

        这是唯一的机制选择入口。
        """
        goal = input_data.goal
        constraints = input_data.constraints
        market = input_data.market
        risk = input_data.risk

        logger.info(
            f"Selecting mechanism for goal: {goal.intent}, "
            f"asset: {goal.asset_id}, target_price: {goal.target_price}"
        )

        # 1. 检查用户是否有明确偏好
        if goal.preferred_mechanism and goal.preferred_mechanism != "auto":
            return cls._apply_user_preference(input_data)

        # 2. 根据意图类型选择
        if goal.intent == TradeIntent.SELL_ASSET:
            return cls._select_for_sell(input_data)
        elif goal.intent == TradeIntent.BUY_ASSET:
            return cls._select_for_buy(input_data)
        else:
            return cls._select_default(input_data)

    @classmethod
    def _apply_user_preference(cls, input_data: SelectionInput) -> MechanismSelection:
        """应用用户明确偏好的机制"""
        goal = input_data.goal
        constraints = input_data.constraints

        preference = goal.preferred_mechanism

        if preference == "bilateral":
            return MechanismSelection(
                mechanism_type="bilateral",
                engine_type="simple",
                selection_reason="User explicitly preferred bilateral negotiation",
                expected_participants=2,
                requires_approval=constraints.approval_policy != "none",
                requires_full_audit=False,
            )
        elif preference == "auction":
            expected = constraints.max_participants or 10
            return MechanismSelection(
                mechanism_type="auction",
                engine_type="event_sourced" if expected > 2 else "simple",
                selection_reason="User explicitly preferred auction",
                expected_participants=expected,
                requires_approval=constraints.approval_policy != "none",
                requires_full_audit=expected > cls.BILATERAL_MAX_PARTICIPANTS,
            )

        return cls._select_default(input_data)

    @classmethod
    def _select_for_sell(cls, input_data: SelectionInput) -> MechanismSelection:
        """为出售场景选择机制"""
        goal = input_data.goal
        constraints = input_data.constraints
        market = input_data.market
        risk = input_data.risk

        # 决策因素
        factors = []

        # 1. 检查是否为高价值资产
        is_high_value = cls._is_high_value(goal, market)
        if is_high_value:
            factors.append("high_value_asset")

        # 2. 检查市场流动性
        high_liquidity = market.market_liquidity == "high"
        if high_liquidity:
            factors.append("high_market_liquidity")

        # 3. 检查紧迫性
        urgent = goal.urgency == "high"
        if urgent:
            factors.append("urgent_deadline")

        # 4. 检查风险等级
        high_risk = risk.risk_level == "high"

        # 决策逻辑
        if urgent and not is_high_value:
            # 紧急 + 非高价值 -> 直接交易或双边快速协商
            return MechanismSelection(
                mechanism_type="bilateral",
                engine_type="simple",
                selection_reason=f"Urgent sale with moderate value. Factors: {factors}",
                expected_participants=2,
                requires_approval=risk.requires_manual_review,
                requires_full_audit=False,
            )

        if is_high_value or high_liquidity:
            # 高价值或高流动性 -> 拍卖获取最优价格
            expected = cls._estimate_participants(goal, market, constraints)
            return MechanismSelection(
                mechanism_type="auction",
                engine_type="event_sourced" if expected > cls.BILATERAL_MAX_PARTICIPANTS else "simple",
                selection_reason=f"High value or liquidity suggests auction. Factors: {factors}",
                expected_participants=expected,
                requires_approval=is_high_value or risk.requires_manual_review,
                requires_full_audit=expected > cls.BILATERAL_MAX_PARTICIPANTS,
            )

        # 默认：双边协商
        return MechanismSelection(
            mechanism_type="bilateral",
            engine_type="simple",
            selection_reason=f"Default bilateral for standard sale. Factors: {factors}",
            expected_participants=2,
            requires_approval=risk.requires_manual_review,
            requires_full_audit=False,
        )

    @classmethod
    def _select_for_buy(cls, input_data: SelectionInput) -> MechanismSelection:
        """为购买场景选择机制"""
        goal = input_data.goal
        constraints = input_data.constraints
        market = input_data.market
        risk = input_data.risk

        factors = []

        # 1. 是否针对特定 listing
        specific_listing = goal.listing_id is not None
        if specific_listing:
            factors.append("specific_listing")

        # 2. 是否为高预算
        high_budget = cls._is_high_budget(goal, constraints)
        if high_budget:
            factors.append("high_budget")

        # 3. 紧迫性
        urgent = goal.urgency == "high"
        if urgent:
            factors.append("urgent")

        # 决策逻辑
        if specific_listing:
            # 针对特定 listing -> 双边协商
            return MechanismSelection(
                mechanism_type="bilateral",
                engine_type="simple",
                selection_reason=f"Buying specific listing. Factors: {factors}",
                expected_participants=2,
                requires_approval=risk.requires_manual_review,
                requires_full_audit=False,
            )

        if urgent and not high_budget:
            # 紧急购买 + 非高预算 -> 双边快速协商
            return MechanismSelection(
                mechanism_type="bilateral",
                engine_type="simple",
                selection_reason=f"Urgent purchase. Factors: {factors}",
                expected_participants=2,
                requires_approval=risk.requires_manual_review,
                requires_full_audit=False,
            )

        if high_budget or constraints.max_participants > cls.BILATERAL_MAX_PARTICIPANTS:
            # 高预算或多参与者 -> 拍卖
            expected = cls._estimate_participants(goal, market, constraints)
            return MechanismSelection(
                mechanism_type="auction",
                engine_type="event_sourced" if expected > cls.BILATERAL_MAX_PARTICIPANTS else "simple",
                selection_reason=f"High budget or multi-participant scenario. Factors: {factors}",
                expected_participants=expected,
                requires_approval=high_budget or risk.requires_manual_review,
                requires_full_audit=expected > cls.BILATERAL_MAX_PARTICIPANTS,
            )

        # 默认：双边协商
        return MechanismSelection(
            mechanism_type="bilateral",
            engine_type="simple",
            selection_reason=f"Default bilateral for purchase. Factors: {factors}",
            expected_participants=2,
            requires_approval=risk.requires_manual_review,
            requires_full_audit=False,
        )

    @classmethod
    def _select_default(cls, input_data: SelectionInput) -> MechanismSelection:
        """默认选择"""
        return MechanismSelection(
            mechanism_type="bilateral",
            engine_type="simple",
            selection_reason="Default mechanism for unspecified scenario",
            expected_participants=2,
            requires_approval=input_data.risk.requires_manual_review,
            requires_full_audit=False,
        )

    @classmethod
    def _is_high_value(cls, goal: TradeGoal, market: MarketContext) -> bool:
        """判断是否高价值资产"""
        if goal.target_price is None:
            return False

        # 绝对价格阈值（例如 10000元）
        ABSOLUTE_THRESHOLD = 10000.0

        # 相对市场均价
        if market.current_avg_price and market.current_avg_price > 0:
            relative_ratio = goal.target_price / market.current_avg_price
            return goal.target_price > ABSOLUTE_THRESHOLD or relative_ratio > 1.5

        return goal.target_price > ABSOLUTE_THRESHOLD

    @classmethod
    def _is_high_budget(cls, goal: TradeGoal, constraints: TradeConstraints) -> bool:
        """判断是否高预算"""
        if constraints.budget_limit is None:
            return False

        ABSOLUTE_THRESHOLD = 10000.0
        return constraints.budget_limit > ABSOLUTE_THRESHOLD

    @classmethod
    def _estimate_participants(
        cls,
        goal: TradeGoal,
        market: MarketContext,
        constraints: TradeConstraints,
    ) -> int:
        """估计参与者数量"""
        # 基于市场活跃度
        if market.active_listings_count > 100:
            base = 10
        elif market.active_listings_count > 50:
            base = 5
        else:
            base = 2

        # 基于用户约束
        if constraints.max_participants:
            base = min(base, constraints.max_participants)

        # 基于紧迫性调整
        if goal.urgency == "high":
            base = max(2, base // 2)

        return max(2, base)


# ============================================================================
# 便捷函数
# ============================================================================

def select_mechanism(
    goal: TradeGoal,
    constraints: TradeConstraints,
    market_context: Optional[MarketContext] = None,
    risk_context: Optional[RiskContext] = None,
    user_config: Optional[Dict[str, Any]] = None,
) -> MechanismSelection:
    """
    便捷函数：选择机制

    这是外部调用的主要入口。
    """
    input_data = SelectionInput(
        goal=goal,
        constraints=constraints,
        market=market_context or MarketContext(),
        risk=risk_context or RiskContext(),
        user_config=user_config or {},
    )

    return MechanismSelectionPolicy.select_mechanism(input_data)
