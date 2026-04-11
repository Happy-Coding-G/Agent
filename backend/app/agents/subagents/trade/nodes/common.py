"""
Common Trade Nodes

通用交易处理节点，被多个工作流复用
"""
import logging
from datetime import datetime

from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


async def validate_input(self, state: TradeState) -> TradeState:
    """验证输入参数"""
    try:
        action = state.get("action")
        if not action:
            state["success"] = False
            state["error"] = "Missing required field: action"
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
    """选择交易机制"""
    if not state.get("success"):
        return state

    try:
        mechanism_hint = state.get("mechanism_hint")
        if mechanism_hint:
            state["selected_mechanism"] = mechanism_hint
            return state

        pricing_strategy = state.get("pricing_strategy", "negotiable")

        strategy_map = {
            "negotiable": "bilateral",
            "auction": "auction",
            "competitive": "contract_net",
            "fixed": "fixed_price",
        }

        state["selected_mechanism"] = strategy_map.get(pricing_strategy, "bilateral")
        return state

    except Exception as e:
        logger.error(f"Mechanism selection failed: {e}")
        state["selected_mechanism"] = "bilateral"
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
