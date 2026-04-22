"""Trade tools backed by TradeService."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class CreateListingInput(BaseModel):
    asset_id: str = Field(description="要上架的数字资产ID")
    space_id: str = Field(description="资产所在空间public_id")
    price: Optional[float] = Field(None, description="挂牌价格（不填则自动定价）")
    category: Optional[str] = Field(None, description="资产分类")
    tags: Optional[List[str]] = Field(default_factory=list, description="标签列表")


class TradeNormalizeGoalInput(BaseModel):
    goal_text: str = Field(description="用户的交易目标描述")


class TradeSelectMechanismInput(BaseModel):
    asset_id: Optional[str] = Field(None, description="资产ID")
    buyer_preferences: Optional[str] = Field(None, description="买方偏好描述")


class TradeExecuteInput(BaseModel):
    action: str = Field(description="交易动作: listing, purchase, inquiry")
    asset_id: Optional[str] = Field(None, description="资产ID")
    space_id: str = Field(description="空间public_id")
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外参数")


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

    async def trade_normalize_goal(goal_text: str) -> Dict[str, Any]:
        """归一化交易目标，补全缺失参数。"""
        try:
            # 解析意图
            intent = "inquiry"
            goal_lower = goal_text.lower()
            if any(kw in goal_lower for kw in ["卖", "上架", "出售", "sell", "listing"]):
                intent = "sell_asset"
            elif any(kw in goal_lower for kw in ["买", "购买", "收购", "buy", "purchase"]):
                intent = "buy_asset"

            goal = {
                "intent": intent,
                "raw_text": goal_text,
            }

            # 提取价格
            price_match = __import__("re").search(r'(\d+(?:\.\d+)?)\s*(?:元| credits?|币)?', goal_text)
            if price_match:
                price = float(price_match.group(1))
                if intent == "sell_asset":
                    goal["target_price"] = price
                    goal["min_price"] = price * 0.9
                else:
                    goal["max_price"] = price
                    goal["target_price"] = price * 0.9
            else:
                if intent == "sell_asset":
                    goal["target_price"] = 50.0
                    goal["min_price"] = 45.0
                else:
                    goal["target_price"] = 50.0
                    goal["max_price"] = 55.0

            # 默认截止时间
            goal["deadline"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

            return {"success": True, "goal": goal}
        except Exception as e:
            logger.exception(f"trade_normalize_goal failed: {e}")
            return {"success": False, "error": str(e)}

    async def trade_select_mechanism(
        asset_id: Optional[str] = None,
        buyer_preferences: Optional[str] = None,
    ) -> Dict[str, Any]:
        """选择交易机制。当前简化版本：所有交易统一使用 direct（直接交易）模式。"""
        return {
            "success": True,
            "mechanism_type": "direct",
            "engine_type": "simple",
            "selection_reason": "当前平台仅支持直接交易模式",
            "requires_approval": False,
        }

    async def trade_execute(
        action: str,
        space_id: str,
        asset_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行交易操作。"""
        from app.services.trade.trade_service import TradeService
        from app.core.errors import ServiceError
        from app.db.models import TradeListings, TradeOrders, Users, DataAssets
        from sqlalchemy import select
        import uuid as _uuid

        payload = payload or {}

        try:
            if action == "listing":
                # 卖方：创建上架记录
                price = payload.get("price", 50.0)
                if not asset_id:
                    return {"success": False, "error": "asset_id is required for listing"}

                # 获取资产标题
                result = await db.execute(select(DataAssets).where(DataAssets.asset_id == asset_id))
                asset = result.scalar_one_or_none()
                title = asset.asset_name if asset else (payload.get("title") or "Untitled Asset")

                # 获取 seller alias
                seller_alias = ""
                if user:
                    seller_alias = getattr(user, "username", "") or ""

                listing = TradeListings(
                    public_id=str(_uuid.uuid4())[:32],
                    asset_id=asset_id,
                    seller_user_id=getattr(user, "id", None),
                    seller_alias=seller_alias,
                    title=title,
                    price_credits=int(price * 100) if price else 0,
                    status="active",
                )
                db.add(listing)
                await db.commit()

                return {
                    "success": True,
                    "status": "listing_created",
                    "listing_id": listing.public_id,
                    "asset_id": asset_id,
                    "price": price,
                    "message": f"上架已创建: {listing.public_id}",
                }

            elif action == "purchase":
                # 买方：创建订单
                listing_id = payload.get("listing_id")
                if not listing_id:
                    return {"success": False, "error": "listing_id is required for purchase"}

                buyer_id = getattr(user, "id", None)

                # 查询 listing
                result = await db.execute(select(TradeListings).where(TradeListings.public_id == listing_id))
                listing = result.scalar_one_or_none()
                if not listing:
                    return {"success": False, "error": "Listing not found"}

                price_credits = listing.price_credits or 0
                platform_fee = int(price_credits * 0.05)
                seller_income = price_credits - platform_fee

                order = TradeOrders(
                    public_id=str(_uuid.uuid4())[:32],
                    listing_id=listing_id,
                    buyer_user_id=buyer_id,
                    seller_user_id=listing.seller_user_id,
                    asset_title_snapshot=listing.title or "",
                    seller_alias_snapshot=listing.seller_alias or "",
                    price_credits=price_credits,
                    platform_fee=platform_fee,
                    seller_income=seller_income,
                    status="pending",
                )
                db.add(order)
                await db.commit()

                return {
                    "success": True,
                    "status": "order_created",
                    "order_id": order.public_id,
                    "listing_id": listing_id,
                    "price": price_credits / 100.0 if price_credits else 0,
                    "message": f"订单已创建: {order.public_id}",
                }

            elif action == "inquiry":
                # 价格查询
                service = TradeService(db)
                market_data = {}
                if asset_id:
                    try:
                        listings_result = await db.execute(
                            select(TradeListings).where(
                                (TradeListings.asset_id == asset_id) &
                                (TradeListings.status == "active")
                            )
                        )
                        listings = listings_result.scalars().all()
                        market_data["active_listings"] = [
                            {"listing_id": l.public_id, "price": l.price_credits / 100.0 if l.price_credits else 0}
                            for l in listings
                        ]
                    except Exception:
                        pass
                return {
                    "success": True,
                    "status": "inquiry",
                    "message": "Price inquiry completed",
                    "market_data": market_data,
                }

            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"trade_execute failed: {e}")
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
            name="trade_normalize_goal",
            func=trade_normalize_goal,
            description="归一化用户交易目标文本，提取意图、价格、截止时间等参数。",
            args_schema=TradeNormalizeGoalInput,
            coroutine=trade_normalize_goal,
        ),
        StructuredTool.from_function(
            name="trade_select_mechanism",
            func=trade_select_mechanism,
            description="选择最优交易机制（当前统一返回 direct 直接交易）。",
            args_schema=TradeSelectMechanismInput,
            coroutine=trade_select_mechanism,
        ),
        StructuredTool.from_function(
            name="trade_execute",
            func=trade_execute,
            description="执行交易操作：listing（上架）、purchase（购买）、inquiry（询价）。",
            args_schema=TradeExecuteInput,
            coroutine=trade_execute,
        ),
    ]
