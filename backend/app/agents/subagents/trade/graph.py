"""
TradeAgent Graph - Direct Trade Mode

基于 LangGraph 的直接交易执行工作流。

简化的执行链路：
normalize_goal -> load_user_config -> load_asset_context -> evaluate_market
-> evaluate_risk -> select_mechanism -> execute_direct_trade -> check_approval
-> settle_or_continue -> publish_state
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableLambda

from app.agents.subagents.trade.state import TradeState
from app.agents.subagents.trade.nodes import TradeNodes

logger = logging.getLogger(__name__)


def create_direct_trade_graph(db, skills: Dict[str, Any]) -> StateGraph:
    """
    创建直接交易 StateGraph。

    工作流（线性，无循环）：
    normalize_goal -> load_user_config -> load_asset_context -> evaluate_market
    -> evaluate_risk -> select_mechanism -> execute_direct_trade -> check_approval
    -> settle_or_continue -> publish_state -> format_result -> END
    """
    nodes = TradeNodes(db, skills)

    builder = StateGraph(TradeState)

    builder.add_node("normalize_goal", RunnableLambda(nodes.normalize_goal))
    builder.add_node("load_user_config", RunnableLambda(nodes.load_user_config))
    builder.add_node("load_asset_context", RunnableLambda(nodes.load_asset_context))
    builder.add_node("evaluate_market", RunnableLambda(nodes.evaluate_market))
    builder.add_node("evaluate_risk", RunnableLambda(nodes.evaluate_risk))
    builder.add_node("select_mechanism", RunnableLambda(nodes.select_mechanism))
    builder.add_node("execute_direct_trade", RunnableLambda(nodes.execute_direct_trade))
    builder.add_node("check_approval", RunnableLambda(nodes.check_approval))
    builder.add_node("settle_or_continue", RunnableLambda(nodes.settle_or_continue))
    builder.add_node("publish_state", RunnableLambda(nodes.publish_state))
    builder.add_node("format_result", RunnableLambda(nodes.format_result))

    # 线性流程，无分支循环
    builder.set_entry_point("normalize_goal")
    builder.add_edge("normalize_goal", "load_user_config")
    builder.add_edge("load_user_config", "load_asset_context")
    builder.add_edge("load_asset_context", "evaluate_market")
    builder.add_edge("evaluate_market", "evaluate_risk")
    builder.add_edge("evaluate_risk", "select_mechanism")
    builder.add_edge("select_mechanism", "execute_direct_trade")
    builder.add_edge("execute_direct_trade", "check_approval")
    builder.add_edge("check_approval", "settle_or_continue")
    builder.add_edge("settle_or_continue", "publish_state")
    builder.add_edge("publish_state", "format_result")
    builder.add_edge("format_result", END)

    return builder.compile()
