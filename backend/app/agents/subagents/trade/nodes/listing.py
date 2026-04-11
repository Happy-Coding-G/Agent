"""
Listing Trade Nodes

资产上架相关节点
"""
import logging

from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


async def execute_listing(self, state: TradeState) -> TradeState:
    """
    执行资产上架操作

    流程：
    1. 创建数据库 listing 记录
    2. 创建协商会话 (状态: pending)
    3. 返回上架结果
    """
    if not state.get("success"):
        return state

    try:
        # 获取计算好的参数
        calculated_price = state.get("calculated_price", 50.0)
        mechanism = state.get("selected_mechanism", "bilateral")
        asset_id = state.get("asset_id", "")
        space_id = state.get("space_public_id", "")

        # 这里简化实现，实际应调用 trade_negotiation_service.create_listing
        # 完整实现需要包含：
        # - 创建 TradeListing 记录
        # - 创建 NegotiationSession 记录
        # - 初始化事件溯源状态

        state["result"] = {
            "success": True,
            "status": "pending",
            "message": "Listing workflow initiated",
            "calculated_price": calculated_price,
            "mechanism": mechanism,
            "asset_id": asset_id,
            "space_id": space_id,
            # 实际应返回创建的 listing_id 和 negotiation_id
            "listing_id": None,
            "negotiation_id": None,
        }
        return state

    except Exception as e:
        logger.error(f"Listing execution failed: {e}")
        state["success"] = False
        state["error"] = str(e)
        return state
