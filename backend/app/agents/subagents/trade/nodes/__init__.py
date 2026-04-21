"""
TradeAgent Nodes Package

交易处理节点按职责拆分：
- common: select_mechanism, format_result
- agent_first: 直接交易执行节点
"""
from typing import Any, Dict

from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository


class TradeNodes:
    """
    交易处理节点集合

    组合所有职责节点，提供统一的节点访问接口
    """

    def __init__(self, db, skills: Dict[str, Any]):
        self.db = db
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.skills = skills

    # common 模块中 graph 仍引用的节点
    from app.agents.subagents.trade.nodes.common import (
        select_mechanism,
        format_result,
    )

    # 直接交易节点
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
