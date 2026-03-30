"""
Bilateral Negotiation Mechanism (双边协商机制)

Implements multi-round bilateral negotiation between buyer and seller:
- Price negotiation with concession tracking
- Term negotiation (license scope, delivery, etc.)
- Deadline management
- Automatic termination conditions
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class NegotiationRoundStatus(str, Enum):
    """Status of a negotiation round."""
    PENDING = "pending"           # 等待对方回应
    ACCEPTED = "accepted"         # 接受
    REJECTED = "rejected"         # 拒绝
    COUNTERED = "countered"       # 提出反报价
    EXPIRED = "expired"           # 过期


@dataclass
class Offer:
    """An offer in bilateral negotiation."""
    offer_id: str
    round_number: int
    from_party: str               # "seller" or "buyer"
    to_party: str
    price: float
    terms: Dict[str, Any]
    message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


@dataclass
class NegotiationRound:
    """A single round of bilateral negotiation."""
    round_number: int
    seller_offer: Optional[Offer] = None
    buyer_offer: Optional[Offer] = None
    status: NegotiationRoundStatus = NegotiationRoundStatus.PENDING
    concession_seller: float = 0.0    # 卖方让步幅度
    concession_buyer: float = 0.0     # 买方让步幅度
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class BilateralNegotiation:
    """
    Bilateral negotiation mechanism with multi-round support.

    Features:
    - Price and term negotiation
    - Concession tracking and analysis
    - Deadline management
    - Automatic termination on deadlock
    - BATNA (Best Alternative to Negotiated Agreement) tracking
    """

    DEFAULT_MAX_ROUNDS = 10
    DEFAULT_OFFER_TIMEOUT_MINUTES = 30
    MIN_CONCESSION_THRESHOLD = 0.01   # 最小让步阈值 (1%)

    def __init__(
        self,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        offer_timeout_minutes: int = DEFAULT_OFFER_TIMEOUT_MINUTES,
        on_agreement: Optional[Callable] = None,
        on_termination: Optional[Callable] = None,
    ):
        self.max_rounds = max_rounds
        self.offer_timeout_minutes = offer_timeout_minutes
        self.on_agreement = on_agreement
        self.on_termination = on_termination

        self.negotiations: Dict[str, Dict[str, Any]] = {}  # session_id -> negotiation data

    # ========================================================================
    # Session Management
    # ========================================================================

    def create_negotiation(
        self,
        seller_id: int,
        buyer_id: int,
        initial_seller_price: float,
        initial_buyer_price: float,
        negotiable_terms: Optional[List[str]] = None,
        seller_batna: Optional[float] = None,    # Seller's walk-away price
        buyer_batna: Optional[float] = None,     # Buyer's walk-away price
    ) -> Dict[str, Any]:
        """
        Create a new bilateral negotiation session.

        Args:
            seller_id: Seller's user ID
            buyer_id: Buyer's user ID
            initial_seller_price: Seller's opening price
            initial_buyer_price: Buyer's opening price
            negotiable_terms: List of terms that can be negotiated
            seller_batna: Seller's BATNA (reserve price)
            buyer_batna: Buyer's BATNA (max willing to pay)

        Returns:
            Session initialization result
        """
        session_id = str(uuid.uuid4())[:32]

        negotiation_data = {
            "session_id": session_id,
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "rounds": [],
            "current_round": 0,
            "seller_batna": seller_batna or initial_seller_price * 0.8,
            "buyer_batna": buyer_batna or initial_buyer_price * 1.2,
            "initial_seller_price": initial_seller_price,
            "initial_buyer_price": initial_buyer_price,
            "negotiable_terms": negotiable_terms or ["price"],
            "status": "active",
            "agreement": None,
            "termination_reason": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        self.negotiations[session_id] = negotiation_data

        logger.info(f"Bilateral negotiation created: {session_id}")

        return {
            "success": True,
            "session_id": session_id,
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "current_round": 0,
            "status": "active",
            "next_action": "seller" if initial_seller_price <= initial_buyer_price else "buyer",
        }

    # ========================================================================
    # Making Offers
    # ========================================================================

    def make_offer(
        self,
        session_id: str,
        from_party: str,          # "seller" or "buyer"
        price: float,
        terms: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Make an offer in the negotiation.

        Args:
            session_id: Negotiation session ID
            from_party: "seller" or "buyer"
            price: Offered price
            terms: Additional terms
            message: Optional message

        Returns:
            Offer result with analysis
        """
        negotiation = self.negotiations.get(session_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        if negotiation["status"] != "active":
            return {"success": False, "error": f"Negotiation is {negotiation['status']}"}

        # Determine round
        current_round_num = negotiation["current_round"] + 1
        if current_round_num > self.max_rounds:
            negotiation["status"] = "terminated"
            negotiation["termination_reason"] = "max_rounds_reached"
            return {"success": False, "error": "Maximum rounds reached"}

        to_party = "buyer" if from_party == "seller" else "seller"

        # Create offer
        offer = Offer(
            offer_id=str(uuid.uuid4())[:32],
            round_number=current_round_num,
            from_party=from_party,
            to_party=to_party,
            price=price,
            terms=terms or {},
            message=message,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.offer_timeout_minutes),
        )

        # Get or create round
        if len(negotiation["rounds"]) < current_round_num:
            round_data = NegotiationRound(round_number=current_round_num)
            negotiation["rounds"].append(round_data)
        else:
            round_data = negotiation["rounds"][current_round_num - 1]

        # Store offer
        if from_party == "seller":
            round_data.seller_offer = offer
        else:
            round_data.buyer_offer = offer

        negotiation["current_round"] = current_round_num
        negotiation["updated_at"] = datetime.now(timezone.utc)

        # Calculate concession if previous round exists
        concession = self._calculate_concession(negotiation, from_party, price)

        logger.info(f"Offer made in {session_id} round {current_round_num} by {from_party}: {price}")

        return {
            "success": True,
            "session_id": session_id,
            "round": current_round_num,
            "offer_id": offer.offer_id,
            "from": from_party,
            "price": price,
            "concession_rate": concession,
            "waiting_for": to_party,
            "expires_at": offer.expires_at.isoformat(),
        }

    def _calculate_concession(
        self,
        negotiation: Dict[str, Any],
        party: str,
        current_price: float,
    ) -> float:
        """Calculate concession rate compared to previous offer."""
        rounds = negotiation["rounds"]
        if len(rounds) < 2:
            return 0.0

        # Find previous offer from this party
        previous_offer = None
        for r in reversed(rounds[:-1]):  # Exclude current round
            if party == "seller" and r.seller_offer:
                previous_offer = r.seller_offer.price
                break
            elif party == "buyer" and r.buyer_offer:
                previous_offer = r.buyer_offer.price
                break

        if previous_offer is None:
            # Use initial position
            previous_offer = negotiation["initial_seller_price"] if party == "seller" else negotiation["initial_buyer_price"]

        if party == "seller":
            # Seller concession: decrease in price
            if previous_offer > 0:
                return max(0, (previous_offer - current_price) / previous_offer)
        else:
            # Buyer concession: increase in price offered
            if previous_offer > 0:
                return max(0, (current_price - previous_offer) / previous_offer)

        return 0.0

    # ========================================================================
    # Responding to Offers
    # ========================================================================

    def respond_to_offer(
        self,
        session_id: str,
        responder: str,           # "seller" or "buyer"
        response: str,            # "accept", "reject", "counter"
        counter_price: Optional[float] = None,
        counter_terms: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Respond to an offer.

        Args:
            session_id: Negotiation session ID
            responder: Who is responding
            response: "accept", "reject", or "counter"
            counter_price: Counter-offer price (if counter)
            counter_terms: Counter-offer terms (if counter)
            message: Optional message

        Returns:
            Response result
        """
        negotiation = self.negotiations.get(session_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        current_round = negotiation["current_round"]
        if current_round == 0 or current_round > len(negotiation["rounds"]):
            return {"success": False, "error": "No active offer to respond to"}

        round_data = negotiation["rounds"][current_round - 1]

        # Determine which offer we're responding to
        if responder == "seller":
            offer_to_respond = round_data.buyer_offer
        else:
            offer_to_respond = round_data.seller_offer

        if not offer_to_respond:
            return {"success": False, "error": "No offer from other party to respond to"}

        # Check if offer expired
        if offer_to_respond.expires_at and datetime.now(timezone.utc) > offer_to_respond.expires_at:
            round_data.status = NegotiationRoundStatus.EXPIRED
            return {"success": False, "error": "Offer has expired"}

        # Process response
        if response == "accept":
            return self._handle_acceptance(negotiation, round_data, offer_to_respond)

        elif response == "reject":
            round_data.status = NegotiationRoundStatus.REJECTED
            round_data.completed_at = datetime.now(timezone.utc)
            negotiation["status"] = "terminated"
            negotiation["termination_reason"] = "rejected"

            if self.on_termination:
                self.on_termination(session_id, "rejected")

            return {
                "success": True,
                "status": "terminated",
                "reason": "rejected",
                "final_round": current_round,
            }

        elif response == "counter":
            if counter_price is None:
                return {"success": False, "error": "Counter offer requires a price"}

            round_data.status = NegotiationRoundStatus.COUNTERED
            round_data.completed_at = datetime.now(timezone.utc)

            # Create counter offer in next round
            return self.make_offer(
                session_id=session_id,
                from_party=responder,
                price=counter_price,
                terms=counter_terms,
                message=message,
            )

        return {"success": False, "error": "Invalid response type"}

    def _handle_acceptance(
        self,
        negotiation: Dict[str, Any],
        round_data: NegotiationRound,
        accepted_offer: Offer,
    ) -> Dict[str, Any]:
        """Handle offer acceptance."""
        round_data.status = NegotiationRoundStatus.ACCEPTED
        round_data.completed_at = datetime.now(timezone.utc)

        negotiation["status"] = "agreed"
        negotiation["agreement"] = {
            "price": accepted_offer.price,
            "terms": accepted_offer.terms,
            "agreed_at": datetime.now(timezone.utc).isoformat(),
            "rounds_to_agreement": negotiation["current_round"],
        }

        # Calculate final concessions
        seller_concession = self._calculate_total_concession(negotiation, "seller")
        buyer_concession = self._calculate_total_concession(negotiation, "buyer")

        logger.info(f"Agreement reached in {negotiation['session_id']}: {accepted_offer.price}")

        if self.on_agreement:
            self.on_agreement(
                negotiation["session_id"],
                negotiation["agreement"],
            )

        return {
            "success": True,
            "status": "agreed",
            "agreed_price": accepted_offer.price,
            "terms": accepted_offer.terms,
            "total_rounds": negotiation["current_round"],
            "seller_concession": seller_concession,
            "buyer_concession": buyer_concession,
        }

    def _calculate_total_concession(self, negotiation: Dict[str, Any], party: str) -> float:
        """Calculate total concession from initial position to final agreement."""
        agreement = negotiation.get("agreement")
        if not agreement:
            return 0.0

        initial = negotiation["initial_seller_price"] if party == "seller" else negotiation["initial_buyer_price"]
        final = agreement["price"]

        if party == "seller":
            return max(0, (initial - final) / initial) if initial > 0 else 0
        else:
            return max(0, (final - initial) / initial) if initial > 0 else 0

    # ========================================================================
    # Analysis & Status
    # ========================================================================

    def get_negotiation_status(self, session_id: str) -> Dict[str, Any]:
        """Get current status of a negotiation."""
        negotiation = self.negotiations.get(session_id)
        if not negotiation:
            return {"error": "Negotiation not found"}

        rounds_summary = []
        for r in negotiation["rounds"]:
            rounds_summary.append({
                "round": r.round_number,
                "seller_price": r.seller_offer.price if r.seller_offer else None,
                "buyer_price": r.buyer_offer.price if r.buyer_offer else None,
                "status": r.status.value,
            })

        # Calculate zone of possible agreement (ZOPA)
        zopa_low = negotiation["seller_batna"]
        zopa_high = negotiation["buyer_batna"]
        zopa_exists = zopa_low <= zopa_high

        return {
            "session_id": session_id,
            "status": negotiation["status"],
            "current_round": negotiation["current_round"],
            "max_rounds": self.max_rounds,
            "rounds_summary": rounds_summary,
            "zopa": {
                "low": zopa_low,
                "high": zopa_high,
                "exists": zopa_exists,
            } if negotiation["status"] == "active" else None,
            "agreement": negotiation.get("agreement"),
            "termination_reason": negotiation.get("termination_reason"),
        }

    def analyze_negotiation(self, session_id: str) -> Dict[str, Any]:
        """Analyze negotiation dynamics and outcomes."""
        negotiation = self.negotiations.get(session_id)
        if not negotiation:
            return {"error": "Negotiation not found"}

        rounds = negotiation["rounds"]
        if not rounds:
            return {"error": "No rounds to analyze"}

        # Calculate concession patterns
        seller_concessions = []
        buyer_concessions = []

        for i, r in enumerate(rounds):
            if i == 0:
                continue
            prev_round = rounds[i - 1]

            if r.seller_offer and prev_round.seller_offer:
                seller_concessions.append(
                    (prev_round.seller_offer.price - r.seller_offer.price) / prev_round.seller_offer.price
                )

            if r.buyer_offer and prev_round.buyer_offer:
                buyer_concessions.append(
                    (r.buyer_offer.price - prev_round.buyer_offer.price) / prev_round.buyer_offer.price
                )

        return {
            "session_id": session_id,
            "total_rounds": len(rounds),
            "final_status": negotiation["status"],
            "seller_avg_concession": sum(seller_concessions) / len(seller_concessions) if seller_concessions else 0,
            "buyer_avg_concession": sum(buyer_concessions) / len(buyer_concessions) if buyer_concessions else 0,
            "concession_pattern": "balanced" if len(seller_concessions) == len(buyer_concessions) else "asymmetric",
            "efficiency": self._calculate_efficiency(negotiation),
        }

    def _calculate_efficiency(self, negotiation: Dict[str, Any]) -> float:
        """Calculate negotiation efficiency (closeness to optimal outcome)."""
        agreement = negotiation.get("agreement")
        if not agreement:
            return 0.0

        # Simple efficiency: how close to midpoint of BATNAs
        midpoint = (negotiation["seller_batna"] + negotiation["buyer_batna"]) / 2
        agreed_price = agreement["price"]

        if negotiation["buyer_batna"] == negotiation["seller_batna"]:
            return 1.0

        # Normalize distance from midpoint
        max_distance = (negotiation["buyer_batna"] - negotiation["seller_batna"]) / 2
        actual_distance = abs(agreed_price - midpoint)

        return max(0, 1 - (actual_distance / max_distance)) if max_distance > 0 else 1.0

    # ========================================================================
    # Batch Operations
    # ========================================================================

    def get_active_negotiations_for_party(self, party_id: int) -> List[Dict[str, Any]]:
        """Get all active negotiations for a party."""
        active = []
        for session_id, negotiation in self.negotiations.items():
            if negotiation["status"] == "active":
                if negotiation["seller_id"] == party_id or negotiation["buyer_id"] == party_id:
                    active.append({
                        "session_id": session_id,
                        "role": "seller" if negotiation["seller_id"] == party_id else "buyer",
                        "current_round": negotiation["current_round"],
                        "other_party": negotiation["buyer_id"] if negotiation["seller_id"] == party_id else negotiation["seller_id"],
                    })
        return active

    def terminate_negotiation(
        self,
        session_id: str,
        reason: str,
        terminated_by: int,
    ) -> Dict[str, Any]:
        """Force terminate a negotiation."""
        negotiation = self.negotiations.get(session_id)
        if not negotiation:
            return {"success": False, "error": "Negotiation not found"}

        if negotiation["seller_id"] != terminated_by and negotiation["buyer_id"] != terminated_by:
            return {"success": False, "error": "Not authorized to terminate"}

        negotiation["status"] = "terminated"
        negotiation["termination_reason"] = reason
        negotiation["updated_at"] = datetime.now(timezone.utc)

        if self.on_termination:
            self.on_termination(session_id, reason)

        return {
            "success": True,
            "session_id": session_id,
            "status": "terminated",
            "reason": reason,
        }
