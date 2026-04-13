"""
TradeAgent Graph - Agent-First Architecture

基于LangGraph的交易目标执行工作流

新执行链路：
normalize_goal -> load_user_config -> load_asset_context -> evaluate_market_and_lineage
-> evaluate_risk -> select_mechanism -> create_or_resume_session -> run_negotiation_round
-> check_approval_gate -> settle_or_continue -> publish_state
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
    创建交易目标执行的 StateGraph (Agent-First)

    工作流：
    1. normalize_goal -> 标准化交易目标
    2. load_user_config -> 加载用户配置
    3. load_asset_context -> 加载资产上下文
    4. evaluate_market_and_lineage -> 评估市场和血缘
    5. evaluate_risk -> 风险评估
    6. select_mechanism -> 选择机制 (使用统一策略)
    7. create_or_resume_session -> 创建或恢复会话
    8. run_negotiation_round -> 执行协商回合
    9. check_approval_gate -> 检查审批门控
    10. settle_or_continue -> 结算或继续
    11. publish_state -> 发布状态
    """
    nodes = TradeNodes(db, skills)

    # 创建 Graph
    builder = StateGraph(TradeState)

    # 添加 Agent-First 节点
    builder.add_node("normalize_goal", RunnableLambda(nodes.normalize_goal))
    builder.add_node("load_user_config", RunnableLambda(nodes.load_user_config))
    builder.add_node("load_asset_context", RunnableLambda(nodes.load_asset_context))
    builder.add_node("evaluate_market", RunnableLambda(nodes.evaluate_market))
    builder.add_node("evaluate_risk", RunnableLambda(nodes.evaluate_risk))
    builder.add_node("select_mechanism", RunnableLambda(nodes.select_mechanism))
    builder.add_node("create_session", RunnableLambda(nodes.create_session))
    builder.add_node("run_negotiation", RunnableLambda(nodes.run_negotiation))
    builder.add_node("check_approval", RunnableLambda(nodes.check_approval))
    builder.add_node("settle_or_continue", RunnableLambda(nodes.settle_or_continue))
    builder.add_node("publish_state", RunnableLambda(nodes.publish_state))

    # 兼容旧流程的节点
    builder.add_node("validate_input", RunnableLambda(nodes.validate_input))
    builder.add_node("load_asset", RunnableLambda(nodes.load_asset))
    builder.add_node("calculate_price", RunnableLambda(nodes.calculate_price))
    builder.add_node("execute_listing", RunnableLambda(nodes.execute_listing))
    builder.add_node("execute_purchase", RunnableLambda(nodes.execute_purchase))
    builder.add_node("format_result", RunnableLambda(nodes.format_result))

    # 定义新的 Agent-First 主流程
    def route_by_goal_type(state: TradeState) -> str:
        """根据目标类型路由"""
        goal_type = state.get("goal_type")
        action = state.get("action")

        # 如果有新的 goal_type，走新流程
        if goal_type in ["sell_asset", "buy_asset", "price_inquiry"]:
            return "agent_first"

        # 否则走兼容流程
        return "legacy"

    def route_after_mechanism(state: TradeState) -> str:
        """机制选择后路由"""
        mechanism = state.get("mechanism_selection", {}).get("mechanism_type", "bilateral")

        if mechanism == "direct":
            return "settle_or_continue"
        return "create_session"

    def route_after_negotiation(state: TradeState) -> str:
        """协商后路由"""
        if state.get("approval_required"):
            return "check_approval"

        status = state.get("result", {}).get("status")
        if status in ["accepted", "rejected", "cancelled"]:
            return "settle_or_continue"

        return "run_negotiation"  # 继续协商

    # 入口路由
    builder.add_conditional_edges(
        "validate_input",
        route_by_goal_type,
        {
            "agent_first": "normalize_goal",
            "legacy": "load_asset",
        }
    )

    # Agent-First 流程
    builder.add_edge("normalize_goal", "load_user_config")
    builder.add_edge("load_user_config", "load_asset_context")
    builder.add_edge("load_asset_context", "evaluate_market")
    builder.add_edge("evaluate_market", "evaluate_risk")
    builder.add_edge("evaluate_risk", "select_mechanism")

    builder.add_conditional_edges(
        "select_mechanism",
        route_after_mechanism,
        {
            "create_session": "create_session",
            "settle_or_continue": "settle_or_continue",
        }
    )

    builder.add_edge("create_session", "run_negotiation")

    builder.add_conditional_edges(
        "run_negotiation",
        route_after_negotiation,
        {
            "check_approval": "check_approval",
            "settle_or_continue": "settle_or_continue",
            "run_negotiation": "run_negotiation",
        }
    )

    builder.add_edge("check_approval", "settle_or_continue")
    builder.add_edge("settle_or_continue", "publish_state")
    builder.add_edge("publish_state", "format_result")

    # 兼容旧流程
    builder.add_edge("load_asset", "calculate_price")
    builder.add_edge("calculate_price", "select_mechanism")

    # 旧流程从 select_mechanism 后根据 action 分支
    def legacy_action_router(state: TradeState) -> str:
        """旧流程 action 路由"""
        action = state.get("action", "listing")

        if action == "listing":
            return "execute_listing"
        elif action in ["purchase", "auction_bid", "bilateral"]:
            return "execute_purchase"
        return "execute_listing"

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
