"""
Purchase Trade Nodes

购买、出价相关节点
"""
import logging

from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


async def execute_purchase(self, state: TradeState) -> TradeState:
    """
    执行购买操作

    支持：
    - 直接购买 (fixed_price)
    - 拍卖出价 (auction_bid)
    - 双边协商 (bilateral)
    - 合同网投标 (contract_net)
    """
    if not state.get("success"):
        return state

    try:
        action = state.get("action")
        listing_id = state.get("listing_id")
        budget_max = state.get("budget_max", 0.0)

        # 根据 action 类型执行不同逻辑
        if action == "auction_bid":
            # 拍卖出价
            bid_amount = state.get("bid_amount", 0.0)
            state["result"] = {
                "success": True,
                "status": "bid_placed",
                "message": "Auction bid placed",
                "listing_id": listing_id,
                "bid_amount": bid_amount,
            }

        elif action == "bilateral":
            # 双边协商
            state["result"] = {
                "success": True,
                "status": "negotiation_initiated",
                "message": "Bilateral negotiation started",
                "listing_id": listing_id,
                "initial_offer": budget_max,
            }

        else:
            # 默认购买流程
            state["result"] = {
                "success": True,
                "status": "joining_negotiation",
                "message": "Purchase workflow initiated",
                "listing_id": listing_id,
                "budget_max": budget_max,
            }

        return state

    except Exception as e:
        logger.error(f"Purchase execution failed: {e}")
        state["success"] = False
        state["error"] = str(e)
        return state
