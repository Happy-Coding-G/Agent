"""
Mechanism Selection Policy - 机制选择策略

全项目唯一机制选择策略。

当前架构：直接交易为唯一模式（过渡期简化）。
协商和拍卖场景已移除，所有交易统一走 direct 路径。

输入：
1. 交易目标
2. 用户配置
3. 市场状态
4. 风控等级

输出：
1. mechanism_type (始终为 "direct")
2. selection_reason
3. requires_approval
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.schemas.trade_goal import (
    TradeGoal,
    TradeConstraints,
    MechanismSelection,
    TradeIntent,
    AutonomyMode,
    NegotiationMechanism,
    EngineType,
)

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
    price_volatility: float = 0.0
    market_liquidity: str = "medium"
    recent_trades_count: int = 0
    active_listings_count: int = 0


@dataclass
class RiskContext:
    """风控上下文"""

    risk_level: str = "low"
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

    当前简化版本：所有交易统一使用直接交易模式。
    未来如需恢复协商/拍卖，可在此扩展决策逻辑。
    """

    @classmethod
    def select_mechanism(cls, input_data: SelectionInput) -> MechanismSelection:
        """
        选择机制

        当前唯一选择：direct（直接交易）
        """
        goal = input_data.goal
        risk = input_data.risk

        logger.info(
            f"Selecting mechanism for goal: {goal.intent}, "
            f"asset: {goal.asset_id}, target_price: {goal.target_price}"
        )

        # 用户明确偏好处理（仅保留 direct 和 auction 偏好，auction 降级为 direct）
        if goal.preferred_mechanism and goal.preferred_mechanism not in ("auto", "direct"):
            logger.info(
                f"User preferred {goal.preferred_mechanism}, "
                f"downgraded to direct (negotiation/auction not supported)"
            )

        # 统一返回 direct
        return MechanismSelection(
            mechanism_type="direct",
            engine_type="simple",
            selection_reason="Direct trade mode (negotiation/auction deprecated)",
            expected_participants=1,
            requires_approval=risk.requires_manual_review or _should_require_approval(goal, risk),
            requires_full_audit=False,
        )


def _should_require_approval(goal: TradeGoal, risk: RiskContext) -> bool:
    """判断是否需要审批"""
    # 高价值交易需要审批
    if goal.target_price and goal.target_price > 10000:
        return True
    # 首次交易需要审批
    if risk.is_first_transaction:
        return True
    # 高风险用户需要审批
    if risk.risk_level == "high":
        return True
    return False


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
