"""
Trade Repository - Production grade with ACID transactions and row-level locking.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert

from app.db.models import (
    TradeListings, TradeOrders, TradeWallets, TradeHoldings,
    TradeYieldRuns, TradeTransactionLog,
    DataRightsTransactions, ComputationMethod, DataRightsStatus,
)
from app.core.errors import ServiceError


# Currency conversion utilities (cents <-> credits)
def credits_to_cents(credits: float) -> int:
    """Convert credits to integer cents (avoid floating point errors)."""
    return int(Decimal(str(credits)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)


def cents_to_credits(cents: int) -> float:
    """Convert cents to credits."""
    return round(cents / 100, 2)


class TradeRepository:
    """
    Production-grade repository for Trade system.
    All methods use proper transaction handling and row-level locking.
    """

    PLATFORM_FEE_RATE = Decimal('0.05')  # 5%

    def __init__(self, db: AsyncSession):
        self._db = db

    # ==========================================================================
    # Listing Operations
    # ==========================================================================

    async def create_listing(
        self,
        seller_user_id: int,
        seller_alias: str,
        title: str,
        category: str,
        price_credits: float,
        public_summary: str,
        preview_excerpt: str,
        delivery_payload: dict,
        asset_id: Optional[str] = None,
        space_public_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        rights_template: Optional[Dict[str, Any]] = None,
    ) -> TradeListings:
        """Create a new listing."""
        # Encrypt delivery payload (simplified - use proper encryption in production)
        import json
        delivery_bytes = json.dumps(delivery_payload).encode('utf-8')

        listing = TradeListings(
            public_id=str(uuid.uuid4()).replace('-', '')[:32],
            seller_user_id=seller_user_id,
            seller_alias=seller_alias,
            asset_id=asset_id,
            space_public_id=space_public_id,
            title=title[:255],
            category=category[:64],
            tags=tags or [],
            price_credits=credits_to_cents(price_credits),
            public_summary=public_summary,
            preview_excerpt=preview_excerpt,
            delivery_payload_encrypted=delivery_bytes,
            rights_template=rights_template or {},
            status="active",
        )

        self._db.add(listing)
        await self._db.flush()
        await self._db.refresh(listing)
        return listing

    async def get_listing_by_public_id(
        self, public_id: str, lock: bool = False
    ) -> Optional[TradeListings]:
        """Get listing by public ID, optionally with row-level lock."""
        stmt = select(TradeListings).where(TradeListings.public_id == public_id)

        if lock:
            # FOR UPDATE lock prevents concurrent modifications
            stmt = stmt.with_for_update()

        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_listings(
        self,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[TradeListings]:
        """List active listings with optional filters."""
        stmt = (
            select(TradeListings)
            .where(TradeListings.status == "active")
            .order_by(TradeListings.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        if category:
            stmt = stmt.where(TradeListings.category == category)
        if min_price is not None:
            stmt = stmt.where(TradeListings.price_credits >= credits_to_cents(min_price))
        if max_price is not None:
            stmt = stmt.where(TradeListings.price_credits <= credits_to_cents(max_price))

        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def update_listing_stats(
        self, listing_id: str, increment_purchases: bool = True, revenue_cents: int = 0
    ) -> None:
        """Update listing statistics atomically."""
        updates = {
            "revenue_total": TradeListings.revenue_total + revenue_cents,
            "updated_at": datetime.now(timezone.utc),
        }

        if increment_purchases:
            updates["purchase_count"] = TradeListings.purchase_count + 1

        stmt = (
            update(TradeListings)
            .where(TradeListings.public_id == listing_id)
            .values(**updates)
        )
        await self._db.execute(stmt)

    async def reprice_listing(
        self, listing_id: str, new_price_credits: float, demand_score: float
    ) -> bool:
        """Update listing price and demand score."""
        stmt = (
            update(TradeListings)
            .where(TradeListings.public_id == listing_id)
            .values(
                price_credits=credits_to_cents(new_price_credits),
                demand_score=demand_score,
                last_reprice_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await self._db.execute(stmt)
        return result.rowcount > 0

    async def get_listings_by_seller(self, seller_user_id: int) -> List[TradeListings]:
        """Get all listings by a seller."""
        stmt = (
            select(TradeListings)
            .where(TradeListings.seller_user_id == seller_user_id)
            .order_by(TradeListings.created_at.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ==========================================================================
    # Wallet Operations - with pessimistic locking (SELECT FOR UPDATE)
    # ==========================================================================

    async def get_wallet(
        self, user_id: int, lock: bool = False
    ) -> Optional[TradeWallets]:
        """Get user wallet, optionally with row-level lock."""
        stmt = select(TradeWallets).where(TradeWallets.user_id == user_id)

        if lock:
            stmt = stmt.with_for_update()

        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_wallet(self, user_id: int, initial_credits: float = 1000.0) -> TradeWallets:
        """Create a new wallet for user."""
        wallet = TradeWallets(
            user_id=user_id,
            liquid_credits=credits_to_cents(initial_credits),
        )
        self._db.add(wallet)
        await self._db.flush()
        await self._db.refresh(wallet)
        return wallet

    async def get_or_create_wallet(
        self, user_id: int, initial_credits: float = 1000.0
    ) -> TradeWallets:
        """获取或创建钱包 - 使用 upsert 防止竞态条件"""
        # 首先尝试获取
        wallet = await self.get_wallet(user_id, lock=False)
        if wallet:
            return wallet

        # 使用 PostgreSQL upsert 安全创建
        stmt = (
            insert(TradeWallets)
            .values(
                user_id=user_id,
                liquid_credits=credits_to_cents(initial_credits),
                version=1,
            )
            .on_conflict_do_nothing(
                index_elements=['user_id']  # 使用唯一索引
            )
            .returning(TradeWallets)
        )

        result = await self._db.execute(stmt)
        created_wallet = result.scalar_one_or_none()

        if created_wallet:
            await self._db.commit()
            return created_wallet

        # 其他事务创建了钱包，重新获取
        await self._db.rollback()
        wallet = await self.get_wallet(user_id, lock=False)
        if not wallet:
            raise ServiceError(500, "Failed to create or retrieve wallet")
        return wallet

    async def credit_wallet(
        self,
        user_id: int,
        amount_credits: float,
        tx_type: str,
        metadata: Optional[Dict] = None,
        ip_address: Optional[str] = None,
    ) -> TradeWallets:
        """
        Add credits to wallet.
        Must be called within a transaction with wallet locked.
        """
        # Get wallet with lock
        wallet = await self.get_wallet(user_id, lock=True)
        if not wallet:
            raise ServiceError(404, f"Wallet not found for user {user_id}")

        amount_cents = credits_to_cents(amount_credits)
        balance_before = wallet.liquid_credits
        balance_after = balance_before + amount_cents

        # Update wallet
        wallet.liquid_credits = balance_after
        wallet.version += 1  # Optimistic lock version bump
        wallet.updated_at = datetime.now(timezone.utc)

        # Create transaction log
        tx_log = TradeTransactionLog(
            public_id=str(uuid.uuid4()).replace('-', '')[:32],
            tx_type=tx_type,
            user_id=user_id,
            amount_delta=amount_cents,
            balance_before=balance_before,
            balance_after=balance_after,
            metadata=metadata or {},
            ip_address=ip_address,
        )
        self._db.add(tx_log)

        await self._db.flush()
        return wallet

    async def debit_wallet(
        self,
        user_id: int,
        amount_credits: float,
        tx_type: str,
        metadata: Optional[Dict] = None,
        ip_address: Optional[str] = None,
    ) -> TradeWallets:
        """
        Deduct credits from wallet.
        Must be called within a transaction with wallet locked.
        Raises ServiceError if insufficient balance.
        """
        # Get wallet with lock
        wallet = await self.get_wallet(user_id, lock=True)
        if not wallet:
            raise ServiceError(404, f"Wallet not found for user {user_id}")

        amount_cents = credits_to_cents(amount_credits)
        balance_before = wallet.liquid_credits

        if balance_before < amount_cents:
            raise ServiceError(
                400,
                f"Insufficient balance: {cents_to_credits(balance_before):.2f} credits available, "
                f"{amount_credits:.2f} credits required"
            )

        balance_after = balance_before - amount_cents

        # Update wallet
        wallet.liquid_credits = balance_after
        wallet.total_spent += amount_cents
        wallet.version += 1
        wallet.updated_at = datetime.now(timezone.utc)

        # Create transaction log
        tx_log = TradeTransactionLog(
            public_id=str(uuid.uuid4()).replace('-', '')[:32],
            tx_type=tx_type,
            user_id=user_id,
            amount_delta=-amount_cents,
            balance_before=balance_before,
            balance_after=balance_after,
            metadata=metadata or {},
            ip_address=ip_address,
        )
        self._db.add(tx_log)

        await self._db.flush()
        return wallet

    async def transfer_credits(
        self,
        from_user_id: int,
        to_user_id: int,
        amount_credits: float,
        tx_type: str,
        metadata: Optional[Dict] = None,
    ) -> tuple[TradeWallets, TradeWallets]:
        """
        Transfer credits between wallets atomically.
        Uses row-level locks to prevent race conditions.
        """
        # Lock both wallets in consistent order to prevent deadlocks
        # Always lock by smaller user_id first
        user_ids = sorted([from_user_id, to_user_id])

        wallets = []
        for uid in user_ids:
            wallet = await self.get_wallet(uid, lock=True)
            if not wallet:
                raise ServiceError(404, f"Wallet not found for user {uid}")
            wallets.append(wallet)

        # Find the wallets in our result
        from_wallet = next(w for w in wallets if w.user_id == from_user_id)
        to_wallet = next(w for w in wallets if w.user_id == to_user_id)

        amount_cents = credits_to_cents(amount_credits)

        # Check balance
        if from_wallet.liquid_credits < amount_cents:
            raise ServiceError(
                400,
                f"Insufficient balance: {cents_to_credits(from_wallet.liquid_credits):.2f} credits available"
            )

        # Perform transfer
        from_balance_before = from_wallet.liquid_credits
        to_balance_before = to_wallet.liquid_credits

        from_wallet.liquid_credits -= amount_cents
        to_wallet.liquid_credits += amount_cents

        from_wallet.version += 1
        to_wallet.version += 1

        from_wallet.updated_at = datetime.now(timezone.utc)
        to_wallet.updated_at = datetime.now(timezone.utc)

        # Create transaction logs for both sides
        tx_id = str(uuid.uuid4()).replace('-', '')[:32]

        from_tx = TradeTransactionLog(
            public_id=tx_id + "_from",
            tx_type=tx_type,
            user_id=from_user_id,
            amount_delta=-amount_cents,
            balance_before=from_balance_before,
            balance_after=from_wallet.liquid_credits,
            metadata={**(metadata or {}), "counterparty": to_user_id, "direction": "out"},
        )

        to_tx = TradeTransactionLog(
            public_id=tx_id + "_to",
            tx_type=tx_type,
            user_id=to_user_id,
            amount_delta=amount_cents,
            balance_before=to_balance_before,
            balance_after=to_wallet.liquid_credits,
            metadata={**(metadata or {}), "counterparty": from_user_id, "direction": "in"},
        )

        self._db.add(from_tx)
        self._db.add(to_tx)

        await self._db.flush()
        return from_wallet, to_wallet

    # ==========================================================================
    # Order Operations
    # ==========================================================================

    async def create_order(
        self,
        listing: TradeListings,
        buyer_user_id: int,
        delivery_payload: dict,
        override_price_cents: Optional[int] = None,
    ) -> TradeOrders:
        """
        Create a purchase order with proper price calculation.
        Called within a transaction after wallet checks.
        """
        import json

        price_cents = override_price_cents if override_price_cents is not None else listing.price_credits
        platform_fee_cents = int(Decimal(price_cents) * self.PLATFORM_FEE_RATE)
        seller_income_cents = price_cents - platform_fee_cents

        order = TradeOrders(
            public_id=str(uuid.uuid4()).replace('-', '')[:32],
            listing_id=listing.public_id,
            buyer_user_id=buyer_user_id,
            seller_user_id=listing.seller_user_id,
            asset_title_snapshot=listing.title,
            seller_alias_snapshot=listing.seller_alias,
            price_credits=price_cents,
            platform_fee=platform_fee_cents,
            seller_income=seller_income_cents,
            delivery_payload_encrypted=json.dumps(delivery_payload).encode('utf-8'),
            status="completed",
            completed_at=datetime.now(timezone.utc),
        )

        self._db.add(order)
        await self._db.flush()
        await self._db.refresh(order)
        return order

    async def get_order_by_public_id(self, public_id: str) -> Optional[TradeOrders]:
        """Get order by public ID."""
        stmt = select(TradeOrders).where(TradeOrders.public_id == public_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_orders_by_buyer(
        self, buyer_user_id: int, limit: int = 50, offset: int = 0
    ) -> List[TradeOrders]:
        """Get orders by buyer."""
        stmt = (
            select(TradeOrders)
            .where(TradeOrders.buyer_user_id == buyer_user_id)
            .order_by(TradeOrders.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ==========================================================================
    # Holding Operations
    # ==========================================================================

    async def create_holding(
        self,
        user_id: int,
        order_id: str,
        listing_id: str,
        asset_title: str,
        seller_alias: str,
    ) -> TradeHoldings:
        """Create a holding record after purchase."""
        holding = TradeHoldings(
            user_id=user_id,
            order_id=order_id,
            listing_id=listing_id,
            asset_title=asset_title,
            seller_alias=seller_alias,
        )
        self._db.add(holding)
        await self._db.flush()
        await self._db.refresh(holding)
        return holding

    async def get_holdings_by_user(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[TradeHoldings]:
        """Get user's holdings."""
        stmt = (
            select(TradeHoldings)
            .where(TradeHoldings.user_id == user_id)
            .order_by(TradeHoldings.purchased_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_holding_by_listing(
        self, user_id: int, listing_id: str
    ) -> Optional[TradeHoldings]:
        """Check if user owns a specific listing."""
        stmt = (
            select(TradeHoldings)
            .where(
                TradeHoldings.user_id == user_id,
                TradeHoldings.listing_id == listing_id
            )
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def record_access(self, holding_id: int) -> None:
        """Record access to a holding."""
        stmt = (
            update(TradeHoldings)
            .where(TradeHoldings.id == holding_id)
            .values(
                download_count=TradeHoldings.download_count + 1,
                last_accessed_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)

    async def create_rights_transaction(
        self,
        data_asset_id: str,
        owner_id: int,
        buyer_id: int,
        listing_id: str,
        order_id: str,
        rights_types: List[str],
        usage_scope: Dict[str, Any],
        restrictions: List[str],
        agreed_price: Optional[float] = None,
        computation_method: ComputationMethod = ComputationMethod.RAW_DATA,
        anonymization_level: int = 1,
        validity_days: int = 365,
    ) -> DataRightsTransactions:
        """Create a DataRightsTransaction after purchase."""
        now = datetime.now(timezone.utc)
        tx = DataRightsTransactions(
            transaction_id=str(uuid.uuid4()).replace('-', '')[:32],
            listing_id=listing_id,
            order_id=order_id,
            data_asset_id=data_asset_id,
            owner_id=owner_id,
            buyer_id=buyer_id,
            rights_types=rights_types,
            usage_scope=usage_scope,
            restrictions=restrictions,
            computation_method=computation_method,
            anonymization_level=anonymization_level,
            valid_from=now,
            valid_until=datetime.fromtimestamp(now.timestamp() + validity_days * 86400, tz=timezone.utc),
            agreed_price=agreed_price,
            status=DataRightsStatus.ACTIVE,
            settlement_time=now,
        )
        self._db.add(tx)
        await self._db.flush()
        await self._db.refresh(tx)
        return tx

    async def list_active_rights_transactions(
        self,
        buyer_id: int,
        data_asset_id: str,
    ) -> List[DataRightsTransactions]:
        """List all active rights transactions for a buyer and asset."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(DataRightsTransactions)
            .where(
                DataRightsTransactions.buyer_id == buyer_id,
                DataRightsTransactions.data_asset_id == data_asset_id,
                DataRightsTransactions.status == DataRightsStatus.ACTIVE,
                DataRightsTransactions.valid_from <= now,
                DataRightsTransactions.valid_until >= now,
            )
            .order_by(DataRightsTransactions.created_at.desc())
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def check_rights(
        self,
        buyer_id: int,
        data_asset_id: str,
        required_right: str,
    ) -> bool:
        """Check if buyer has a specific active right on an asset.

        Searches across ALL active rights transactions (not just the latest),
        because a buyer may hold multiple rights packages for the same asset.
        """
        transactions = await self.list_active_rights_transactions(
            buyer_id, data_asset_id
        )
        if not transactions:
            return False
        return any(
            required_right in (tx.rights_types or [])
            for tx in transactions
        )

    # ==========================================================================
    # Yield Operations
    # ==========================================================================

    async def create_yield_run(
        self,
        user_id: int,
        strategy: str,
        annual_rate: float,
        elapsed_days: float,
        yield_credits: float,
        liquid_before: float,
        liquid_after: float,
        listing_adjustments: List[Dict],
    ) -> TradeYieldRuns:
        """Log a yield accrual run."""
        run = TradeYieldRuns(
            public_id=str(uuid.uuid4()).replace('-', '')[:32],
            user_id=user_id,
            strategy=strategy,
            annual_rate=annual_rate,
            elapsed_days=elapsed_days,
            yield_amount=credits_to_cents(yield_credits),
            liquid_credits_before=credits_to_cents(liquid_before),
            liquid_credits_after=credits_to_cents(liquid_after),
            listing_adjustments=listing_adjustments,
        )
        self._db.add(run)
        await self._db.flush()
        await self._db.refresh(run)
        return run

    async def update_yield_settings(
        self, user_id: int, strategy: Optional[str] = None, enabled: Optional[bool] = None
    ) -> TradeWallets:
        """Update user's yield settings."""
        wallet = await self.get_wallet(user_id, lock=True)
        if not wallet:
            raise ServiceError(404, "Wallet not found")

        if strategy:
            wallet.yield_strategy = strategy
        if enabled is not None:
            wallet.auto_yield_enabled = enabled

        wallet.updated_at = datetime.now(timezone.utc)
        await self._db.flush()
        return wallet

    # ==========================================================================
    # Transaction Log Queries
    # ==========================================================================

    async def get_transaction_history(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> List[TradeTransactionLog]:
        """Get user's transaction history."""
        stmt = (
            select(TradeTransactionLog)
            .where(TradeTransactionLog.user_id == user_id)
            .order_by(TradeTransactionLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_wallet_stats(self, user_id: int) -> Dict[str, Any]:
        """Get comprehensive wallet statistics."""
        wallet = await self.get_wallet(user_id)
        if not wallet:
            raise ServiceError(404, "Wallet not found")

        # Count orders
        orders_stmt = select(func.count()).where(
            TradeOrders.buyer_user_id == user_id,
            TradeOrders.status == "completed"
        )
        orders_result = await self._db.execute(orders_stmt)
        purchase_count = orders_result.scalar() or 0

        # Count sales
        sales_stmt = select(func.count()).where(
            TradeOrders.seller_user_id == user_id,
            TradeOrders.status == "completed"
        )
        sales_result = await self._db.execute(sales_stmt)
        sale_count = sales_result.scalar() or 0

        # Total yield earned
        yield_stmt = select(func.sum(TradeYieldRuns.yield_amount)).where(
            TradeYieldRuns.user_id == user_id
        )
        yield_result = await self._db.execute(yield_stmt)
        total_yield = yield_result.scalar() or 0

        return {
            "liquid_credits": cents_to_credits(wallet.liquid_credits),
            "cumulative_sales_earnings": cents_to_credits(wallet.cumulative_sales_earnings),
            "cumulative_yield_earnings": cents_to_credits(wallet.cumulative_yield_earnings),
            "total_spent": cents_to_credits(wallet.total_spent),
            "auto_yield_enabled": wallet.auto_yield_enabled,
            "yield_strategy": wallet.yield_strategy,
            "purchase_count": purchase_count,
            "sale_count": sale_count,
            "total_yield_earned": cents_to_credits(total_yield),
        }

