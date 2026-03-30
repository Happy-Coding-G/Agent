"""
Migrate Trade data from JSON files to PostgreSQL database.

Usage:
    cd backend
    python -m scripts.migrate_trade_data

Prerequisites:
    1. Run Alembic migration to create trade tables:
       alembic upgrade add_trade_tables
    2. Ensure database is accessible
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.db.models import (
    TradeListings, TradeOrders, TradeWallets, TradeHoldings,
    TradeYieldRuns, TradeTransactionLog
)
from app.repositories.trade_repo import credits_to_cents


STATE_DIR = Path(__file__).parent.parent / "state"


def load_json_file(path: Path) -> Any:
    """Load JSON file if exists."""
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}")
        return None


def parse_iso_datetime(iso_str: str) -> datetime:
    """Parse ISO datetime string."""
    if not iso_str:
        return datetime.now(timezone.utc)
    try:
        # Handle various ISO formats
        if iso_str.endswith('Z'):
            iso_str = iso_str[:-1] + '+00:00'
        return datetime.fromisoformat(iso_str)
    except:
        return datetime.now(timezone.utc)


async def migrate_market(session: AsyncSession) -> int:
    """Migrate market listings."""
    market_path = STATE_DIR / "trade_market" / "global.json"
    listings = load_json_file(market_path)

    if not listings:
        print("No market listings to migrate")
        return 0

    count = 0
    for item in listings:
        try:
            listing = TradeListings(
                public_id=item.get("listing_id", ""),
                asset_id=item.get("asset_id"),
                space_public_id=item.get("space_public_id"),
                seller_user_id=item.get("seller_user_id", 0),
                seller_alias=item.get("seller_alias", ""),
                title=item.get("title", "Untitled")[:255],
                category=item.get("category", "knowledge_report")[:64],
                tags=item.get("tags", []),
                price_credits=credits_to_cents(item.get("price_credits", 0)),
                public_summary=item.get("public_summary", ""),
                preview_excerpt=item.get("preview_excerpt", ""),
                delivery_payload_encrypted=json.dumps(
                    item.get("delivery_payload", {})
                ).encode('utf-8') if item.get("delivery_payload") else None,
                status=item.get("status", "active"),
                purchase_count=item.get("purchase_count", 0),
                market_view_count=item.get("market_view_count", 0),
                revenue_total=credits_to_cents(item.get("revenue_total", 0)),
                created_at=parse_iso_datetime(item.get("created_at", "")),
                updated_at=parse_iso_datetime(item.get("updated_at", "")),
            )
            session.add(listing)
            count += 1
        except Exception as e:
            print(f"Error migrating listing {item.get('listing_id')}: {e}")

    await session.flush()
    print(f"Migrated {count} market listings")
    return count


async def migrate_wallets(session: AsyncSession) -> int:
    """Migrate user wallets."""
    wallets_dir = STATE_DIR / "trade_wallets"
    if not wallets_dir.exists():
        print("No wallets directory")
        return 0

    count = 0
    for wallet_file in wallets_dir.glob("*.json"):
        user_id = int(wallet_file.stem)
        data = load_json_file(wallet_file)

        if not data:
            continue

        try:
            wallet = TradeWallets(
                user_id=user_id,
                liquid_credits=credits_to_cents(data.get("liquid_credits", 1000)),
                cumulative_sales_earnings=credits_to_cents(
                    data.get("cumulative_sales_earnings", 0)
                ),
                cumulative_yield_earnings=credits_to_cents(
                    data.get("cumulative_yield_earnings", 0)
                ),
                total_spent=credits_to_cents(data.get("total_spent", 0)),
                auto_yield_enabled=data.get("auto_yield_enabled", True),
                yield_strategy=data.get("yield_strategy", "balanced"),
                last_yield_run_at=parse_iso_datetime(
                    data.get("last_yield_run_at", "")
                ) if data.get("last_yield_run_at") else None,
                created_at=parse_iso_datetime(data.get("updated_at", "")),
                updated_at=parse_iso_datetime(data.get("updated_at", "")),
            )
            session.add(wallet)
            count += 1
        except Exception as e:
            print(f"Error migrating wallet for user {user_id}: {e}")

    await session.flush()
    print(f"Migrated {count} wallets")
    return count


async def migrate_orders(session: AsyncSession) -> int:
    """Migrate user orders."""
    orders_dir = STATE_DIR / "trade_orders"
    if not orders_dir.exists():
        print("No orders directory")
        return 0

    count = 0
    for orders_file in orders_dir.glob("*.json"):
        user_id = int(orders_file.stem)
        orders = load_json_file(orders_file)

        if not orders:
            continue

        for item in orders:
            try:
                order = TradeOrders(
                    public_id=item.get("order_id", ""),
                    listing_id=item.get("listing_id", ""),
                    buyer_user_id=user_id,
                    seller_user_id=item.get("seller_user_id", 0),
                    asset_title_snapshot=item.get("asset_title", "")[:255],
                    seller_alias_snapshot=item.get("seller_alias", "")[:64],
                    price_credits=credits_to_cents(item.get("price_credits", 0)),
                    platform_fee=credits_to_cents(item.get("platform_fee", 0)),
                    seller_income=credits_to_cents(item.get("seller_income", 0)),
                    delivery_payload_encrypted=json.dumps(
                        item.get("delivery", {})
                    ).encode('utf-8') if item.get("delivery") else None,
                    status="completed",
                    completed_at=parse_iso_datetime(item.get("purchased_at", "")),
                    created_at=parse_iso_datetime(item.get("purchased_at", "")),
                )
                session.add(order)
                count += 1
            except Exception as e:
                print(f"Error migrating order {item.get('order_id')}: {e}")

    await session.flush()
    print(f"Migrated {count} orders")
    return count


async def migrate_holdings(session: AsyncSession) -> int:
    """Migrate user holdings."""
    holdings_dir = STATE_DIR / "trade_holdings"
    if not holdings_dir.exists():
        print("No holdings directory")
        return 0

    count = 0
    for holdings_file in holdings_dir.glob("*.json"):
        user_id = int(holdings_file.stem)
        holdings = load_json_file(holdings_file)

        if not holdings:
            continue

        for item in holdings:
            try:
                # Get order_id from the order that created this holding
                order_id = item.get("holding_id", "")  # Use holding_id as order_id temporarily

                holding = TradeHoldings(
                    user_id=user_id,
                    order_id=order_id,
                    listing_id=item.get("listing_id", ""),
                    asset_title=item.get("asset_title", "")[:255],
                    seller_alias=item.get("seller_alias", "")[:64],
                    purchased_at=parse_iso_datetime(item.get("purchased_at", "")),
                    created_at=parse_iso_datetime(item.get("purchased_at", "")),
                )
                session.add(holding)
                count += 1
            except Exception as e:
                print(f"Error migrating holding for user {user_id}: {e}")

    await session.flush()
    print(f"Migrated {count} holdings")
    return count


async def migrate_yield_journal(session: AsyncSession) -> int:
    """Migrate yield journal entries."""
    journal_dir = STATE_DIR / "trade_yield_journal"
    if not journal_dir.exists():
        print("No yield journal directory")
        return 0

    count = 0
    for journal_file in journal_dir.glob("*.json"):
        user_id = int(journal_file.stem)
        entries = load_json_file(journal_file)

        if not entries:
            continue

        for item in entries:
            try:
                wallet_before = item.get("wallet_before", {})
                wallet_after = item.get("wallet_after", {})

                run = TradeYieldRuns(
                    public_id=item.get("run_id", ""),
                    user_id=user_id,
                    strategy=item.get("strategy", "balanced"),
                    annual_rate=item.get("annual_rate", 0.08),
                    elapsed_days=item.get("elapsed_days", 0),
                    yield_amount=credits_to_cents(item.get("yield_amount", 0)),
                    liquid_credits_before=credits_to_cents(
                        wallet_before.get("liquid_credits", 0)
                    ),
                    liquid_credits_after=credits_to_cents(
                        wallet_after.get("liquid_credits", 0)
                    ),
                    listing_adjustments=item.get("listing_adjustments", []),
                    created_at=parse_iso_datetime(item.get("generated_at", "")),
                )
                session.add(run)
                count += 1
            except Exception as e:
                print(f"Error migrating yield run {item.get('run_id')}: {e}")

    await session.flush()
    print(f"Migrated {count} yield journal entries")
    return count


async def main():
    """Main migration function."""
    print("=" * 60)
    print("Trade Data Migration Tool")
    print("JSON Files -> PostgreSQL Database")
    print("=" * 60)

    # Create engine
    database_url = settings.DATABASE_URL
    if "postgresql+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            print("\nMigrating market listings...")
            listings_count = await migrate_market(session)

            print("\nMigrating wallets...")
            wallets_count = await migrate_wallets(session)

            print("\nMigrating orders...")
            orders_count = await migrate_orders(session)

            print("\nMigrating holdings...")
            holdings_count = await migrate_holdings(session)

            print("\nMigrating yield journal...")
            yield_count = await migrate_yield_journal(session)

            print("\n" + "=" * 60)
            print("Migration Summary:")
            print(f"  - Market listings: {listings_count}")
            print(f"  - Wallets: {wallets_count}")
            print(f"  - Orders: {orders_count}")
            print(f"  - Holdings: {holdings_count}")
            print(f"  - Yield entries: {yield_count}")
            print("=" * 60)

            # Commit all changes
            confirm = input("\nCommit changes to database? (yes/no): ")
            if confirm.lower() == "yes":
                await session.commit()
                print("Changes committed successfully!")
            else:
                await session.rollback()
                print("Migration rolled back.")

        except Exception as e:
            print(f"\nError during migration: {e}")
            await session.rollback()
            raise

    await engine.dispose()
    print("\nMigration complete!")


if __name__ == "__main__":
    asyncio.run(main())
