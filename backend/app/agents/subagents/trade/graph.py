"""
TradeAgent Graph

基于LangGraph的交易协商工作流
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableLambda

from app.agents.subagents.trade.state import TradeState
from app.agents.subagents.trade.nodes import TradeNodes

logger = logging.getLogger(__name__)


def create_trade_graph(db, skills: Dict[str, Any]) -> StateGraph:
    """
    创建交易协商的StateGraph

    工作流：
    1. validate_input -> 验证输入
    2. load_asset -> 加载资产信息
    3. calculate_price -> 计算价格
    4. select_mechanism -> 选择机制
    5. execute_* -> 执行具体操作（根据action分支）
    6. format_result -> 格式化结果
    """
    nodes = TradeNodes(db, skills)

    # 创建Graph
    builder = StateGraph(TradeState)

    # 添加节点
    builder.add_node("validate_input", RunnableLambda(nodes.validate_input))
    builder.add_node("load_asset", RunnableLambda(nodes.load_asset))
    builder.add_node("calculate_price", RunnableLambda(nodes.calculate_price))
    builder.add_node("select_mechanism", RunnableLambda(nodes.select_mechanism))
    builder.add_node("execute_listing", RunnableLambda(nodes.execute_listing))
    builder.add_node("execute_purchase", RunnableLambda(nodes.execute_purchase))
    builder.add_node("format_result", RunnableLambda(nodes.format_result))

    # 定义流程
    builder.add_edge("validate_input", "load_asset")
    builder.add_edge("load_asset", "calculate_price")
    builder.add_edge("calculate_price", "select_mechanism")

    # 根据action分支
    builder.add_conditional_edges(
        "select_mechanism",
        lambda state: state.get("action", "listing"),
        {
            "listing": "execute_listing",
            "purchase": "execute_purchase",
            "auction_bid": "execute_purchase",
            "bilateral": "execute_purchase",
            "yield": "execute_listing",  # 简化处理
        }
    )

    # 汇聚到结果格式化
    builder.add_edge("execute_listing", "format_result")
    builder.add_edge("execute_purchase", "format_result")
    builder.add_edge("format_result", END)

    builder.set_entry_point("validate_input")

    return builder.compile()


def should_continue(state: TradeState) -> str:
    """判断是否继续执行"""
    if not state.get("success"):
        return "error"
    return "continue"
