"""
Trade Agent Service - Production grade adapter using database-backed TradeService.
Replaces file-based storage with ACID transactions.
"""
from __future__ import annotations

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .trade_service import TradeService
from ..asset_service import AssetService
from app.db.models import Users
from app.core.errors import ServiceError


class TradeAgentService:
    """
    Adapter service that wraps the new production-grade TradeService
    and provides backward-compatible API responses.
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        self._trade = TradeService(db)
        self._assets = AssetService(db)

    async def get_privacy_policy(self, space_id: str, user: Users) -> dict:
        """Return privacy policy."""
        return {
            "policy_id": "trade-privacy-v1",
            "version": "2026-02-08",
            "principles": [
                "Least-privilege disclosure by default.",
                "Buyer pre-purchase view is metadata + redacted preview only.",
                "No seller identity leakage: only pseudonymous seller alias is exposed.",
                "Prompt/source object keys/raw graph internals are never disclosed to buyers.",
                "Delivery payload is sanitized by automated redaction rules.",
            ],
            "buyer_visibility": {
                "pre_purchase": [
                    "listing_id", "title", "category", "tags", "price_credits",
                    "public_summary", "preview_excerpt", "seller_alias",
                    "purchase_count", "status"
                ],
                "post_purchase": [
                    "order_id", "listing_id", "asset_title", "purchased_at",
                    "content_markdown", "graph_snapshot", "usage_terms"
                ],
                "never_exposed": [
                    "seller_user_id", "seller_user_key", "asset_prompt",
                    "source_documents", "raw_graph_nodes", "raw_graph_edges",
                    "object_storage_keys", "wallet_internal_ledger"
                ]
            },
            "redaction_rules": [
                "Email addresses",
                "Phone numbers",
                "API keys and token-like secrets",
                "IPv4 addresses",
                "Long numeric identifiers"
            ],
            "delivery_terms": [
                "Delivery content is for licensed personal use only.",
                "Seller identity and private source data are not part of delivery scope.",
                "Reselling raw delivery content outside the platform is prohibited."
            ],
            "notes": [
                "The trading agent runs in a sandbox credit mode.",
                "Automatic yield is strategy-driven simulation and can be tuned."
            ]
        }

    async def list_space_listings(self, space_id: str, user: Users) -> List[dict]:
        """List all listings in a space."""
        assets = await self._assets.list_assets(space_id, user)

        result = []
        for asset in assets:
            result.append({
                "asset_id": asset.get("asset_id"),
                "listing_id": None,
                "title": asset.get("title"),
                "status": "not_listed",
            })

        return result

    async def create_listing(
        self,
        *,
        space_public_id: str,
        asset_id: str,
        user: Users,
        price_credits: Optional[float] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> dict:
        """Create a new listing."""
        result = await self._trade.create_listing(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            price_credits=price_credits,
            category=category,
            tags=tags,
        )

        result["seller_user_id"] = user.id
        result["delivery_scope"] = (await self.get_privacy_policy("", user))["buyer_visibility"]["post_purchase"]

        return result

    async def run_auto_yield(
        self,
        *,
        space_public_id: str,
        user: Users,
        strategy: Optional[str] = None,
    ) -> dict:
        """Run auto-yield for user."""
        result = await self._trade.run_auto_yield(user=user, strategy=strategy)

        return {
            "run_id": result.get("run_id", ""),
            "strategy": result.get("strategy", "balanced"),
            "annual_rate": result.get("annual_rate", 0.08),
            "elapsed_days": result.get("elapsed_days", 0.0),
            "yield_amount": result.get("yield_amount", 0.0),
            "wallet_before": result.get("wallet_before", {}),
            "wallet_after": result.get("wallet_after", {}),
            "listing_adjustments": result.get("listing_adjustments", []),
            "generated_at": result.get("run_id", ""),
        }

    async def list_yield_journal(self, space_id: str, user: Users) -> List[dict]:
        """List yield journal for user."""
        return []

    async def list_market(self, current_user: Users) -> List[dict]:
        """List active market listings."""
        listings = await self._trade.list_market()

        return [
            {
                "listing_id": l["listing_id"],
                "title": l["title"],
                "category": l["category"],
                "tags": l["tags"],
                "price_credits": l["price_credits"],
                "public_summary": l["public_summary"],
                "preview_excerpt": l["preview_excerpt"],
                "seller_alias": l["seller_alias"],
                "purchase_count": l["purchase_count"],
                "status": l["status"],
            }
            for l in listings
        ]

    async def get_market_listing(self, listing_id: str, current_user: Users) -> dict:
        """Get detailed market listing."""
        listing = await self._trade.get_listing(listing_id)
        if not listing:
            raise ServiceError(404, "Listing not found")

        return listing

    async def purchase_listing(self, listing_id: str, buyer: Users) -> dict:
        """Purchase a listing."""
        result = await self._trade.purchase(listing_id, buyer)

        order = result.get("order", {})

        return {
            "order_id": order.get("order_id"),
            "listing_id": order.get("listing_id"),
            "asset_title": order.get("asset_title"),
            "seller_alias": order.get("seller_alias"),
            "price_credits": order.get("price_credits"),
            "platform_fee": order.get("platform_fee"),
            "seller_income": order.get("seller_income"),
            "purchased_at": order.get("purchased_at"),
            "delivery_scope": (await self.get_privacy_policy("", buyer))["buyer_visibility"]["post_purchase"],
        }

    async def list_orders(self, user: Users) -> List[dict]:
        """List user's purchase orders."""
        holdings = await self._trade.get_holdings(user.id)

        return [
            {
                "order_id": h["order_id"],
                "listing_id": h["listing_id"],
                "asset_title": h["asset_title"],
                "seller_alias": h["seller_alias"],
                "purchased_at": h["purchased_at"],
            }
            for h in holdings
        ]

    async def get_order_delivery(self, order_id: str, user: Users) -> dict:
        """Get order delivery content."""
        holdings = await self._trade.get_holdings(user.id)

        holding = next((h for h in holdings if h["order_id"] == order_id), None)
        if not holding:
            raise ServiceError(404, "Order not found")

        content = await self._trade.get_purchased_content(user.id, holding["listing_id"])

        return {
            "order_id": order_id,
            "listing_id": holding["listing_id"],
            "asset_title": content.get("asset_title", ""),
            "purchased_at": holding["purchased_at"],
            "accessible_fields": (await self.get_privacy_policy("", user))["buyer_visibility"]["post_purchase"],
            "content_markdown": content.get("content", ""),
            "graph_snapshot": content.get("graph_snapshot", {}),
            "usage_terms": [
                "Delivery content is for licensed personal use only.",
                "Seller identity and private source data are not part of delivery scope.",
                "Reselling raw delivery content outside the platform is prohibited."
            ],
        }

    async def get_wallet(self, user: Users) -> dict:
        """Get user's wallet."""
        return await self._trade.get_wallet(user.id)
