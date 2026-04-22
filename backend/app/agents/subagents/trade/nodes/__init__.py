"""Trade nodes package.

Legacy LangGraph nodes. Core business logic has been extracted to
trade_tools.py. These modules are kept for reference but no longer
used by the main agent orchestration.
"""

from typing import Any, Dict

from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository


class TradeNodes:
    """
    交易处理节点集合（遗留）。

    核心功能已迁移至 trade_tools.py。
    """

    def __init__(self, db, skills: Dict[str, Any]):
        self.db = db
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.skills = skills

    from app.agents.subagents.trade.nodes.common import (
        format_result,
    )

    from app.agents.subagents.trade.nodes.agent_first import (
        normalize_goal,
        load_user_config,
        load_asset_context,
        evaluate_market,
        evaluate_risk,
        execute_direct_trade,
        check_approval,
        settle_or_continue,
        publish_state,
    )


__all__ = ["TradeNodes"]
