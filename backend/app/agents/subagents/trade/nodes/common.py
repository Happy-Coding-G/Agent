"""
Common Trade Nodes - Direct Trade Mode

通用交易处理节点，被多个工作流复用

重要：机制选择已通过 policy 简化为 always direct，
本模块保留兼容性但不再实际做复杂决策。
"""
"""
Common Trade Nodes - Direct Trade Mode

通用交易处理节点（select_mechanism、format_result 在 graph 中仍被引用）
"""
import logging
from datetime import datetime, timezone

from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)

# Fallback pricing heuristic constants
_PRICE_DEFAULT = 50.0


async def select_mechanism(self, state: TradeState) -> TradeState:
    """
    选择交易机制

    当前简化版本：所有交易统一使用 direct（直接交易）模式。
    保留调用 mechanism_selection_policy 以支持未来扩展。
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

            # 统一策略始终返回 direct
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

        # 兼容旧模式
        state["selected_mechanism"] = "direct"
        return state

    except Exception as e:
        logger.error(f"Mechanism selection failed: {e}")
        state["selected_mechanism"] = "direct"
        state["mechanism_selection"] = {
            "mechanism_type": "direct",
            "engine_type": "simple",
            "selection_reason": f"Error during selection: {e}",
            "expected_participants": 1,
            "requires_approval": False,
        }
        return state


async def format_result(self, state: TradeState) -> TradeState:
    """格式化最终结果"""
    state["completed_at"] = datetime.now(timezone.utc)

    if not state.get("success"):
        return state

    if "result" not in state:
        state["result"] = {
            "success": state.get("success", False),
            "error": state.get("error"),
        }

    return state
