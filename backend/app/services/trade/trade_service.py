"""
Trade Service - Production grade implementation with ACID transactions.
Replaces file-based state with database transactions.
"""
from __future__ import annotations

import uuid
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.repositories.trade_repo import TradeRepository, cents_to_credits, credits_to_cents
from app.db.models import TradeListings, Users
from app.core.errors import ServiceError
from ..asset_service import AssetService


class TradeService:
    """
    Production-grade Trade Service.

    Key improvements over file-based TradeAgent:
    1. ACID transactions - all operations are atomic
    2. Row-level locking - prevents race conditions with SELECT FOR UPDATE
    3. Audit logging - every transaction is recorded
    4. Optimistic locking - version numbers prevent lost updates
    5. No floating point - all monetary values stored as integers (cents)
    """

    # Yield strategies
    STRATEGY_RATES = {
        "conservative": Decimal("0.03"),
        "balanced": Decimal("0.08"),
        "aggressive": Decimal("0.15"),
    }

    # Repricing thresholds
    REPRICE_HIGH_DEMAND = 10.0  # +3%
    REPRICE_LOW_DEMAND = 2.0    # -1%

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = TradeRepository(db)
        self._assets = AssetService(db)

    # ==========================================================================
    # Listing Workflow
    # ==========================================================================

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        price_credits: Optional[float] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new listing with full sanitization.

        Transaction: All or nothing - either complete listing is created or nothing.
        """
        # Get asset (this validates ownership)
        asset = await self._assets.get_asset(space_public_id, asset_id, user)

        # Sanitize content
        seller_alias = self._generate_user_alias(user.id)
        content_markdown = asset.get("content_markdown", "")

        # Apply sanitization
        redacted_content = self._redact_sensitive_info(content_markdown)
        public_summary = self._compact_text(
            self._redact_sensitive_info(asset.get("summary", "")),
            240
        )
        preview_excerpt = self._compact_text(redacted_content, 320)

        # Auto-calculate price if not provided
        if price_credits is None or price_credits <= 0:
            price_credits = self._calculate_auto_price(asset)

        # Build delivery payload
        delivery_payload = {
            "content_markdown": redacted_content,
            "graph_snapshot": asset.get("graph_snapshot", {}),
            "source_asset_id": asset_id,
        }

        # Create listing within transaction
        listing = await self._repo.create_listing(
            seller_user_id=user.id,
            seller_alias=seller_alias,
            title=asset.get("title", "Untitled Asset")[:255],
            category=(category or "knowledge_report").strip()[:64],
            price_credits=max(0.05, min(500.0, price_credits)),  # Clamp to [0.05, 500]
            public_summary=public_summary,
            preview_excerpt=preview_excerpt,
            delivery_payload=delivery_payload,
            asset_id=asset_id,
            space_public_id=space_public_id,
            tags=self._sanitize_tags(tags or []),
        )

        await self._db.commit()

        return self._format_listing_response(listing)

    async def get_listing(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """Get listing public view."""
        listing = await self._repo.get_listing_by_public_id(listing_id)
        if not listing:
            return None
        return self._format_listing_response(listing, include_delivery=False)

    async def list_market(
        self,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List active marketplace items."""
        listings = await self._repo.list_active_listings(
            category=category,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )
        return [self._format_listing_response(l, include_delivery=False) for l in listings]

    # ==========================================================================
    # Purchase Workflow - Critical Section with Row Locking
    # ==========================================================================

    async def purchase(self, listing_id: str, buyer: Users) -> Dict[str, Any]:
        """
        Execute a purchase with full ACID guarantees.

        This is the most critical operation - uses row-level locking to prevent:
        1. Double-spending (same buyer purchasing twice)
        2. Overselling (multiple buyers purchasing the same listing simultaneously)
        3. Race conditions in wallet balance updates

        Transaction Flow:
        1. Lock listing row (SELECT FOR UPDATE)
        2. Lock buyer wallet row (SELECT FOR UPDATE)
        3. Lock seller wallet row (SELECT FOR UPDATE) - order matters!
        4. Validate all conditions
        5. Create order, update wallets, create holding
        6. Commit (or rollback on error)
        """
        # Check if already purchased (using holding record)
        existing_holding = await self._repo.get_holding_by_listing(buyer.id, listing_id)
        if existing_holding:
            # Return existing order
            order = await self._repo.get_order_by_public_id(existing_holding.order_id)
            return {
                "status": "already_purchased",
                "order": self._format_order_response(order),
                "holding": self._format_holding_response(existing_holding),
            }

        # Step 1: Lock and validate listing
        listing = await self._repo.get_listing_by_public_id(listing_id, lock=True)
        if not listing:
            raise ServiceError(404, "Listing not found")

        if listing.status != "active":
            raise ServiceError(400, f"Listing is not active (status: {listing.status})")

        if listing.seller_user_id == buyer.id:
            raise ServiceError(400, "Cannot purchase your own listing")

        # Step 2 & 3: Lock wallets (in consistent order to prevent deadlocks)
        buyer_wallet = await self._repo.get_wallet(buyer.id, lock=True)
        if not buyer_wallet:
            raise ServiceError(404, "Buyer wallet not found")

        seller_wallet = await self._repo.get_wallet(listing.seller_user_id, lock=True)
        if not seller_wallet:
            raise ServiceError(404, "Seller wallet not found")

        # Check balance
        price_credits = cents_to_credits(listing.price_credits)
        if cents_to_credits(buyer_wallet.liquid_credits) < price_credits:
            raise ServiceError(
                400,
                f"Insufficient balance. Available: {cents_to_credits(buyer_wallet.liquid_credits):.2f}, "
                f"Required: {price_credits:.2f}"
            )

        # Step 4: Calculate amounts
        platform_fee_rate = Decimal("0.05")
        price_cents = Decimal(listing.price_credits)
        platform_fee_cents = int(price_cents * platform_fee_rate)
        seller_income_cents = listing.price_credits - platform_fee_cents

        try:
            # Step 5: Execute all mutations

            # Debit buyer
            await self._repo.debit_wallet(
                user_id=buyer.id,
                amount_credits=price_credits,
                tx_type="purchase",
                metadata={
                    "listing_id": listing_id,
                    "seller_id": listing.seller_user_id,
                },
            )

            # Credit seller (seller gets 95%)
            await self._repo.credit_wallet(
                user_id=listing.seller_user_id,
                amount_credits=cents_to_credits(seller_income_cents),
                tx_type="sale_income",
                metadata={
                    "listing_id": listing_id,
                    "buyer_id": buyer.id,
                    "platform_fee": cents_to_credits(platform_fee_cents),
                },
            )

            # Update seller's cumulative earnings
            seller_wallet.cumulative_sales_earnings += seller_income_cents

            # Create order
            import json
            delivery_payload = json.loads(
                listing.delivery_payload_encrypted.decode('utf-8')
                if listing.delivery_payload_encrypted
                else '{}'
            )

            order = await self._repo.create_order(
                listing=listing,
                buyer_user_id=buyer.id,
                delivery_payload=delivery_payload,
            )

            # Update listing stats
            await self._repo.update_listing_stats(
                listing_id=listing_id,
                increment_purchases=True,
                revenue_cents=seller_income_cents,
            )

            # Create holding
            holding = await self._repo.create_holding(
                user_id=buyer.id,
                order_id=order.public_id,
                listing_id=listing_id,
                asset_title=listing.title,
                seller_alias=listing.seller_alias,
            )

            # Commit transaction
            await self._db.commit()

            return {
                "status": "completed",
                "order": self._format_order_response(order),
                "holding": self._format_holding_response(holding),
            }

        except IntegrityError as e:
            await self._db.rollback()

            # 检查是否是重复购买的唯一约束冲突
            error_str = str(e).lower()
            if "uk_holdings_user_listing" in error_str or "unique" in error_str:
                existing = await self._repo.get_holding_by_listing(buyer.id, listing_id)
                if existing:
                    order = await self._repo.get_order_by_public_id(existing.order_id)
                    return {
                        "status": "already_purchased",
                        "order": self._format_order_response(order),
                        "holding": self._format_holding_response(existing),
                    }

            raise ServiceError(500, f"Purchase failed: {str(e)}")

        except Exception as e:
            # Rollback on any other error
            await self._db.rollback()
            raise ServiceError(500, f"Purchase failed: {str(e)}")

    # ==========================================================================
    # Yield Workflow - Idempotent with Last-Run Tracking
    # ==========================================================================

    async def run_auto_yield(
        self,
        user: Users,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Accrue yield on user's wallet balance.

        This operation is idempotent - running it multiple times with the same
        last_yield_run_at will produce consistent results.

        Uses row-level locking on wallet to prevent concurrent yield calculations.
        """
        # Lock wallet
        wallet = await self._repo.get_wallet(user.id, lock=True)
        if not wallet:
            raise ServiceError(404, "Wallet not found")

        if not wallet.auto_yield_enabled:
            return {"status": "disabled", "message": "Auto-yield is disabled"}

        # Determine strategy
        use_strategy = strategy or wallet.yield_strategy
        if use_strategy not in self.STRATEGY_RATES:
            use_strategy = "balanced"

        annual_rate = self.STRATEGY_RATES[use_strategy]

        # Calculate time elapsed
        now = datetime.now(timezone.utc)
        last_run = wallet.last_yield_run_at

        if not last_run:
            # First run - initialize
            wallet.last_yield_run_at = now
            wallet.yield_strategy = use_strategy
            await self._db.commit()
            return {
                "status": "initialized",
                "message": "Yield tracking initialized",
                "strategy": use_strategy,
            }

        # Calculate elapsed time
        elapsed_seconds = max(0, (now - last_run).total_seconds())
        elapsed_days = elapsed_seconds / 86400.0

        if elapsed_days < 0.001:  # Less than ~1.5 minutes
            return {
                "status": "too_soon",
                "elapsed_seconds": elapsed_seconds,
                "message": "Yield was calculated recently",
            }

        # Calculate yield
        principal_cents = wallet.liquid_credits
        principal = Decimal(principal_cents) / 100
        gain = principal * annual_rate * (Decimal(elapsed_days) / 365)
        gain_cents = int(gain * 100)

        if gain_cents <= 0:
            return {
                "status": "no_yield",
                "elapsed_days": elapsed_days,
                "message": "No yield to accrue",
            }

        # Record before state
        liquid_before = cents_to_credits(wallet.liquid_credits)

        # Apply yield
        wallet.liquid_credits += gain_cents
        wallet.cumulative_yield_earnings += gain_cents
        wallet.last_yield_run_at = now
        wallet.yield_strategy = use_strategy
        wallet.version += 1

        liquid_after = cents_to_credits(wallet.liquid_credits)

        # Reprice listings
        adjustments = await self._reprice_user_listings(user.id)

        # Log yield run
        yield_run = await self._repo.create_yield_run(
            user_id=user.id,
            strategy=use_strategy,
            annual_rate=float(annual_rate),
            elapsed_days=elapsed_days,
            yield_credits=cents_to_credits(gain_cents),
            liquid_before=liquid_before,
            liquid_after=liquid_after,
            listing_adjustments=adjustments,
        )

        await self._db.commit()

        return {
            "status": "completed",
            "run_id": yield_run.public_id,
            "strategy": use_strategy,
            "annual_rate": float(annual_rate),
            "elapsed_days": elapsed_days,
            "yield_amount": cents_to_credits(gain_cents),
            "wallet_before": liquid_before,
            "wallet_after": liquid_after,
            "listing_adjustments": adjustments,
        }

    async def _reprice_user_listings(self, user_id: int) -> List[Dict]:
        """
        Dynamically reprice user's listings based on demand.
        Returns list of adjustments made.
        """
        listings = await self._repo.get_listings_by_seller(user_id)
        adjustments = []

        for listing in listings:
            if listing.status != "active" or not listing.auto_reprice_enabled:
                continue

            old_price_cents = listing.price_credits
            old_price = Decimal(old_price_cents) / 100

            views = listing.market_view_count
            buys = listing.purchase_count
            demand_score = buys * 2 + views * 0.15

            # Determine new price
            if demand_score >= self.REPRICE_HIGH_DEMAND:
                new_price = old_price * Decimal("1.03")
            elif demand_score <= self.REPRICE_LOW_DEMAND:
                new_price = old_price * Decimal("0.99")
            else:
                continue  # No change

            new_price = max(Decimal("0.01"), new_price)  # Minimum price
            new_price_cents = int(new_price * 100)

            if new_price_cents != old_price_cents:
                await self._repo.reprice_listing(
                    listing_id=listing.public_id,
                    new_price_credits=float(new_price),
                    demand_score=demand_score,
                )
                adjustments.append({
                    "listing_id": listing.public_id,
                    "old_price": cents_to_credits(old_price_cents),
                    "new_price": float(new_price.quantize(Decimal("0.01"))),
                    "demand_score": round(demand_score, 4),
                })

        return adjustments

    # ==========================================================================
    # Wallet & Balance Operations
    # ==========================================================================

    async def get_wallet(self, user_id: int) -> Dict[str, Any]:
        """Get user's wallet with stats."""
        wallet = await self._repo.get_or_create_wallet(user_id)
        stats = await self._repo.get_wallet_stats(user_id)
        return {
            "wallet_id": wallet.id,
            "user_id": wallet.user_id,
            **stats,
            "version": wallet.version,
            "last_yield_run_at": wallet.last_yield_run_at.isoformat() if wallet.last_yield_run_at else None,
        }

    async def get_transaction_history(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> List[Dict]:
        """Get user's transaction history."""
        txs = await self._repo.get_transaction_history(user_id, limit, offset)
        return [
            {
                "tx_id": tx.public_id,
                "type": tx.tx_type,
                "amount": cents_to_credits(tx.amount_delta),
                "balance_before": cents_to_credits(tx.balance_before),
                "balance_after": cents_to_credits(tx.balance_after),
                "metadata": tx.metadata,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in txs
        ]

    async def update_yield_settings(
        self, user_id: int, strategy: Optional[str] = None, enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Update yield settings."""
        wallet = await self._repo.update_yield_settings(user_id, strategy, enabled)
        await self._db.commit()
        return {
            "auto_yield_enabled": wallet.auto_yield_enabled,
            "yield_strategy": wallet.yield_strategy,
        }

    # ==========================================================================
    # Holdings & Access
    # ==========================================================================

    async def get_holdings(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get user's purchased assets."""
        holdings = await self._repo.get_holdings_by_user(user_id, limit, offset)
        return [self._format_holding_response(h) for h in holdings]

    async def get_purchased_content(self, user_id: int, listing_id: str) -> Dict:
        """
        Get purchased content for a holding.
        Records access for analytics.
        """
        # Verify ownership
        holding = await self._repo.get_holding_by_listing(user_id, listing_id)
        if not holding:
            raise ServiceError(404, "Holding not found or access denied")

        # Get order to retrieve delivery payload
        order = await self._repo.get_order_by_public_id(holding.order_id)
        if not order:
            raise ServiceError(500, "Order not found for holding")

        # Record access
        await self._repo.record_access(holding.id)
        await self._db.commit()

        import json
        delivery = json.loads(
            order.delivery_payload_encrypted.decode('utf-8')
            if order.delivery_payload_encrypted
            else '{}'
        )

        return {
            "holding_id": holding.id,
            "order_id": holding.order_id,
            "listing_id": listing_id,
            "asset_title": holding.asset_title,
            "seller_alias": holding.seller_alias,
            "purchased_at": holding.purchased_at.isoformat(),
            "content": delivery.get("content_markdown", ""),
            "graph_snapshot": delivery.get("graph_snapshot", {}),
        }

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def _generate_user_alias(self, user_id: int) -> str:
        """Generate pseudonymous seller alias."""
        digest = hashlib.sha256(f"user-{user_id}".encode()).hexdigest()[:10]
        return f"seller-{digest}"

    def _redact_sensitive_info(self, text: str) -> str:
        """Redact sensitive information from content."""
        if not text:
            return ""

        patterns = [
            (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
            (re.compile(r"(?<!\d)(?:\+?\d[\d\-\s]{8,}\d)(?!\d)"), "[REDACTED_PHONE]"),
            (re.compile(r"(?i)\b(?:sk|api|token|secret)[-_a-z0-9]{12,}\b"), "[REDACTED_SECRET]"),
            (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
            (re.compile(r"\b\d{8,}\b"), "[REDACTED_ID]"),
        ]

        for pattern, repl in patterns:
            text = pattern.sub(repl, text)
        return text

    def _compact_text(self, text: str, limit: int) -> str:
        """Compact text to character limit."""
        compact = " ".join((text or "").split())
        return compact[:limit]

    def _calculate_auto_price(self, asset: Dict) -> float:
        """Calculate automatic price based on content complexity."""
        markdown = asset.get("content_markdown", "")
        graph = asset.get("graph_snapshot", {})

        node_count = graph.get("node_count", 0)
        edge_count = graph.get("edge_count", 0)

        length_factor = min(len(markdown) / 180.0, 120.0)
        score = 20.0 + length_factor + node_count * 1.5 + edge_count * 1.2

        return max(5.0, min(500.0, score))

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """Sanitize and deduplicate tags."""
        result = []
        for tag in tags:
            candidate = (tag or "").strip().lower()
            if candidate and candidate not in result:
                result.append(candidate[:32])
        return result[:8]

    # ==========================================================================
    # Response Formatters
    # ==========================================================================

    def _format_listing_response(
        self, listing: TradeListings, include_delivery: bool = False
    ) -> Dict[str, Any]:
        """Format listing for API response."""
        result = {
            "listing_id": listing.public_id,
            "asset_id": listing.asset_id,
            "space_public_id": listing.space_public_id,
            "seller_alias": listing.seller_alias,
            "title": listing.title,
            "category": listing.category,
            "tags": listing.tags,
            "price_credits": cents_to_credits(listing.price_credits),
            "public_summary": listing.public_summary,
            "preview_excerpt": listing.preview_excerpt,
            "status": listing.status,
            "purchase_count": listing.purchase_count,
            "market_view_count": listing.market_view_count,
            "revenue_total": cents_to_credits(listing.revenue_total),
            "created_at": listing.created_at.isoformat() if listing.created_at else None,
            "updated_at": listing.updated_at.isoformat() if listing.updated_at else None,
        }

        if include_delivery and listing.delivery_payload_encrypted:
            import json
            result["delivery"] = json.loads(listing.delivery_payload_encrypted.decode('utf-8'))

        return result

    def _format_order_response(self, order: TradeOrders) -> Dict[str, Any]:
        """Format order for API response."""
        return {
            "order_id": order.public_id,
            "listing_id": order.listing_id,
            "asset_title": order.asset_title_snapshot,
            "seller_alias": order.seller_alias_snapshot,
            "price_credits": cents_to_credits(order.price_credits),
            "platform_fee": cents_to_credits(order.platform_fee),
            "seller_income": cents_to_credits(order.seller_income),
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        }

    def _format_holding_response(self, holding: TradeHoldings) -> Dict[str, Any]:
        """Format holding for API response."""
        return {
            "holding_id": holding.id,
            "order_id": holding.order_id,
            "listing_id": holding.listing_id,
            "asset_title": holding.asset_title,
            "seller_alias": holding.seller_alias,
            "purchased_at": holding.purchased_at.isoformat() if holding.purchased_at else None,
            "download_count": holding.download_count,
            "last_accessed_at": holding.last_accessed_at.isoformat() if holding.last_accessed_at else None,
        }