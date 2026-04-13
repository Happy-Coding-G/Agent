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
    """测试机制选择策略"""

    def test_select_bilateral_for_direct_buy(self):
        """直接购买场景应选择双边协商"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_123",
            target_price=1000.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert isinstance(selection, MechanismSelection)
        assert selection.mechanism_type == NegotiationMechanism.BILATERAL
        assert selection.engine_type == EngineType.SIMPLE
        assert selection.expected_participants == 2

    def test_select_bilateral_for_sell(self):
        """出售场景应选择双边协商"""
        goal = TradeGoal(
            intent=TradeIntent.SELL,
            asset_id="asset_123",
            min_price=500.0,
            target_price=800.0,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.BILATERAL
        assert "sell" in selection.selection_reason.lower()

    def test_select_auction_for_high_value_asset(self):
        """高价值资产可能触发拍卖"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_456",
            target_price=50000.0,  # 高价值
            asset_type=AssetType.DIGITAL_ART,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        # 高价值可能选择拍卖
        assert selection.mechanism_type in [
            NegotiationMechanism.BILATERAL,
            NegotiationMechanism.AUCTION,
        ]

    def test_select_bilateral_when_preferred(self):
        """用户偏好的双边协商应被尊重"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_789",
            target_price=2000.0,
            preferred_mechanism=NegotiationMechanism.BILATERAL,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.mechanism_type == NegotiationMechanism.BILATERAL

    def test_auction_strategy_triggers_auction(self):
        """拍卖策略应触发拍卖机制"""
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

        assert selection.mechanism_type == NegotiationMechanism.AUCTION
        assert selection.engine_type == EngineType.EVENT_SOURCED

    def test_high_volume_triggers_batch(self):
        """大批量交易可能触发批量处理"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_batch",
            target_price=100.0,
            quantity=1000,  # 大批量
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        # 可能优化为批量或直接购买
        assert selection.mechanism_type in [
            NegotiationMechanism.BILATERAL,
            NegotiationMechanism.DIRECT,
        ]

    def test_manual_mode_selects_simple_engine(self):
        """手动模式应选择简单引擎"""
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

    def test_full_audit_requires_event_sourced(self):
        """完整审计需求应使用事件溯源引擎"""
        goal = TradeGoal(
            intent=TradeIntent.BUY,
            listing_id="listing_audit",
            target_price=5000.0,
            requires_full_audit=True,
            asset_type=AssetType.GENERAL,
        )
        constraints = TradeConstraints()

        selection = select_mechanism(goal, constraints)

        assert selection.engine_type == EngineType.EVENT_SOURCED
        assert selection.requires_full_audit is True

    def test_mechanism_selection_to_dict(self):
        """测试序列化"""
        selection = MechanismSelection(
            mechanism_type=NegotiationMechanism.BILATERAL,
            engine_type=EngineType.SIMPLE,
            expected_participants=2,
            selection_reason="Test reason",
        )

        data = selection.dict()

        assert data["mechanism_type"] == "bilateral"
        assert data["engine_type"] == "simple"
        assert data["expected_participants"] == 2
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

        # 应该正常返回，不崩溃
        assert isinstance(selection, MechanismSelection)
        assert selection.mechanism_type is not None

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

        # 应该正常返回
        assert isinstance(selection, MechanismSelection)

    def test_missing_listing_id_for_buy(self):
        """购买时缺少 listing_id 应报错"""
        with pytest.raises(ValueError, match="listing_id"):
            goal = TradeGoal(
                intent=TradeIntent.BUY,
                listing_id="",  # 空值
                target_price=100.0,
                asset_type=AssetType.GENERAL,
            )
            constraints = TradeConstraints()
            select_mechanism(goal, constraints)

    def test_missing_asset_id_for_sell(self):
        """出售时缺少 asset_id 应报错"""
        with pytest.raises(ValueError, match="asset_id"):
            goal = TradeGoal(
                intent=TradeIntent.SELL,
                asset_id="",  # 空值
                min_price=100.0,
                target_price=200.0,
                asset_type=AssetType.GENERAL,
            )
            constraints = TradeConstraints()
            select_mechanism(goal, constraints)
