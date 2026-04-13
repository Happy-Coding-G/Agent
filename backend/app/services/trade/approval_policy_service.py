"""
Approval Policy Service - 审批策略服务

集中定义哪些行为可自动执行，哪些必须人工审批。

这是 Agent-First 架构的审批控制中心。
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from app.schemas.trade_goal import TradeGoal, TradeConstraints, ApprovalPolicy

logger = logging.getLogger(__name__)


class ApprovalTrigger(str, Enum):
    """审批触发原因"""
    PRICE_THRESHOLD_EXCEEDED = "price_threshold_exceeded"
    HIGH_VALUE_ASSET = "high_value_asset"
    HIGH_RISK_OPERATION = "high_risk_operation"
    FIRST_TRANSACTION = "first_transaction"
    MANUAL_MODE = "manual_mode"
    POLICY_VIOLATION = "policy_violation"


@dataclass
class ApprovalDecision:
    """审批决策结果"""
    requires_approval: bool
    trigger: Optional[ApprovalTrigger]
    reason: str
    policy_applied: str
    auto_executable: bool


class ApprovalPolicyService:
    """
    审批策略服务

    集中管理所有审批决策逻辑。
    """

    # 高价值阈值（元）
    HIGH_VALUE_THRESHOLD = 10000.0

    # 高预算阈值（元）
    HIGH_BUDGET_THRESHOLD = 50000.0

    @classmethod
    def evaluate_transaction(
        cls,
        goal: TradeGoal,
        constraints: TradeConstraints,
        current_price: Optional[float] = None,
        user_trust_score: float = 1.0,
        is_first_transaction: bool = False,
    ) -> ApprovalDecision:
        """
        评估交易是否需要审批

        Args:
            goal: 交易目标
            constraints: 交易约束
            current_price: 当前价格
            user_trust_score: 用户信任分数
            is_first_transaction: 是否首次交易

        Returns:
            ApprovalDecision
        """
        # 1. 检查约束中的审批策略
        policy = constraints.approval_policy

        if policy == ApprovalPolicy.ALWAYS:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.MANUAL_MODE,
                reason="Approval policy set to ALWAYS",
                policy_applied="always",
                auto_executable=False,
            )

        if policy == ApprovalPolicy.NONE:
            return ApprovalDecision(
                requires_approval=False,
                trigger=None,
                reason="Approval policy set to NONE",
                policy_applied="none",
                auto_executable=True,
            )

        # 2. 首次交易检查
        if policy == ApprovalPolicy.FIRST_TRANSACTION and is_first_transaction:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.FIRST_TRANSACTION,
                reason="First transaction requires approval",
                policy_applied="first_transaction",
                auto_executable=False,
            )

        # 3. 价格阈值检查
        if policy == ApprovalPolicy.PRICE_THRESHOLD:
            threshold = constraints.approval_threshold
            price_to_check = current_price or goal.target_price

            if threshold and price_to_check and price_to_check > threshold:
                return ApprovalDecision(
                    requires_approval=True,
                    trigger=ApprovalTrigger.PRICE_THRESHOLD_EXCEEDED,
                    reason=f"Price {price_to_check} exceeds threshold {threshold}",
                    policy_applied="price_threshold",
                    auto_executable=False,
                )

        # 4. 高价值资产检查
        target_price = goal.target_price or 0
        if target_price >= cls.HIGH_VALUE_THRESHOLD:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.HIGH_VALUE_ASSET,
                reason=f"High value asset (price: {target_price})",
                policy_applied="high_value",
                auto_executable=False,
            )

        # 5. 高预算检查
        budget = constraints.budget_limit or 0
        if budget >= cls.HIGH_BUDGET_THRESHOLD:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.HIGH_RISK_OPERATION,
                reason=f"High budget operation (budget: {budget})",
                policy_applied="high_budget",
                auto_executable=False,
            )

        # 6. 自治模式检查
        autonomy = constraints.autonomy_mode.value
        if autonomy == "manual_step":
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.MANUAL_MODE,
                reason="Autonomy mode set to MANUAL_STEP",
                policy_applied="manual_mode",
                auto_executable=False,
            )

        # 默认：不需要审批
        return ApprovalDecision(
            requires_approval=False,
            trigger=None,
            reason="No approval triggers matched",
            policy_applied="default",
            auto_executable=True,
        )

    @classmethod
    def evaluate_mechanism_selection(
        cls,
        mechanism_type: str,
        expected_participants: int,
    ) -> ApprovalDecision:
        """
        评估机制选择是否需要审批

        Args:
            mechanism_type: 机制类型
            expected_participants: 预期参与者数量

        Returns:
            ApprovalDecision
        """
        # 高并发拍卖需要审批
        if mechanism_type == "auction" and expected_participants > 50:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.HIGH_RISK_OPERATION,
                reason=f"Large auction ({expected_participants} participants) requires approval",
                policy_applied="large_auction",
                auto_executable=False,
            )

        return ApprovalDecision(
            requires_approval=False,
            trigger=None,
            reason="Mechanism selection approved",
            policy_applied="mechanism_default",
            auto_executable=True,
        )

    @classmethod
    def evaluate_settlement(
        cls,
        final_price: float,
        goal: TradeGoal,
        constraints: TradeConstraints,
    ) -> ApprovalDecision:
        """
        评估结算是否需要审批

        Args:
            final_price: 最终价格
            goal: 交易目标
            constraints: 交易约束

        Returns:
            ApprovalDecision
        """
        # 检查是否超出预算
        budget = constraints.budget_limit
        if budget and final_price > budget:
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.PRICE_THRESHOLD_EXCEEDED,
                reason=f"Final price {final_price} exceeds budget {budget}",
                policy_applied="budget_exceeded",
                auto_executable=False,
            )

        # 检查是否超出目标价格过多
        target = goal.target_price
        if target and final_price > target * 1.2:  # 超出20%
            return ApprovalDecision(
                requires_approval=True,
                trigger=ApprovalTrigger.PRICE_THRESHOLD_EXCEEDED,
                reason=f"Final price {final_price} exceeds target {target} by >20%",
                policy_applied="price_deviation",
                auto_executable=False,
            )

        return ApprovalDecision(
            requires_approval=False,
            trigger=None,
            reason="Settlement approved",
            policy_applied="settlement_default",
            auto_executable=True,
        )


# ============================================================================
# 便捷函数
# ============================================================================

def requires_approval(
    goal: TradeGoal,
    constraints: TradeConstraints,
    **kwargs
) -> bool:
    """便捷函数：检查是否需要审批"""
    decision = ApprovalPolicyService.evaluate_transaction(
        goal=goal,
        constraints=constraints,
        **kwargs
    )
    return decision.requires_approval


def get_approval_reason(
    goal: TradeGoal,
    constraints: TradeConstraints,
    **kwargs
) -> str:
    """便捷函数：获取审批原因"""
    decision = ApprovalPolicyService.evaluate_transaction(
        goal=goal,
        constraints=constraints,
        **kwargs
    )
    return decision.reason
