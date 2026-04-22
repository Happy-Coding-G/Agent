"""
Common Trade Nodes - Direct Trade Mode

通用交易处理节点（遗留参考）。
核心功能已迁移至 trade_tools.py。
"""
import logging
from datetime import datetime, timezone

from typing import Dict, Any

TradeState = Dict[str, Any]

logger = logging.getLogger(__name__)


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
