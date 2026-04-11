"""
TradeAgent Nodes Package

交易处理节点按职责拆分：
- common: 通用节点（验证、加载、价格计算等）
- listing: 资产上架节点
- purchase: 购买/出价节点
"""
from typing import Any, Dict

from app.agents.subagents.trade.state import TradeState
from app.services.asset_service import AssetService
from app.services.trade.trade_negotiation_service import TradeNegotiationService
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
        self.negotiation_service = TradeNegotiationService(db)
        self.skills = skills

    # 从 common 模块导入的节点
    from app.agents.subagents.trade.nodes.common import (
        validate_input,
        load_asset,
        calculate_price,
        select_mechanism,
        format_result,
    )

    # 从 listing 模块导入的节点
    from app.agents.subagents.trade.nodes.listing import execute_listing

    # 从 purchase 模块导入的节点
    from app.agents.subagents.trade.nodes.purchase import execute_purchase


__all__ = ["TradeNodes"]
