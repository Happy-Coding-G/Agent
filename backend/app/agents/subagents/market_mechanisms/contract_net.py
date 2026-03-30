"""
Contract Net Protocol Implementation (合同网机制)

Implements the classic Contract Net Protocol:
1. Announce - Manager announces task
2. Bid - Contractors submit bids
3. Award - Manager awards contract to best bidder
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

from app.agents.core import ContractNetState

logger = logging.getLogger(__name__)


@dataclass
class TaskAnnouncement:
    """Task announcement from manager (seller)."""
    announcement_id: str
    task_description: Dict[str, Any]
    eligibility_criteria: Dict[str, Any]
    deadline: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Bid:
    """Bid submission from contractor (buyer)."""
    bid_id: str
    announcement_id: str
    bidder_id: int
    bid_amount: float
    qualifications: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Award:
    """Contract award from manager to contractor."""
    award_id: str
    announcement_id: str
    bid_id: str
    awardee_id: int
    awarded_amount: float
    terms: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ContractNetProtocol:
    """
    Contract Net Protocol implementation.

    Roles:
    - Manager (Seller): Announces tasks, evaluates bids, awards contracts
    - Contractor (Buyer): Submits bids for announced tasks
    """

    def __init__(
        self,
        evaluation_strategy: str = "best_value",  # "best_value", "lowest_price", "first_valid"
        allow_multiple_awards: bool = False,
    ):
        self.evaluation_strategy = evaluation_strategy
        self.allow_multiple_awards = allow_multiple_awards
        self.announcements: Dict[str, TaskAnnouncement] = {}
        self.bids: Dict[str, List[Bid]] = {}  # announcement_id -> bids
        self.awards: Dict[str, List[Award]] = {}  # announcement_id -> awards

    # ========================================================================
    # Phase 1: Announce
    # ========================================================================

    def announce_task(
        self,
        manager_id: int,
        task_description: Dict[str, Any],
        eligibility_criteria: Optional[Dict[str, Any]] = None,
        deadline_minutes: int = 60,
    ) -> Dict[str, Any]:
        """
        Manager announces a task to potential contractors.

        Args:
            manager_id: ID of the task manager (seller)
            task_description: Description of the task/asset
            eligibility_criteria: Requirements for bidders
            deadline_minutes: Bidding deadline in minutes

        Returns:
            Announcement details
        """
        announcement_id = str(uuid.uuid4())[:32]
        deadline = datetime.now(timezone.utc).timestamp() + (deadline_minutes * 60)

        announcement = TaskAnnouncement(
            announcement_id=announcement_id,
            task_description={
                **task_description,
                "manager_id": manager_id,
            },
            eligibility_criteria=eligibility_criteria or {},
            deadline=datetime.fromtimestamp(deadline, timezone.utc),
        )

        self.announcements[announcement_id] = announcement
        self.bids[announcement_id] = []
        self.awards[announcement_id] = []

        logger.info(f"Task announced: {announcement_id} by manager {manager_id}")

        return {
            "success": True,
            "announcement_id": announcement_id,
            "phase": "bidding",
            "deadline": deadline,
            "eligibility_criteria": eligibility_criteria,
        }

    # ========================================================================
    # Phase 2: Bid
    # ========================================================================

    def submit_bid(
        self,
        announcement_id: str,
        bidder_id: int,
        bid_amount: float,
        qualifications: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Contractor submits a bid for an announced task.

        Args:
            announcement_id: ID of the task announcement
            bidder_id: ID of the bidding contractor (buyer)
            bid_amount: Bid price offered
            qualifications: Bidder's qualifications

        Returns:
            Bid submission result
        """
        # Validate announcement exists
        announcement = self.announcements.get(announcement_id)
        if not announcement:
            return {
                "success": False,
                "error": "Announcement not found",
            }

        # Check deadline
        if datetime.now(timezone.utc) > announcement.deadline:
            return {
                "success": False,
                "error": "Bidding deadline has passed",
            }

        # Check eligibility (basic validation)
        eligibility = announcement.eligibility_criteria
        if eligibility:
            min_reputation = eligibility.get("min_reputation")
            if min_reputation and qualifications:
                bidder_reputation = qualifications.get("reputation_score", 0)
                if bidder_reputation < min_reputation:
                    return {
                        "success": False,
                        "error": f"Bidder does not meet reputation requirement ({min_reputation})",
                    }

        # Create bid
        bid = Bid(
            bid_id=str(uuid.uuid4())[:32],
            announcement_id=announcement_id,
            bidder_id=bidder_id,
            bid_amount=bid_amount,
            qualifications=qualifications or {},
        )

        self.bids[announcement_id].append(bid)

        logger.info(f"Bid submitted: {bid.bid_id} for announcement {announcement_id}")

        return {
            "success": True,
            "bid_id": bid.bid_id,
            "status": "submitted",
            "current_bid_count": len(self.bids[announcement_id]),
        }

    def get_bids_for_announcement(
        self,
        announcement_id: str,
        manager_id: int,
    ) -> Dict[str, Any]:
        """
        Manager retrieves all bids for their announcement.

        Args:
            announcement_id: ID of the announcement
            manager_id: ID of the manager (for authorization)

        Returns:
            List of bids with evaluation
        """
        announcement = self.announcements.get(announcement_id)
        if not announcement:
            return {"success": False, "error": "Announcement not found"}

        # Verify manager owns this announcement
        if announcement.task_description.get("manager_id") != manager_id:
            return {"success": False, "error": "Not authorized to view bids"}

        bids = self.bids.get(announcement_id, [])

        # Evaluate and rank bids
        ranked_bids = self._rank_bids(bids)

        return {
            "success": True,
            "announcement_id": announcement_id,
            "total_bids": len(bids),
            "bidding_closed": datetime.now(timezone.utc) > announcement.deadline,
            "ranked_bids": [
                {
                    "rank": i + 1,
                    "bid_id": bid.bid_id,
                    "bidder_id": bid.bidder_id,
                    "amount": bid.bid_amount,
                    "qualifications": bid.qualifications,
                    "score": score,
                }
                for i, (bid, score) in enumerate(ranked_bids)
            ],
        }

    def _rank_bids(self, bids: List[Bid]) -> List[tuple[Bid, float]]:
        """Rank bids based on evaluation strategy."""
        if not bids:
            return []

        scored_bids = []

        for bid in bids:
            if self.evaluation_strategy == "lowest_price":
                # Lower is better
                score = 1.0 / (bid.bid_amount + 1)
            elif self.evaluation_strategy == "best_value":
                # Consider both price and qualifications
                price_score = 1.0 / (bid.bid_amount + 1)
                qual_score = bid.qualifications.get("quality_score", 0.5)
                reputation = bid.qualifications.get("reputation_score", 0.5)
                score = (price_score * 0.4) + (qual_score * 0.3) + (reputation * 0.3)
            else:  # first_valid
                score = float(len(scored_bids))

            scored_bids.append((bid, score))

        # Sort by score descending
        scored_bids.sort(key=lambda x: x[1], reverse=True)
        return scored_bids

    # ========================================================================
    # Phase 3: Award
    # ========================================================================

    def award_contract(
        self,
        announcement_id: str,
        bid_id: str,
        manager_id: int,
        terms: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Manager awards contract to a bidder.

        Args:
            announcement_id: ID of the announcement
            bid_id: ID of the bid to award
            manager_id: ID of the manager (for authorization)
            terms: Additional contract terms

        Returns:
            Award details
        """
        announcement = self.announcements.get(announcement_id)
        if not announcement:
            return {"success": False, "error": "Announcement not found"}

        # Verify manager owns this announcement
        if announcement.task_description.get("manager_id") != manager_id:
            return {"success": False, "error": "Not authorized to award"}

        # Find the bid
        bids = self.bids.get(announcement_id, [])
        selected_bid = None
        for bid in bids:
            if bid.bid_id == bid_id:
                selected_bid = bid
                break

        if not selected_bid:
            return {"success": False, "error": "Bid not found"}

        # Check if already awarded (unless multiple awards allowed)
        if not self.allow_multiple_awards and self.awards[announcement_id]:
            return {"success": False, "error": "Contract already awarded"}

        # Create award
        award = Award(
            award_id=str(uuid.uuid4())[:32],
            announcement_id=announcement_id,
            bid_id=bid_id,
            awardee_id=selected_bid.bidder_id,
            awarded_amount=selected_bid.bid_amount,
            terms=terms or {},
        )

        self.awards[announcement_id].append(award)

        logger.info(f"Contract awarded: {award.award_id} to bidder {award.awardee_id}")

        return {
            "success": True,
            "award_id": award.award_id,
            "awardee_id": award.awardee_id,
            "awarded_amount": award.awarded_amount,
            "terms": award.terms,
            "phase": "completed",
        }

    def reject_bid(
        self,
        announcement_id: str,
        bid_id: str,
        manager_id: int,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Manager rejects a bid with optional reason."""
        announcement = self.announcements.get(announcement_id)
        if not announcement:
            return {"success": False, "error": "Announcement not found"}

        if announcement.task_description.get("manager_id") != manager_id:
            return {"success": False, "error": "Not authorized"}

        # Mark bid as rejected (in a real system, we'd track this)
        logger.info(f"Bid {bid_id} rejected for announcement {announcement_id}: {reason}")

        return {
            "success": True,
            "bid_id": bid_id,
            "status": "rejected",
            "reason": reason,
        }

    # ========================================================================
    # Utilities
    # ========================================================================

    def get_protocol_state(self, announcement_id: str) -> Dict[str, Any]:
        """Get current state of a contract net protocol instance."""
        announcement = self.announcements.get(announcement_id)
        if not announcement:
            return {"error": "Announcement not found"}

        bids = self.bids.get(announcement_id, [])
        awards = self.awards.get(announcement_id, [])

        now = datetime.now(timezone.utc)

        return {
            "announcement_id": announcement_id,
            "phase": "awarding" if awards else "bidding" if now <= announcement.deadline else "evaluating",
            "total_bids": len(bids),
            "total_awards": len(awards),
            "deadline": announcement.deadline.isoformat(),
            "bidding_open": now <= announcement.deadline,
            "task_description": announcement.task_description,
        }
