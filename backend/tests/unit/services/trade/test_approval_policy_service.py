"""
Tests for Approval Policy Service

测试审批策略服务的各种场景。
"""
import pytest

from app.schemas.trade_goal import (
    TradeGoal,
    TradeIntent,
    TradeConstraints,
    ApprovalPolicy,
    AutonomyMode,
    AssetType,
)
from app.services.trade.approval_policy_service import (
    ApprovalPolicyService,
    ApprovalDecision,
    ApprovalTrigger,
    requires_approval,
    get_approval_reason,
)


class TestEvaluateTransaction:
    """测试交易审批评估"""

    def test_always_approval_policy(self):
        """ALWAYS 策略总是需要审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.ALWAYS,
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.MANUAL_MODE
        assert "ALWAYS" in decision.reason

    def test_none_approval_policy(self):
        """NONE 策略从不审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=999999.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.NONE,
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is False
        assert decision.auto_executable is True

    def test_first_transaction_policy(self):
        """首次交易触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.FIRST_TRANSACTION,
        )

        decision = ApprovalPolicyService.evaluate_transaction(
            goal, constraints, is_first_transaction=True
        )

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.FIRST_TRANSACTION

    def test_first_transaction_policy_not_first(self):
        """非首次交易不触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.FIRST_TRANSACTION,
        )

        decision = ApprovalPolicyService.evaluate_transaction(
            goal, constraints, is_first_transaction=False
        )

        assert decision.requires_approval is False

    def test_price_threshold_exceeded(self):
        """超出价格阈值触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=1000.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.PRICE_THRESHOLD,
            approval_threshold=500.0,
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.PRICE_THRESHOLD_EXCEEDED
        assert "exceeds threshold" in decision.reason

    def test_price_threshold_not_exceeded(self):
        """未超出价格阈值不触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=400.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.PRICE_THRESHOLD,
            approval_threshold=500.0,
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is False

    def test_high_value_asset_triggers_approval(self):
        """高价值资产触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=15000.0,  # 超过 HIGH_VALUE_THRESHOLD (10000)
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.HIGH_VALUE_ASSET

    def test_high_budget_triggers_approval(self):
        """高预算触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            budget_limit=60000.0,  # 超过 HIGH_BUDGET_THRESHOLD (50000)
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.HIGH_RISK_OPERATION

    def test_manual_step_autonomy_mode(self):
        """手动步骤自治模式触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            autonomy_mode=AutonomyMode.MANUAL_STEP,
        )

        decision = ApprovalPolicyService.evaluate_transaction(goal, constraints)

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.MANUAL_MODE


class TestEvaluateMechanismSelection:
    """测试机制选择审批"""

    def test_large_auction_requires_approval(self):
        """大型拍卖需要审批"""
        decision = ApprovalPolicyService.evaluate_mechanism_selection(
            mechanism_type="auction",
            expected_participants=100,  # 超过50
        )

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.HIGH_RISK_OPERATION
        assert "Large auction" in decision.reason

    def test_small_auction_no_approval(self):
        """小型拍卖不需要审批"""
        decision = ApprovalPolicyService.evaluate_mechanism_selection(
            mechanism_type="auction",
            expected_participants=10,
        )

        assert decision.requires_approval is False
        assert decision.auto_executable is True


class TestEvaluateSettlement:
    """测试结算审批"""

    def test_settlement_exceeds_budget(self):
        """结算超出预算触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            budget_limit=500.0,
        )

        decision = ApprovalPolicyService.evaluate_settlement(
            final_price=600.0,
            goal=goal,
            constraints=constraints,
        )

        assert decision.requires_approval is True
        assert decision.trigger == ApprovalTrigger.PRICE_THRESHOLD_EXCEEDED

    def test_settlement_within_budget(self):
        """结算在预算内不触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            budget_limit=500.0,
        )

        decision = ApprovalPolicyService.evaluate_settlement(
            final_price=400.0,
            goal=goal,
            constraints=constraints,
        )

        assert decision.requires_approval is False

    def test_settlement_exceeds_target_by_20_percent(self):
        """结算超出目标价格20%触发审批"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        decision = ApprovalPolicyService.evaluate_settlement(
            final_price=125.0,  # 超出 25%
            goal=goal,
            constraints=constraints,
        )

        assert decision.requires_approval is True
        assert ">20%" in decision.reason


class TestHelperFunctions:
    """测试便捷函数"""

    def test_requires_approval_helper(self):
        """测试 requires_approval 便捷函数"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.ALWAYS,
        )

        result = requires_approval(goal, constraints)

        assert result is True

    def test_get_approval_reason_helper(self):
        """测试 get_approval_reason 便捷函数"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=100.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            approval_policy=ApprovalPolicy.ALWAYS,
        )

        reason = get_approval_reason(goal, constraints)

        assert "ALWAYS" in reason
