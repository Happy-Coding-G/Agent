"""
Tests for Mechanism Selection Policy

测试机制选择策略服务的各种场景。
"""
import pytest
from decimal import Decimal

from app.schemas.trade_goal import (
    TradeGoal,
    TradeIntent,
    AssetType,
    TradeConstraints,
    PriceStrategy,
    AutonomyMode,
    ApprovalPolicy,
)
from app.services.trade.mechanism_selection_policy import (
    select_mechanism,
    MechanismSelection,
    NegotiationMechanism,
    EngineType,
)


class TestSelectMechanism:
    """测试机制选择策略——直接交易模式"""

    def test_all_scenarios_select_direct(self):
        """所有场景统一返回 direct 机制"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=1000.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert isinstance(selection, MechanismSelection)
        assert selection.mechanism_type == NegotiationMechanism.DIRECT
        assert selection.engine_type == EngineType.SIMPLE
        assert selection.expected_participants == 1

    def test_sell_scenario_selects_direct(self):
        """出售场景也返回直接交易"""
        goal = TradeGoal(
            intent=TradeIntent.SELL,
            asset_id="asset_123",
            min_price=500.0,
            target_price=800.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.DIRECT
        assert "direct" in selection.selection_reason.lower()

    def test_high_value_asset_still_direct(self):
        """高价值资产仍使用直接交易"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_456",
            target_price=50000.0,
            asset_type=AssetType.DIGITAL_ART,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.DIRECT

    def test_direct_when_preferred(self):
        """用户偏好被忽略，始终返回 direct"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_789",
            target_price=2000.0,
            preferred_mechanism="bilateral",
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.DIRECT

    def test_auction_strategy_ignored(self):
        """拍卖策略被忽略，始终返回 direct"""
        goal = TradeGoal(
            intent=TradeIntent.SELL,
            asset_id="asset_999",
            min_price=1000.0,
            target_price=2000.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            price_strategy=PriceStrategy.AUCTION,
        )

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.DIRECT
        assert selection.engine_type == EngineType.SIMPLE

    def test_high_volume_still_direct(self):
        """大批量交易仍使用直接交易"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_batch",
            target_price=100.0,
            quantity=1000,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.DIRECT

    def test_manual_mode_selects_simple_engine(self):
        """手动模式仍使用简单引擎"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_manual",
            target_price=500.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints(
            autonomy_mode=AutonomyMode.MANUAL_STEP,
        )

        selection = select_mechanism(goal, constraints)

        assert selection.engine_type == EngineType.SIMPLE

    def test_mechanism_selection_to_dict(self):
        """测试序列化"""
        selection = MechanismSelection(
            mechanism_type=NegotiationMechanism.DIRECT,
            engine_type=EngineType.SIMPLE,
            expected_participants=1,
            selection_reason="Test reason",
        )

        data = selection.dict()

        assert data["mechanism_type"] == "direct"
        assert data["engine_type"] == "simple"
        assert data["expected_participants"] == 1
        assert data["selection_reason"] == "Test reason"


class TestMechanismSelectionEdgeCases:
    """测试边界情况"""

    def test_very_low_price(self):
        """极低价格场景"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_low",
            target_price=0.01,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert isinstance(selection, MechanismSelection)
        assert selection.mechanism_type == NegotiationMechanism.DIRECT

    def test_very_high_price(self):
        """极高价格场景"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_high",
            target_price=999999999.99,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert isinstance(selection, MechanismSelection)
        assert selection.mechanism_type == NegotiationMechanism.DIRECT
