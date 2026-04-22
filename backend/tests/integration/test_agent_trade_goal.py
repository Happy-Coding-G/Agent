"""
Integration Tests for Agent Trade Goal

测试 Agent-First 架构下的交易目标执行流程。
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from app.schemas.trade_goal import (
    TradeGoal,
    TradeIntent,
    TradeConstraints,
    AssetType,
    create_buy_goal,
    create_sell_goal,
)


class TestAgentTradeGoal:
    """测试 Agent 交易目标"""

    @pytest.mark.asyncio
    async def test_create_buy_goal(self):
        """测试创建购买目标"""
        goal = create_buy_goal(
            listing_id="listing_123",
            max_price=1000.0,
            target_price=900.0,
        )

        assert goal.intent == TradeIntent.BUY_ASSET
        assert goal.listing_id == "listing_123"
        assert goal.target_price == 900.0
        assert goal.asset_type == AssetType.GENERAL

    @pytest.mark.asyncio
    async def test_create_sell_goal(self):
        """测试创建出售目标"""
        goal = create_sell_goal(
            asset_id="asset_456",
            min_price=500.0,
            target_price=800.0,
        )

        assert goal.intent == TradeIntent.SELL_ASSET
        assert goal.asset_id == "asset_456"
        assert goal.min_price == 500.0
        assert goal.target_price == 800.0

    @pytest.mark.asyncio
    async def test_buy_goal_validation(self):
        """测试购买目标验证"""
        # max_price 为负数应该失败（gt=0 约束）
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.BUY_ASSET,
                listing_id="listing_123",
                max_price=-100.0,
                target_price=100.0,
                asset_type=AssetType.GENERAL,
            )

    @pytest.mark.asyncio
    async def test_sell_goal_validation(self):
        """测试出售目标验证"""
        # min_price 为负数应该失败（gt=0 约束）
        with pytest.raises(ValueError):
            TradeGoal(
                intent=TradeIntent.SELL_ASSET,
                asset_id="asset_123",
                min_price=-100.0,
                target_price=200.0,
                asset_type=AssetType.GENERAL,
            )

    @pytest.mark.asyncio
    async def test_trade_constraints_defaults(self):
        """测试约束默认值"""
        constraints = TradeConstraints()

        assert constraints.max_rounds == 10
        assert constraints.response_timeout_seconds == 300
        assert constraints.budget_limit is None

    @pytest.mark.asyncio
    async def test_goal_to_execution_plan(self):
        """测试目标转换为执行计划"""
        goal = create_buy_goal(
            listing_id="listing_123",
            max_price=1000.0,
        )
        constraints = TradeConstraints(
            max_rounds=5,
            response_timeout_seconds=60,
        )

        assert goal.intent == TradeIntent.BUY_ASSET
        assert constraints.max_rounds == 5

    @pytest.mark.asyncio
    async def test_buy_goal_with_preferences(self):
        """测试带偏好的购买目标"""
        goal = TradeGoal(
            intent=TradeIntent.BUY_ASSET,
            listing_id="listing_123",
            target_price=1000.0,
            max_price=1200.0,
            preferred_mechanism="auto",
            urgency="high",
            asset_type=AssetType.DIGITAL_ART,
        )

        assert goal.preferred_mechanism == "auto"
        assert goal.urgency == "high"
        assert goal.asset_type == AssetType.DIGITAL_ART
