"""
Exchange Orchestrator - Governance and orchestration layer for hybrid market architecture.

Implements:
- Task orchestration and routing
- Candidate matching (撮合)
- Protocol selection and management
- State machine control
- Exception handling and rollback
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agents.core import (
    MarketMechanismType,
    NegotiationStatus,
    TradeState,
    SellerAgentState,
    BuyerAgentState,
    SharedStateBoard,
)
from app.core.errors import ServiceError
from app.db.models import Users, TradeListings, TradeWallets

logger = logging.getLogger(__name__)


class ProtocolPhase(str, Enum):
    """Phases of market protocol execution."""
    INIT = "init"
    VALIDATION = "validation"
    MATCHING = "matching"
    NEGOTIATION = "negotiation"
    SETTLEMENT = "settlement"
    COMPLETION = "completion"
    ERROR = "error"


class ExchangeOrchestrator:
    """
    Exchange Orchestrator (Supervisor) for hybrid market architecture.

    Responsibilities:
    1. Validate transactions against policies
    2. Select appropriate market mechanism
    3. Orchestrate seller/buyer agents
    4. Manage shared state board
    5. Handle exceptions and rollback
    """

    # Maximum negotiation rounds
    DEFAULT_MAX_ROUNDS = 10
    MAX_NEGOTIATION_TIME_MINUTES = 30

    def __init__(
        self,
        db: AsyncSession,
        compliance_checker: Optional[Callable] = None,
        risk_scorer: Optional[Callable] = None,
    ):
        self._db = db
        self._compliance_checker = compliance_checker
        self._risk_scorer = risk_scorer
        self._active_negotiations: Dict[str, Dict[str, Any]] = {}

    # ========================================================================
    # Main Entry Points
    # ========================================================================

    async def initiate_listing(
        self,
        seller_user_id: int,
        asset_id: str,
        asset_summary: Dict[str, Any],
        pricing_strategy: str = "negotiable",
        reserve_price: float = 0.0,
        license_scope: Optional[List[str]] = None,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a new listing with market mechanism selection.

        Args:
            seller_user_id: ID of the seller
            asset_id: Asset to list
            asset_summary: Sanitized asset summary
            pricing_strategy: "fixed", "negotiable", or "auction"
            reserve_price: Minimum acceptable price
            license_scope: List of allowed usage types
            mechanism_hint: Preferred mechanism type

        Returns:
            Dict with negotiation_id, selected_mechanism, and initial state
        """
        negotiation_id = str(uuid.uuid4())[:32]

        # Validate seller
        seller_wallet = await self._get_wallet(seller_user_id)
        if not seller_wallet:
            raise ServiceError(404, "Seller wallet not found")

        # Initialize seller agent state
        seller_state: SellerAgentState = {
            "seller_user_id": seller_user_id,
            "seller_alias": f"seller-{str(uuid.uuid4())[:8]}",
            "asset_id": asset_id,
            "asset_summary": asset_summary,
            "asset_metadata": {},
            "reserve_price": reserve_price,
            "target_price": reserve_price * 1.2 if reserve_price > 0 else 100.0,
            "pricing_strategy": pricing_strategy,
            "license_scope": license_scope or ["personal_use"],
            "usage_restrictions": {"no_redistribution": True},
            "redistribution_allowed": False,
            "max_usage_count": None,
            "desensitization_level": "partial",
            "visible_fields": ["title", "summary", "category"],
            "hidden_fields": ["raw_content", "source_documents"],
            "current_quote": None,
            "quote_history": [],
            "is_open_to_negotiate": pricing_strategy == "negotiable",
            "min_acceptable_price": reserve_price * 0.9 if reserve_price > 0 else 0.0,
            "announced_tasks": [],
            "received_bids": [],
            "awarded_buyers": [],
        }

        # Select market mechanism
        selected_mechanism = self._select_mechanism(
            pricing_strategy=pricing_strategy,
            mechanism_hint=mechanism_hint,
        )

        # Initialize shared state board
        shared_board: SharedStateBoard = {
            "negotiation_id": negotiation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "public_quotes": [],
            "announced_conditions": {
                "reserve_price": reserve_price,
                "pricing_strategy": pricing_strategy,
                "license_scope": license_scope,
            },
            "current_conditions": {},
            "agreed_conditions": {},
            "event_log": [{
                "event": "listing_initiated",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "seller_id": seller_user_id,
                "asset_id": asset_id,
            }],
            "message_log": [],
            "commitment_hashes": [],
            "timestamp_proofs": [],
            "active_participants": [seller_user_id],
            "current_phase": "announcing",
            "estimated_completion": None,
        }

        # Initialize trade state
        trade_state: TradeState = {
            "action": "listing",
            "asset_to_list": asset_summary,
            "policy": {},
            "listing": None,
            "listing_id": None,
            "order": None,
            "delivery": None,
            "mechanism_type": selected_mechanism.value,
            "negotiation_id": negotiation_id,
            "shared_board": shared_board,
            "seller_agent_state": seller_state,
            "buyer_agent_state": None,
            "negotiation_round": 0,
            "max_rounds": self.DEFAULT_MAX_ROUNDS,
            "negotiation_status": "announcing",
            "settlement_result": None,
            "audit_log": [],
        }

        # Store active negotiation
        self._active_negotiations[negotiation_id] = {
            "state": trade_state,
            "seller_id": seller_user_id,
            "started_at": datetime.now(timezone.utc),
            "mechanism": selected_mechanism,
        }

        logger.info(f"Listing initiated: {negotiation_id} with mechanism {selected_mechanism.value}")

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "mechanism": selected_mechanism.value,
            "seller_alias": seller_state["seller_alias"],
            "status": "announcing",
            "next_steps": self._get_next_steps(selected_mechanism),
        }

    async def initiate_purchase(
        self,
        buyer_user_id: int,
        listing_id: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
        budget_max: float = 0.0,
        mechanism_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a purchase request with market mechanism selection.

        Args:
            buyer_user_id: ID of the buyer
            listing_id: Specific listing to purchase (optional)
            requirements: Buyer's requirements if no specific listing
            budget_max: Maximum budget
            mechanism_hint: Preferred mechanism type

        Returns:
            Dict with negotiation_id and initial state
        """
        negotiation_id = str(uuid.uuid4())[:32]

        # Validate buyer
        buyer_wallet = await self._get_wallet(buyer_user_id)
        if not buyer_wallet:
            raise ServiceError(404, "Buyer wallet not found")

        if budget_max > 0 and buyer_wallet.liquid_credits < budget_max:
            raise ServiceError(400, "Insufficient balance for stated budget")

        # Initialize buyer agent state
        buyer_state: BuyerAgentState = {
            "buyer_user_id": buyer_user_id,
            "buyer_alias": f"buyer-{str(uuid.uuid4())[:8]}",
            "requirements": requirements or {},
            "quality_preferences": {},
            "risk_constraints": {"max_price": budget_max},
            "intended_use": "personal",
            "budget_max": budget_max,
            "budget_preferred": budget_max * 0.8 if budget_max > 0 else 0.0,
            "payment_terms": "immediate",
            "candidate_sellers": [],
            "comparing_offers": [],
            "shortlisted": [],
            "current_bid": None,
            "bid_history": [],
            "counter_offer_ready": False,
            "max_rounds_acceptable": 5,
            "submitted_bids": [],
            "awarded_contracts": [],
        }

        # If specific listing, get seller info
        seller_state = None
        if listing_id:
            listing = await self._get_listing(listing_id)
            if not listing:
                raise ServiceError(404, "Listing not found")

            # Check if fixed price
            if listing.get("pricing_strategy") == "fixed":
                selected_mechanism = MarketMechanismType.FIXED_PRICE
            else:
                selected_mechanism = MarketMechanismType.BILATERAL

            # Create seller state from listing
            seller_state: SellerAgentState = {
                "seller_user_id": listing["seller_user_id"],
                "seller_alias": listing["seller_alias"],
                "asset_id": listing["asset_id"],
                "asset_summary": {},
                "asset_metadata": {},
                "reserve_price": listing.get("price_credits", 0) / 100,
                "target_price": listing.get("price_credits", 0) / 100,
                "pricing_strategy": listing.get("pricing_strategy", "fixed"),
                "license_scope": listing.get("license_scope", ["personal_use"]),
                "usage_restrictions": {},
                "redistribution_allowed": False,
                "max_usage_count": None,
                "desensitization_level": "partial",
                "visible_fields": [],
                "hidden_fields": [],
                "current_quote": listing.get("price_credits", 0) / 100,
                "quote_history": [],
                "is_open_to_negotiate": listing.get("pricing_strategy") != "fixed",
                "min_acceptable_price": listing.get("price_credits", 0) / 100 * 0.9,
                "announced_tasks": [],
                "received_bids": [],
                "awarded_buyers": [],
            }
        else:
            # Search for candidates
            selected_mechanism = MarketMechanismType.CONTRACT_NET

        # Initialize shared state board
        shared_board: SharedStateBoard = {
            "negotiation_id": negotiation_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "public_quotes": [],
            "announced_conditions": {},
            "current_conditions": {
                "buyer_budget": budget_max,
                "buyer_requirements": requirements,
            },
            "agreed_conditions": {},
            "event_log": [{
                "event": "purchase_initiated",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "buyer_id": buyer_user_id,
                "listing_id": listing_id,
            }],
            "message_log": [],
            "commitment_hashes": [],
            "timestamp_proofs": [],
            "active_participants": [buyer_user_id],
            "current_phase": "bidding",
            "estimated_completion": None,
        }

        # Initialize trade state
        trade_state: TradeState = {
            "action": "purchase",
            "asset_to_list": None,
            "policy": {},
            "listing": None,
            "listing_id": listing_id,
            "order": None,
            "delivery": None,
            "mechanism_type": selected_mechanism.value,
            "negotiation_id": negotiation_id,
            "shared_board": shared_board,
            "seller_agent_state": seller_state,
            "buyer_agent_state": buyer_state,
            "negotiation_round": 0,
            "max_rounds": self.DEFAULT_MAX_ROUNDS,
            "negotiation_status": "bidding",
            "settlement_result": None,
            "audit_log": [],
        }

        # Store active negotiation
        self._active_negotiations[negotiation_id] = {
            "state": trade_state,
            "buyer_id": buyer_user_id,
            "seller_id": seller_state["seller_user_id"] if seller_state else None,
            "started_at": datetime.now(timezone.utc),
            "mechanism": selected_mechanism,
        }

        logger.info(f"Purchase initiated: {negotiation_id} with mechanism {selected_mechanism.value}")

        return {
            "success": True,
            "negotiation_id": negotiation_id,
            "mechanism": selected_mechanism.value,
            "buyer_alias": buyer_state["buyer_alias"],
            "status": "bidding",
            "next_steps": self._get_next_steps(selected_mechanism),
        }

    # ========================================================================
    # Market Mechanism Selection
    # ========================================================================

    def _select_mechanism(
        self,
        pricing_strategy: str,
        mechanism_hint: Optional[str] = None,
    ) -> MarketMechanismType:
        """Select appropriate market mechanism based on strategy."""
        if mechanism_hint:
            try:
                return MarketMechanismType(mechanism_hint)
            except ValueError:
                pass

        strategy_mechanism_map = {
            "fixed": MarketMechanismType.FIXED_PRICE,
            "negotiable": MarketMechanismType.BILATERAL,
            "auction": MarketMechanismType.AUCTION,
            "competitive": MarketMechanismType.CONTRACT_NET,
        }

        return strategy_mechanism_map.get(pricing_strategy, MarketMechanismType.BILATERAL)

    def _get_next_steps(self, mechanism: MarketMechanismType) -> List[str]:
        """Get next steps description for the selected mechanism."""
        steps = {
            MarketMechanismType.FIXED_PRICE: [
                "Review listing details",
                "Confirm purchase",
                "Complete settlement",
            ],
            MarketMechanismType.BILATERAL: [
                "Submit initial offer",
                "Wait for seller response",
                "Negotiate terms if needed",
                "Reach agreement",
            ],
            MarketMechanismType.AUCTION: [
                "Place bid",
                "Monitor bidding",
                "Wait for auction end",
                "Claim if won",
            ],
            MarketMechanismType.CONTRACT_NET: [
                "Submit requirements",
                "Receive proposals",
                "Evaluate bids",
                "Select winner",
            ],
        }
        return steps.get(mechanism, ["Proceed with transaction"])

    # ========================================================================
    # Protocol Execution
    # ========================================================================

    async def execute_protocol_step(
        self,
        negotiation_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a step in the market protocol.

        Args:
            negotiation_id: Active negotiation session ID
            action: Action to perform (e.g., "bid", "counter_offer", "accept")
            payload: Action-specific data

        Returns:
            Updated state and next actions
        """
        negotiation = self._active_negotiations.get(negotiation_id)
        if not negotiation:
            raise ServiceError(404, "Negotiation not found")

        state = negotiation["state"]
        mechanism = negotiation["mechanism"]

        # Log action
        self._log_event(negotiation_id, action, payload)

        # Execute based on mechanism
        if mechanism == MarketMechanismType.FIXED_PRICE:
            result = await self._execute_fixed_price_step(state, action, payload)
        elif mechanism == MarketMechanismType.BILATERAL:
            result = await self._execute_bilateral_step(state, action, payload)
        elif mechanism == MarketMechanismType.AUCTION:
            result = await self._execute_auction_step(state, action, payload)
        elif mechanism == MarketMechanismType.CONTRACT_NET:
            result = await self._execute_contract_net_step(state, action, payload)
        else:
            raise ServiceError(400, f"Unknown mechanism: {mechanism}")

        # Check for timeout
        elapsed = (datetime.now(timezone.utc) - negotiation["started_at"]).total_seconds()
        if elapsed > self.MAX_NEGOTIATION_TIME_MINUTES * 60:
            result["timeout_warning"] = True
            result["seconds_remaining"] = 0
        else:
            result["seconds_remaining"] = self.MAX_NEGOTIATION_TIME_MINUTES * 60 - elapsed

        return result

    async def _execute_fixed_price_step(
        self,
        state: TradeState,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute fixed price purchase step."""
        if action == "purchase":
            # Direct purchase
            return {
                "success": True,
                "status": "finalizing",
                "message": "Proceeding to settlement",
                "price": state["seller_agent_state"]["current_quote"],
            }
        return {"success": False, "error": "Invalid action for fixed price"}

    async def _execute_bilateral_step(
        self,
        state: TradeState,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute bilateral negotiation step."""
        round_num = state["negotiation_round"]

        if action == "offer":
            # Buyer makes offer
            offer_price = payload.get("price", 0)
            state["buyer_agent_state"]["current_bid"] = offer_price
            state["buyer_agent_state"]["bid_history"].append({
                "round": round_num,
                "price": offer_price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Check if acceptable to seller
            min_price = state["seller_agent_state"]["min_acceptable_price"]
            if offer_price >= min_price:
                return {
                    "success": True,
                    "status": "awarding",
                    "message": "Offer accepted by seller",
                    "accepted_price": offer_price,
                }

            # Seller counters
            counter = min(offer_price * 1.1, state["seller_agent_state"]["target_price"])
            state["seller_agent_state"]["current_quote"] = counter

            state["negotiation_round"] += 1

            if state["negotiation_round"] >= state["max_rounds"]:
                return {
                    "success": False,
                    "status": "cancelled",
                    "message": "Max rounds reached without agreement",
                }

            return {
                "success": True,
                "status": "negotiating",
                "message": "Seller countered with new price",
                "counter_offer": counter,
                "round": state["negotiation_round"],
            }

        elif action == "accept":
            # Accept current offer
            return {
                "success": True,
                "status": "awarding",
                "message": "Offer accepted",
                "final_price": state["seller_agent_state"]["current_quote"],
            }

        elif action == "reject":
            state["negotiation_status"] = "cancelled"
            return {
                "success": False,
                "status": "cancelled",
                "message": "Offer rejected",
            }

        return {"success": False, "error": "Invalid action for bilateral"}

    async def _execute_auction_step(
        self,
        state: TradeState,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute auction step."""
        # Simplified auction logic
        if action == "bid":
            bid_amount = payload.get("amount", 0)
            bidder_id = payload.get("bidder_id")

            # Validate bid
            current_price = state["shared_board"]["public_quotes"][-1]["price"] if state["shared_board"]["public_quotes"] else state["seller_agent_state"]["reserve_price"]

            if bid_amount <= current_price:
                return {
                    "success": False,
                    "error": f"Bid must be higher than current price {current_price}",
                }

            # Record bid
            state["shared_board"]["public_quotes"].append({
                "bidder_id": bidder_id,
                "price": bid_amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            return {
                "success": True,
                "status": "bidding",
                "current_price": bid_amount,
                "current_winner": bidder_id,
            }

        elif action == "close":
            # Close auction
            if state["shared_board"]["public_quotes"]:
                highest = max(state["shared_board"]["public_quotes"], key=lambda x: x["price"])
                return {
                    "success": True,
                    "status": "awarding",
                    "winner": highest["bidder_id"],
                    "final_price": highest["price"],
                }

        return {"success": False, "error": "Invalid action for auction"}

    async def _execute_contract_net_step(
        self,
        state: TradeState,
        action: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute contract net protocol step."""
        if action == "announce":
            # Seller announces task
            state["shared_board"]["announced_conditions"] = payload
            state["negotiation_status"] = "announcing"
            return {
                "success": True,
                "status": "bidding",
                "message": "Task announced, waiting for bids",
            }

        elif action == "bid":
            # Buyer submits bid
            bid = {
                "bidder_id": payload.get("bidder_id"),
                "price": payload.get("price"),
                "qualifications": payload.get("qualifications", {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            state["seller_agent_state"]["received_bids"].append(bid)

            return {
                "success": True,
                "status": "bidding",
                "bid_count": len(state["seller_agent_state"]["received_bids"]),
            }

        elif action == "award":
            # Seller awards to bidder
            bidder_id = payload.get("bidder_id")
            state["seller_agent_state"]["awarded_buyers"].append(bidder_id)
            state["negotiation_status"] = "awarding"

            return {
                "success": True,
                "status": "awarding",
                "awarded_to": bidder_id,
            }

        return {"success": False, "error": "Invalid action for contract net"}

    # ========================================================================
    # Settlement
    # ========================================================================

    async def finalize_settlement(
        self,
        negotiation_id: str,
        final_price: float,
        buyer_id: int,
        seller_id: int,
    ) -> Dict[str, Any]:
        """
        Finalize settlement after agreement reached.

        Args:
            negotiation_id: Active negotiation ID
            final_price: Agreed price
            buyer_id: Buyer's user ID
            seller_id: Seller's user ID

        Returns:
            Settlement result with order details
        """
        negotiation = self._active_negotiations.get(negotiation_id)
        if not negotiation:
            raise ServiceError(404, "Negotiation not found")

        # Calculate fees
        platform_fee = final_price * 0.05
        seller_proceeds = final_price - platform_fee

        # Get wallets
        buyer_wallet = await self._get_wallet(buyer_id)
        seller_wallet = await self._get_wallet(seller_id)

        if not buyer_wallet or not seller_wallet:
            raise ServiceError(404, "Wallet not found")

        # Check buyer balance
        if buyer_wallet.liquid_credits < final_price * 100:  # Convert to cents
            raise ServiceError(400, "Buyer insufficient balance")

        settlement_result = {
            "negotiation_id": negotiation_id,
            "final_price": final_price,
            "platform_fee": platform_fee,
            "seller_proceeds": seller_proceeds,
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "settled_at": datetime.now(timezone.utc).isoformat(),
            "delivery_pending": True,
            "access_token": str(uuid.uuid4())[:32],
        }

        # Update state
        negotiation["state"]["settlement_result"] = settlement_result
        negotiation["state"]["negotiation_status"] = "settled"

        # Log settlement
        self._log_event(negotiation_id, "settlement_completed", settlement_result)

        return {
            "success": True,
            "settlement": settlement_result,
            "order_id": str(uuid.uuid4())[:32],
        }

    # ========================================================================
    # Helpers
    # ========================================================================

    async def _get_wallet(self, user_id: int) -> Optional[TradeWallets]:
        """Get user's trade wallet."""
        from app.repositories.trade_repo import TradeRepository
        repo = TradeRepository(self._db)
        return await repo.get_wallet(user_id)

    async def _get_listing(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """Get listing by ID."""
        from app.repositories.trade_repo import TradeRepository
        repo = TradeRepository(self._db)
        listing = await repo.get_listing_by_public_id(listing_id)
        if listing:
            return {
                "listing_id": listing.public_id,
                "seller_user_id": listing.seller_user_id,
                "seller_alias": listing.seller_alias,
                "asset_id": listing.asset_id,
                "price_credits": listing.price_credits,
                "pricing_strategy": "fixed" if listing.price_credits > 0 else "negotiable",
                "license_scope": listing.tags,
            }
        return None

    def _log_event(
        self,
        negotiation_id: str,
        event: str,
        payload: Dict[str, Any],
    ):
        """Log event to shared state board."""
        negotiation = self._active_negotiations.get(negotiation_id)
        if negotiation:
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "payload_hash": hash(str(payload)) % 1000000,  # Simple hash
            }
            negotiation["state"]["shared_board"]["event_log"].append(log_entry)
            negotiation["state"]["shared_board"]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def get_negotiation_status(self, negotiation_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a negotiation."""
        negotiation = self._active_negotiations.get(negotiation_id)
        if not negotiation:
            return None

        state = negotiation["state"]
        return {
            "negotiation_id": negotiation_id,
            "mechanism": state["mechanism_type"],
            "status": state["negotiation_status"],
            "round": state["negotiation_round"],
            "max_rounds": state["max_rounds"],
            "shared_board": state["shared_board"],
        }
