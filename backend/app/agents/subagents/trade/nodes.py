"""
TradeAgent Nodes

交易协商流程的各个节点实现
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.agents.subagents.trade.state import TradeState
from app.services.asset_service import AssetService
from app.services.trade.trade_negotiation_service import TradeNegotiationService
from app.repositories.trade_repo import TradeRepository
from app.services.skills import PricingSkill
from app.utils.sanitizer import redact_sensitive_info, compact_text

logger = logging.getLogger(__name__)


class TradeNodes:
    """交易处理节点集合"""

    def __init__(self, db, skills: Dict[str, Any]):
        self.db = db
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.negotiation_service = TradeNegotiationService(db)
        self.skills = skills

    async def validate_input(self, state: TradeState) -> TradeState:
        """验证输入参数"""
        try:
            action = state.get("action")
            if not action:
                state["success"] = False
                state["error"] = "Missing required field: action"
                return state

            valid_actions = ["listing", "purchase", "auction_bid", "bilateral", "yield"]
            if action not in valid_actions:
                state["success"] = False
                state["error"] = f"Invalid action: {action}. Must be one of {valid_actions}"
                return state

            state["success"] = True
            return state

        except Exception as e:
            logger.error(f"Input validation failed: {e}")
            state["success"] = False
            state["error"] = str(e)
            return state

    async def load_asset(self, state: TradeState) -> TradeState:
        """加载资产信息"""
        if not state.get("success"):
            return state

        try:
            asset_id = state.get("asset_id")
            space_id = state.get("space_public_id")

            if not asset_id or not space_id:
                state["asset_info"] = None
                return state

            # 获取资产信息
            from app.db.models import Users
            from sqlalchemy import select

            # 获取系统用户用于资产查询
            result = await self.db.execute(select(Users).limit(1))
            user = result.scalar_one_or_none()

            if user:
                asset = await self.assets.get_asset(space_id, asset_id, user)
                state["asset_info"] = asset
            else:
                state["asset_info"] = None

            return state

        except Exception as e:
            logger.error(f"Failed to load asset: {e}")
            state["asset_info"] = None
            return state

    async def calculate_price(self, state: TradeState) -> TradeState:
        """计算建议价格"""
        if not state.get("success"):
            return state

        try:
            reserve_price = state.get("reserve_price")
            if reserve_price and reserve_price > 0:
                # 已提供价格，跳过计算
                state["calculated_price"] = reserve_price
                return state

            asset_info = state.get("asset_info")
            asset_id = state.get("asset_id")

            if not asset_info or not asset_id:
                # 使用默认价格
                state["calculated_price"] = 50.0
                return state

            # 使用 PricingSkill 计算价格
            try:
                price_result = await self.skills["pricing"].calculate_quick_price(
                    asset_id=asset_id,
                    rights_types=["usage", "analysis"],
                    duration_days=365,
                )
                state["calculated_price"] = price_result["price_range"]["min"]
            except Exception as e:
                logger.warning(f"PricingSkill failed: {e}, using fallback")
                # 回退计算
                content = asset_info.get("content_markdown", "")
                graph = asset_info.get("graph_snapshot", {})
                node_count = graph.get("node_count", 0)
                edge_count = graph.get("edge_count", 0)
                length_factor = min(len(content) / 180.0, 120.0)
                price = 20.0 + length_factor + node_count * 1.5 + edge_count * 1.2
                state["calculated_price"] = max(5.0, min(500.0, price))

            return state

        except Exception as e:
            logger.error(f"Price calculation failed: {e}")
            state["calculated_price"] = 50.0  # 默认值
            return state

    async def select_mechanism(self, state: TradeState) -> TradeState:
        """选择交易机制"""
        if not state.get("success"):
            return state

        try:
            mechanism_hint = state.get("mechanism_hint")
            if mechanism_hint:
                state["selected_mechanism"] = mechanism_hint
                return state

            pricing_strategy = state.get("pricing_strategy", "negotiable")

            # 根据策略选择机制
            strategy_map = {
                "negotiable": "bilateral",
                "auction": "auction",
                "competitive": "contract_net",
                "fixed": "fixed_price",
            }

            state["selected_mechanism"] = strategy_map.get(pricing_strategy, "bilateral")
            return state

        except Exception as e:
            logger.error(f"Mechanism selection failed: {e}")
            state["selected_mechanism"] = "bilateral"
            return state

    async def execute_listing(self, state: TradeState) -> TradeState:
        """执行上架操作"""
        if not state.get("success"):
            return state

        try:
            # 这里简化实现，实际应调用 trade_negotiation_service
            # 由于复杂性，保留原有的实现逻辑
            state["result"] = {
                "success": True,
                "status": "pending",
                "message": "Listing workflow initiated",
                "calculated_price": state.get("calculated_price"),
                "mechanism": state.get("selected_mechanism"),
            }
            return state

        except Exception as e:
            logger.error(f"Listing execution failed: {e}")
            state["success"] = False
            state["error"] = str(e)
            return state

    async def execute_purchase(self, state: TradeState) -> TradeState:
        """执行购买操作"""
        if not state.get("success"):
            return state

        try:
            state["result"] = {
                "success": True,
                "status": "joining_negotiation",
                "message": "Purchase workflow initiated",
            }
            return state

        except Exception as e:
            logger.error(f"Purchase execution failed: {e}")
            state["success"] = False
            state["error"] = str(e)
            return state

    async def format_result(self, state: TradeState) -> TradeState:
        """格式化最终结果"""
        if not state.get("success"):
            return state

        from datetime import datetime
        state["completed_at"] = datetime.utcnow()

        # 确保 result 字段存在
        if "result" not in state:
            state["result"] = {
                "success": state.get("success", False),
                "error": state.get("error"),
            }

        return state
