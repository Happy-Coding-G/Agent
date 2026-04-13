"""
Common Trade Nodes - Agent-First Architecture

通用交易处理节点，被多个工作流复用

重要：机制选择只能通过 mechanism_selection_policy 模块进行，
不允许本地策略映射。
"""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from app.agents.subagents.trade.state import TradeState

if TYPE_CHECKING:
    from app.services.trade.mechanism_selection_policy import MechanismSelectionPolicy

logger = logging.getLogger(__name__)


async def validate_input(self, state: TradeState) -> TradeState:
    """
    验证输入参数

    支持两种输入模式：
    1. Agent-First: goal_type + trade_goal + trade_constraints
    2. Legacy: action + 其他参数
    """
    try:
        # 检查 Agent-First 模式
        goal_type = state.get("goal_type")
        trade_goal = state.get("trade_goal")

        if goal_type and trade_goal:
            # Agent-First 模式验证
            valid_intents = ["sell_asset", "buy_asset", "price_inquiry"]
            if goal_type not in valid_intents:
                state["success"] = False
                state["error"] = f"Invalid goal_type: {goal_type}. Must be one of {valid_intents}"
                return state

            state["success"] = True
            return state

        # 兼容旧模式
        action = state.get("action")
        if not action:
            state["success"] = False
            state["error"] = "Missing required field: action or goal_type"
            return state

        valid_actions = ["listing", "purchase", "auction_bid", "bilateral", "yield"]
        if action not in valid_actions:
            state["success"] = False
            state["error"] = f"Invalid action: {action}. Must be one of {valid_actions}"
            return state

        state["success"] = True
        return state

    except Exception as e:
        logger.error(f"Input validation failed: {e}")
        state["success"] = False
        state["error"] = str(e)
        return state


async def load_asset(self, state: TradeState) -> TradeState:
    """加载资产信息"""
    if not state.get("success"):
        return state

    try:
        asset_id = state.get("asset_id")
        space_id = state.get("space_public_id")

        if not asset_id or not space_id:
            state["asset_info"] = None
            return state

        from app.db.models import Users
        from sqlalchemy import select

        result = await self.db.execute(select(Users).limit(1))
        user = result.scalar_one_or_none()

        if user:
            asset = await self.assets.get_asset(space_id, asset_id, user)
            state["asset_info"] = asset
        else:
            state["asset_info"] = None

        return state

    except Exception as e:
        logger.error(f"Failed to load asset: {e}")
        state["asset_info"] = None
        return state


async def calculate_price(self, state: TradeState) -> TradeState:
    """计算建议价格"""
    if not state.get("success"):
        return state

    try:
        reserve_price = state.get("reserve_price")
        if reserve_price and reserve_price > 0:
            state["calculated_price"] = reserve_price
            return state

        asset_info = state.get("asset_info")
        asset_id = state.get("asset_id")

        if not asset_info or not asset_id:
            state["calculated_price"] = 50.0
            return state

        try:
            price_result = await self.skills["pricing"].calculate_quick_price(
                asset_id=asset_id,
                rights_types=["usage", "analysis"],
                duration_days=365,
            )
            state["calculated_price"] = price_result["price_range"]["min"]
        except Exception as e:
            logger.warning(f"PricingSkill failed: {e}, using fallback")
            content = asset_info.get("content_markdown", "")
            graph = asset_info.get("graph_snapshot", {})
            node_count = graph.get("node_count", 0)
            edge_count = graph.get("edge_count", 0)
            length_factor = min(len(content) / 180.0, 120.0)
            price = 20.0 + length_factor + node_count * 1.5 + edge_count * 1.2
            state["calculated_price"] = max(5.0, min(500.0, price))

        return state

    except Exception as e:
        logger.error(f"Price calculation failed: {e}")
        state["calculated_price"] = 50.0
        return state


async def select_mechanism(self, state: TradeState) -> TradeState:
    """
    选择交易机制

    重要：所有机制选择必须调用 mechanism_selection_policy 模块，
    不允许本地策略映射。
    """
    if not state.get("success"):
        return state

    try:
        # Agent-First 模式：使用统一的机制选择策略
        goal_type = state.get("goal_type")
        if goal_type:
            from app.schemas.trade_goal import TradeGoal, TradeConstraints
            from app.services.trade.mechanism_selection_policy import (
                select_mechanism,
                MarketContext,
                RiskContext,
            )

            goal = TradeGoal(**state.get("trade_goal", {}))
            constraints = TradeConstraints(**state.get("trade_constraints", {}))

            # 使用统一策略选择机制
            mechanism = select_mechanism(
                goal=goal,
                constraints=constraints,
                market_context=state.get("market_context") or MarketContext(),
                risk_context=state.get("risk_context") or RiskContext(),
            )

            state["mechanism_selection"] = mechanism.dict()
            state["engine_type"] = mechanism.engine_type
            state["selected_mechanism"] = mechanism.mechanism_type
            state["approval_required"] = mechanism.requires_approval

            # 记录决策
            if "decisions" not in state:
                state["decisions"] = []
            state["decisions"].append({
                "type": "mechanism_selection",
                "decision": mechanism.mechanism_type,
                "reason": mechanism.selection_reason,
                "engine": mechanism.engine_type,
            })

            return state

        # 兼容旧模式：保留原有逻辑但简化
        mechanism_hint = state.get("mechanism_hint")
        if mechanism_hint:
            state["selected_mechanism"] = mechanism_hint
            return state

        # 旧模式不使用本地策略映射，默认 bilateral
        state["selected_mechanism"] = "bilateral"
        return state

    except Exception as e:
        logger.error(f"Mechanism selection failed: {e}")
        state["selected_mechanism"] = "bilateral"
        state["mechanism_selection"] = {
            "mechanism_type": "bilateral",
            "engine_type": "simple",
            "selection_reason": f"Error during selection: {e}",
            "expected_participants": 2,
            "requires_approval": False,
        }
        return state


async def format_result(self, state: TradeState) -> TradeState:
    """格式化最终结果"""
    if not state.get("success"):
        return state

    state["completed_at"] = datetime.utcnow()

    if "result" not in state:
        state["result"] = {
            "success": state.get("success", False),
            "error": state.get("error"),
        }

    return state
