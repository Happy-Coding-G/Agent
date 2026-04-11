"""
Unified Trade Service - Integrates TradeService with Hybrid Market TradeAgent

Combines:
- TradeService: Database-backed CRUD with ACID transactions
- TradeAgent: Hybrid market negotiation (Auction, Contract Net, Bilateral)
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from .trade_service import TradeService
from app.agents.subagents.trade.agent import TradeAgent
from app.db.models import Users


class UnifiedTradeService:
    """
    Unified trade service combining database operations with market negotiation.

    Architecture:
    - Simple trades (fixed price): Direct TradeService
    - Complex negotiations (auction/bilateral): TradeAgent with market mechanisms
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        self._trade = TradeService(db)
        self._agent = TradeAgent(db)

    # ========================================================================
    # Listing Operations
    # ========================================================================

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        pricing_strategy: str = "fixed",  # "fixed", "negotiable", "auction"
        price_credits: Optional[float] = None,
        reserve_price: Optional[float] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        license_scope: Optional[List[str]] = None,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a listing with selected pricing strategy.

        Args:
            pricing_strategy: "fixed" | "negotiable" | "auction"
            mechanism_hint: "contract_net" | "auction" | "bilateral"
        """
        if pricing_strategy == "fixed":
            # Use simple TradeService for fixed price
            return await self._trade.create_listing(
                space_public_id=space_public_id,
                asset_id=asset_id,
                user=user,
                price_credits=price_credits,
                category=category,
                tags=tags,
            )
        else:
            # Use TradeAgent for complex negotiations
            return await self._agent.create_listing(
                space_public_id=space_public_id,
                asset_id=asset_id,
                user=user,
                pricing_strategy=pricing_strategy,
                reserve_price=reserve_price or price_credits,
                license_scope=license_scope,
                mechanism_hint=mechanism_hint,
                category=category,
                tags=tags,
            )

    async def get_listing(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """Get listing details."""
        return await self._trade.get_listing(listing_id)

    async def list_market(
        self,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List active marketplace items."""
        return await self._trade.list_market(
            category=category,
            min_price=min_price,
            max_price=max_price,
            limit=limit,
            offset=offset,
        )

    # ========================================================================
    # Purchase Operations
    # ========================================================================

    async def purchase(
        self,
        listing_id: str,
        buyer: Users,
        purchase_type: str = "direct",  # "direct" | "auction_bid" | "bilateral"
        bid_amount: Optional[float] = None,
        initial_offer: Optional[float] = None,
        max_rounds: int = 10,
        budget_max: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Purchase a listing with selected mechanism.

        Args:
            purchase_type: Purchase mechanism to use
            bid_amount: For auction bids
            initial_offer: For bilateral negotiation
            max_rounds: Max negotiation rounds
            budget_max: Maximum budget for negotiation
        """
        if purchase_type == "direct":
            # Simple fixed-price purchase
            return await self._trade.purchase(listing_id, buyer)
        else:
            # Complex negotiation via TradeAgent
            return await self._agent.initiate_purchase(
                user=buyer,
                listing_id=listing_id,
                budget_max=budget_max or bid_amount or initial_offer or 0,
                mechanism_hint=purchase_type,
            )

    # ========================================================================
    # Auction Operations
    # ========================================================================

    async def create_auction(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        auction_type: str,  # "english", "dutch", "sealed", "vickrey"
        starting_price: float,
        reserve_price: Optional[float] = None,
        duration_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Create an auction listing."""
        return await self._agent.create_auction(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            auction_type=auction_type,
            starting_price=starting_price,
            reserve_price=reserve_price,
            duration_minutes=duration_minutes,
        )

    async def place_auction_bid(
        self,
        lot_id: str,
        user: Users,
        amount: float,
    ) -> Dict[str, Any]:
        """Place a bid in an auction."""
        return await self._agent.place_auction_bid(
            lot_id=lot_id,
            user=user,
            amount=amount,
        )

    async def close_auction(
        self,
        lot_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """Close an auction (seller only)."""
        return await self._agent.close_auction(lot_id, user)

    async def get_auction_status(self, lot_id: str) -> Dict[str, Any]:
        """Get auction status."""
        return await self._agent.get_auction_status(lot_id)

    async def list_active_auctions(self) -> List[Dict[str, Any]]:
        """List all active auctions."""
        return await self._agent.list_active_auctions()

    # ========================================================================
    # Bilateral Negotiation Operations
    # ========================================================================

    async def create_negotiation(
        self,
        listing_id: str,
        buyer: Users,
        initial_offer: float,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """Create a bilateral negotiation for a listing."""
        return await self._agent.create_bilateral_negotiation(
            listing_id=listing_id,
            buyer=buyer,
            initial_offer=initial_offer,
            max_rounds=max_rounds,
        )

    async def make_offer(
        self,
        session_id: str,
        user: Users,
        price: float,
        terms: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an offer in a bilateral negotiation."""
        return await self._agent.make_negotiation_offer(
            session_id=session_id,
            user=user,
            price=price,
            terms=terms,
            message=message,
        )

    async def respond_to_offer(
        self,
        session_id: str,
        user: Users,
        response: str,  # "accept", "reject", "counter"
        counter_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Respond to an offer in bilateral negotiation."""
        return await self._agent.respond_to_negotiation_offer(
            session_id=session_id,
            user=user,
            response=response,
            counter_price=counter_price,
        )

    async def get_negotiation_status(
        self,
        negotiation_id: str,
        user: Users,
    ) -> Dict[str, Any]:
        """Get status of a negotiation."""
        return await self._agent.get_negotiation_status(negotiation_id, user)

    # ========================================================================
    # Contract Net Operations
    # ========================================================================

    async def announce_contract_net_task(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        task_description: Dict[str, Any],
        eligibility_criteria: Optional[Dict[str, Any]] = None,
        deadline_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Announce a task using Contract Net Protocol."""
        return await self._agent.announce_contract_net_task(
            space_public_id=space_public_id,
            asset_id=asset_id,
            user=user,
            task_description=task_description,
            eligibility_criteria=eligibility_criteria,
            deadline_minutes=deadline_minutes,
        )

    async def submit_contract_net_bid(
        self,
        announcement_id: str,
        user: Users,
        bid_amount: float,
        qualifications: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit a bid for a Contract Net task."""
        return await self._agent.submit_contract_net_bid(
            announcement_id=announcement_id,
            user=user,
            bid_amount=bid_amount,
            qualifications=qualifications,
        )

    # ========================================================================
    # Wallet & Holdings Operations (delegate to TradeService)
    # ========================================================================

    async def get_wallet(self, user_id: int) -> Dict[str, Any]:
        """Get user's wallet."""
        return await self._trade.get_wallet(user_id)

    async def get_holdings(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """Get user's purchased assets."""
        return await self._trade.get_holdings(user_id, limit, offset)

    async def get_purchased_content(self, user_id: int, listing_id: str) -> Dict:
        """Get purchased content for a holding."""
        return await self._trade.get_purchased_content(user_id, listing_id)

    async def get_transaction_history(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> List[Dict]:
        """Get user's transaction history."""
        return await self._trade.get_transaction_history(user_id, limit, offset)

    # ========================================================================
    # Yield Operations (delegate to TradeService)
    # ========================================================================

    async def run_auto_yield(
        self,
        user: Users,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run auto-yield for user."""
        return await self._trade.run_auto_yield(user, strategy)

    async def update_yield_settings(
        self, user_id: int, strategy: Optional[str] = None, enabled: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Update yield settings."""
        return await self._trade.update_yield_settings(user_id, strategy, enabled)
