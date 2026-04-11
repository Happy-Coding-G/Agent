"""
TradeAgent - LangGraph-based Trading Agent

基于LangGraph的交易协商Agent，统一架构与其他SubAgent一致。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.trade_negotiation_service import TradeNegotiationService
from app.db.models import Users, NegotiationSessions
from app.core.errors import ServiceError
from app.services.base import SpaceAwareService
from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository
from app.utils.sanitizer import redact_sensitive_info, compact_text
from app.services.skills import (
    PricingSkill,
    DataLineageSkill,
    MarketAnalysisSkill,
    PrivacyComputationSkill,
    AuditSkill,
)

# LangGraph imports
from app.agents.subagents.trade.graph import create_trade_graph
from app.agents.subagents.trade.state import TradeState

logger = logging.getLogger(__name__)


class TradeAgent(SpaceAwareService):
    """
    TradeAgent - LangGraph-based trading agent.

    核心设计：
    1. 使用LangGraph编排交易流程
    2. 协商状态持久化 (NegotiationSessions表)
    3. 集成5个Skills提供业务能力
    4. 支持双边协商/拍卖/合同网三种机制
    """

    PLATFORM_FEE_RATE = 0.05

    def __init__(self, db: AsyncSession, llm_client: Optional[Any] = None):
        super().__init__(db)
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.negotiation_service = TradeNegotiationService(db)
        self.skills = self._init_skills()
        # 创建LangGraph实例
        self.graph = create_trade_graph(db, self.skills)

    def _init_skills(self) -> Dict[str, Any]:
        """初始化Skills"""
        return {
            "pricing": PricingSkill(self._db),
            "lineage": DataLineageSkill(self._db),
            "market": MarketAnalysisSkill(self._db),
            "privacy": PrivacyComputationSkill(self._db),
            "audit": AuditSkill(self._db),
        }

    # ========================================================================
    # High-Level API (Unified Interface via LangGraph)
    # ========================================================================

    async def run(
        self,
        action: str,
        space_public_id: str,
        user: Users,
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的LangGraph入口

        Args:
            action: 操作类型 ("listing", "purchase", "auction_bid", "bilateral")
            space_public_id: Space ID
            user: 当前用户
            **kwargs: 其他参数

        Returns:
            执行结果
        """
        try:
            # 构建初始状态
            initial_state: TradeState = {
                "action": action,
                "space_public_id": space_public_id,
                "user_id": user.id,
                "user_role": "seller" if action == "listing" else "buyer",
                "started_at": datetime.utcnow(),
                "success": True,
                "result": {},
            }

            # 添加额外参数
            initial_state.update(kwargs)

            # 执行Graph
            final_state = await self.graph.ainvoke(initial_state)

            return final_state.get("result", {
                "success": False,
                "error": "No result generated"
            })

        except Exception as e:
            logger.exception(f"TradeAgent run failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "agent_type": "trade",
            }

    # ========================================================================
    # Legacy API (保持向后兼容)
    # ========================================================================

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        pricing_strategy: str = "negotiable",
        reserve_price: Optional[float] = None,
        license_scope: Optional[List[str]] = None,
        mechanism_hint: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        创建资产上架 (使用LangGraph)
        """
        return await self.run(
            action="listing",
            space_public_id=space_public_id,
            user=user,
            asset_id=asset_id,
            pricing_strategy=pricing_strategy,
            reserve_price=reserve_price,
            license_scope=license_scope,
            mechanism_hint=mechanism_hint,
            category=category,
            tags=tags,
        )

    async def initiate_purchase(
        self,
        user: Users,
        listing_id: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
        budget_max: float = 0.0,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发起购买请求 (使用LangGraph)
        """
        return await self.run(
            action="purchase",
            space_public_id="",  # 购买时可能不需要space
            user=user,
            listing_id=listing_id,
            requirements=requirements,
            budget_max=budget_max,
            mechanism_hint=mechanism_hint,
        )

    async def place_auction_bid(
        self,
        lot_id: str,
        user: Users,
        amount: float,
    ) -> Dict[str, Any]:
        """
        拍卖出价 (使用LangGraph)
        """
        return await self.run(
            action="auction_bid",
            space_public_id="",
            user=user,
            listing_id=lot_id,
            bid_amount=amount,
        )

    async def create_bilateral_negotiation(
        self,
        listing_id: str,
        buyer: Users,
        initial_offer: float,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """
        创建双边协商 (使用LangGraph)
        """
        return await self.run(
            action="bilateral",
            space_public_id="",
            user=buyer,
            listing_id=listing_id,
            budget_max=initial_offer,
            mechanism_hint="bilateral",
        )

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _select_mechanism(self, pricing_strategy: str) -> str:
        """根据定价策略选择机制"""
        strategy_map = {
            "negotiable": "bilateral",
            "auction": "auction",
            "competitive": "contract_net",
        }
        return strategy_map.get(pricing_strategy, "bilateral")

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """清理标签"""
        return [t.strip()[:32] for t in tags if t.strip()][:10]
