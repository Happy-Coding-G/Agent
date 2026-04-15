"""
Trade Tools - 包装 TradeAgent（复用其 run_goal 模式）
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class TradeGoalInput(BaseModel):
    intent: str = Field(description="交易意图: sell_asset, buy_asset, price_inquiry, market_analysis")
    asset_id: Optional[str] = Field(None, description="资产ID")
    listing_id: Optional[str] = Field(None, description="挂牌ID")
    price: Optional[float] = Field(None, description="目标价格/底价/预算")
    space_id: Optional[str] = Field(None, description="空间public_id")


class CreateListingInput(BaseModel):
    asset_id: str = Field(description="要上架的数字资产ID")
    space_id: str = Field(description="资产所在空间public_id")
    price: Optional[float] = Field(None, description="挂牌价格（不填则自动定价）")
    category: Optional[str] = Field(None, description="资产分类")
    tags: Optional[List[str]] = Field(default_factory=list, description="标签列表")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def create_listing(
        asset_id: str,
        space_id: str,
        price: Optional[float] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from app.services.trade.trade_service import TradeService
        from app.core.errors import ServiceError

        try:
            service = TradeService(db)
            listing = await service.create_listing(
                space_public_id=space_id,
                asset_id=asset_id,
                user=user,
                price_credits=price,
                category=category,
                tags=tags or [],
            )
            return {"success": True, "listing": listing}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"create_listing failed: {e}")
            return {"success": False, "error": str(e)}

    async def trade_goal(
        intent: str,
        asset_id: Optional[str] = None,
        listing_id: Optional[str] = None,
        price: Optional[float] = None,
        space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.agents.subagents.trade.agent import TradeAgent
        from app.schemas.trade_goal import TradeGoal, TradeConstraints, TradeIntent
        from app.services.trade.mechanism_selection_policy import (
            select_mechanism,
            MarketContext,
            RiskContext,
        )

        try:
            agent = TradeAgent(db)

            # 映射常见 intent 到 TradeIntent
            intent_map = {
                "sell": "sell_asset",
                "sell_asset": "sell_asset",
                "buy": "buy_asset",
                "buy_asset": "buy_asset",
                "yield": "market_analysis",
                "price_inquiry": "price_inquiry",
                "market_analysis": "market_analysis",
            }
            trade_intent = intent_map.get(intent.lower(), intent)

            # 构造 goal
            goal_data = {"intent": TradeIntent(trade_intent)}
            if asset_id:
                goal_data["asset_id"] = asset_id
            if listing_id:
                goal_data["listing_id"] = listing_id
            if price is not None:
                if trade_intent == "sell_asset":
                    goal_data["min_price"] = price
                elif trade_intent == "buy_asset":
                    goal_data["max_price"] = price
                else:
                    goal_data["target_price"] = price

            goal = TradeGoal(**goal_data)

            # 机制选择
            mechanism = select_mechanism(
                goal=goal,
                constraints=TradeConstraints(),
                market_context=MarketContext(),
                risk_context=RiskContext(),
            )

            constraints = TradeConstraints(
                autonomy_mode="notify_before_action",
                approval_policy="price_threshold" if (price and price > 10000) else "none",
                approval_threshold=price * 0.9 if price else 0,
            )

            result = await agent.run_goal(
                goal=goal,
                constraints=constraints,
                user=user,
                space_public_id=space_id or "",
            )
            return result
        except Exception as e:
            logger.exception(f"trade_goal failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="create_listing",
            func=create_listing,
            description="将已有的数字资产上架到交易平台。asset_id 和 space_id 必填。",
            args_schema=CreateListingInput,
            coroutine=create_listing,
        ),
        StructuredTool.from_function(
            name="trade_goal",
            func=trade_goal,
            description="执行交易目标（出售资产、购买资产、计算收益）",
            args_schema=TradeGoalInput,
            coroutine=trade_goal,
        ),
    ]
