"""
Auction Mechanism Implementation (拍卖机制)

Supports multiple auction types:
- English Auction: Ascending price, highest bidder wins
- Dutch Auction: Descending price, first acceptor wins
- Sealed Bid: Secret bids, highest wins at their bid
- Vickrey: Secret bids, highest wins at second-highest price
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class AuctionType(str, Enum):
    """Types of auctions supported."""
    ENGLISH = "english"          # 英式拍卖: ascending price
    DUTCH = "dutch"              # 荷兰式拍卖: descending price
    SEALED = "sealed"            # 密封拍卖
    VICKREY = "vickrey"          # 维克瑞拍卖 (second-price)


@dataclass
class AuctionLot:
    """Auction lot/item being auctioned."""
    lot_id: str
    seller_id: int
    asset_id: str
    asset_summary: Dict[str, Any]
    reserve_price: float          # 底价
    starting_price: float         # 起拍价
    price_increment: float        # 加价幅度
    auction_type: AuctionType
    start_time: datetime
    end_time: datetime
    auto_extend: bool = True      # 自动延长


@dataclass
class AuctionBid:
    """A bid in the auction."""
    bid_id: str
    lot_id: str
    bidder_id: int
    amount: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_proxy: bool = False        # 是否代理出价
    proxy_max: Optional[float] = None  # 代理出价上限


class AuctionMechanism:
    """
    Auction mechanism supporting multiple auction types.

    Features:
    - English auction with auto-extension
    - Dutch auction with price decrement
    - Sealed bid and Vickrey (second-price) auctions
    - Proxy bidding for English auctions
    """

    DUTCH_DECREMENT_RATE = 0.95   # 荷兰拍卖每次降价5%
    DUTCH_DECREMENT_INTERVAL = 30  # 每30秒降价一次
    EXTENSION_THRESHOLD = 60      # 最后60秒出价则延长
    EXTENSION_DURATION = 120      # 延长2分钟

    def __init__(self):
        self.lots: Dict[str, AuctionLot] = {}
        self.bids: Dict[str, List[AuctionBid]] = {}  # lot_id -> bids
        self.current_price: Dict[str, float] = {}    # lot_id -> current price
        self.current_winner: Dict[str, Optional[int]] = {}  # lot_id -> bidder_id

    # ========================================================================
    # Auction Setup
    # ========================================================================

    def create_auction(
        self,
        seller_id: int,
        asset_id: str,
        asset_summary: Dict[str, Any],
        auction_type: str,
        starting_price: float,
        reserve_price: Optional[float] = None,
        price_increment: float = 1.0,
        duration_minutes: int = 60,
        auto_extend: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a new auction.

        Args:
            seller_id: ID of the seller
            asset_id: Asset being auctioned
            asset_summary: Asset description
            auction_type: Type of auction (english, dutch, sealed, vickrey)
            starting_price: Starting bid price
            reserve_price: Minimum price to sell (optional)
            price_increment: Minimum bid increment
            duration_minutes: Auction duration
            auto_extend: Whether to auto-extend on late bids

        Returns:
            Auction creation result
        """
        lot_id = str(uuid.uuid4())[:32]

        try:
            auction_type_enum = AuctionType(auction_type)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid auction type: {auction_type}",
            }

        now = datetime.now(timezone.utc)

        # Dutch auction starts high and decreases
        if auction_type_enum == AuctionType.DUTCH:
            actual_starting = starting_price * 1.5  # Start 50% higher
        else:
            actual_starting = starting_price

        lot = AuctionLot(
            lot_id=lot_id,
            seller_id=seller_id,
            asset_id=asset_id,
            asset_summary=asset_summary,
            reserve_price=reserve_price or starting_price * 0.8,
            starting_price=actual_starting,
            price_increment=price_increment,
            auction_type=auction_type_enum,
            start_time=now,
            end_time=now + timedelta(minutes=duration_minutes),
            auto_extend=auto_extend,
        )

        self.lots[lot_id] = lot
        self.bids[lot_id] = []
        self.current_price[lot_id] = actual_starting
        self.current_winner[lot_id] = None

        logger.info(f"Auction created: {lot_id} ({auction_type})")

        return {
            "success": True,
            "lot_id": lot_id,
            "auction_type": auction_type,
            "starting_price": actual_starting,
            "reserve_price": lot.reserve_price,
            "start_time": lot.start_time.isoformat(),
            "end_time": lot.end_time.isoformat(),
            "status": "active",
        }

    # ========================================================================
    # Bidding
    # ========================================================================

    def place_bid(
        self,
        lot_id: str,
        bidder_id: int,
        amount: float,
        is_proxy: bool = False,
        proxy_max: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place a bid in an auction.

        Args:
            lot_id: ID of the auction lot
            bidder_id: ID of the bidder
            amount: Bid amount
            is_proxy: Whether this is a proxy bid (English only)
            proxy_max: Maximum proxy bid amount

        Returns:
            Bid result with current status
        """
        lot = self.lots.get(lot_id)
        if not lot:
            return {"success": False, "error": "Auction not found"}

        # Check if auction is active
        now = datetime.now(timezone.utc)
        if now < lot.start_time:
            return {"success": False, "error": "Auction has not started"}
        if now > lot.end_time:
            return {"success": False, "error": "Auction has ended"}

        # Check minimum bid based on auction type
        if lot.auction_type == AuctionType.ENGLISH:
            min_bid = self.current_price[lot_id] + lot.price_increment
            if amount < min_bid:
                return {
                    "success": False,
                    "error": f"Bid must be at least {min_bid}",
                    "current_price": self.current_price[lot_id],
                }

        elif lot.auction_type == AuctionType.DUTCH:
            # In Dutch auction, bid must be >= current price
            if amount < self.current_price[lot_id]:
                return {
                    "success": False,
                    "error": f"Bid must be at least current price {self.current_price[lot_id]}",
                }

        elif lot.auction_type in (AuctionType.SEALED, AuctionType.VICKREY):
            # Sealed bids: just need to be > 0 and >= reserve
            if amount <= 0:
                return {"success": False, "error": "Bid must be positive"}
            if amount < lot.reserve_price:
                return {"success": False, "error": f"Bid below reserve price {lot.reserve_price}"}

        # Create bid
        bid = AuctionBid(
            bid_id=str(uuid.uuid4())[:32],
            lot_id=lot_id,
            bidder_id=bidder_id,
            amount=amount,
            is_proxy=is_proxy,
            proxy_max=proxy_max,
        )

        self.bids[lot_id].append(bid)

        # Update auction state based on type
        if lot.auction_type == AuctionType.ENGLISH:
            self.current_price[lot_id] = amount
            self.current_winner[lot_id] = bidder_id

            # Check for auto-extension
            if lot.auto_extend and (lot.end_time - now).total_seconds() < self.EXTENSION_THRESHOLD:
                lot.end_time += timedelta(seconds=self.EXTENSION_DURATION)
                logger.info(f"Auction {lot_id} extended by {self.EXTENSION_DURATION}s")

        elif lot.auction_type == AuctionType.DUTCH:
            # Dutch auction ends immediately on first bid
            self.current_price[lot_id] = amount
            self.current_winner[lot_id] = bidder_id
            lot.end_time = now  # End auction

        logger.info(f"Bid placed: {bid.bid_id} on lot {lot_id} for {amount}")

        return {
            "success": True,
            "bid_id": bid.bid_id,
            "current_price": self.current_price[lot_id],
            "current_winner": self.current_winner[lot_id],
            "is_leading": self.current_winner[lot_id] == bidder_id,
            "auction_ending": lot.end_time.isoformat(),
        }

    def get_current_price(self, lot_id: str) -> Dict[str, Any]:
        """Get current price for Dutch auction (decrements over time)."""
        lot = self.lots.get(lot_id)
        if not lot:
            return {"error": "Auction not found"}

        if lot.auction_type != AuctionType.DUTCH:
            return {
                "lot_id": lot_id,
                "current_price": self.current_price[lot_id],
            }

        # Calculate Dutch auction current price
        now = datetime.now(timezone.utc)
        elapsed = (now - lot.start_time).total_seconds()
        intervals = int(elapsed / self.DUTCH_DECREMENT_INTERVAL)

        current = lot.starting_price * (self.DUTCH_DECREMENT_RATE ** intervals)
        current = max(current, lot.reserve_price)  # Don't go below reserve

        self.current_price[lot_id] = round(current, 2)

        return {
            "lot_id": lot_id,
            "current_price": self.current_price[lot_id],
            "reserve_price": lot.reserve_price,
            "next_decrement_in": max(0, self.DUTCH_DECREMENT_INTERVAL - (elapsed % self.DUTCH_DECREMENT_INTERVAL)),
        }

    # ========================================================================
    # Auction End & Settlement
    # ========================================================================

    def close_auction(self, lot_id: str, seller_id: int) -> Dict[str, Any]:
        """
        Close an auction and determine the winner.

        Args:
            lot_id: ID of the auction lot
            seller_id: ID of the seller (for authorization)

        Returns:
            Auction result with winner details
        """
        lot = self.lots.get(lot_id)
        if not lot:
            return {"success": False, "error": "Auction not found"}

        if lot.seller_id != seller_id:
            return {"success": False, "error": "Not authorized to close auction"}

        now = datetime.now(timezone.utc)

        # For sealed and Vickrey, allow early close
        if lot.auction_type not in (AuctionType.SEALED, AuctionType.VICKREY):
            if now < lot.end_time and self.current_winner[lot_id] is None:
                return {"success": False, "error": "Cannot close active auction early"}

        bids = self.bids.get(lot_id, [])

        if not bids:
            return {
                "success": False,
                "status": "no_bids",
                "message": "No bids received",
            }

        # Determine winner based on auction type
        if lot.auction_type == AuctionType.ENGLISH:
            winner = max(bids, key=lambda b: b.amount)
            final_price = winner.amount

        elif lot.auction_type == AuctionType.DUTCH:
            # First bidder wins at their bid
            winner = min(bids, key=lambda b: b.timestamp)
            final_price = winner.amount

        elif lot.auction_type == AuctionType.SEALED:
            # Highest bid wins at their bid
            winner = max(bids, key=lambda b: b.amount)
            final_price = winner.amount

        elif lot.auction_type == AuctionType.VICKREY:
            # Highest bid wins at second-highest price
            sorted_bids = sorted(bids, key=lambda b: b.amount, reverse=True)
            winner = sorted_bids[0]
            second_price = sorted_bids[1].amount if len(sorted_bids) > 1 else winner.amount
            final_price = second_price

        else:
            return {"success": False, "error": "Unknown auction type"}

        # Check reserve price
        if final_price < lot.reserve_price:
            return {
                "success": False,
                "status": "reserve_not_met",
                "highest_bid": final_price,
                "reserve_price": lot.reserve_price,
            }

        # Close the auction
        lot.end_time = now
        self.current_winner[lot_id] = winner.bidder_id
        self.current_price[lot_id] = final_price

        logger.info(f"Auction {lot_id} closed. Winner: {winner.bidder_id} at {final_price}")

        return {
            "success": True,
            "status": "completed",
            "lot_id": lot_id,
            "winner_id": winner.bidder_id,
            "final_price": final_price,
            "total_bids": len(bids),
            "auction_type": lot.auction_type.value,
        }

    def get_auction_status(self, lot_id: str) -> Dict[str, Any]:
        """Get current status of an auction."""
        lot = self.lots.get(lot_id)
        if not lot:
            return {"error": "Auction not found"}

        now = datetime.now(timezone.utc)
        bids = self.bids.get(lot_id, [])

        # Calculate time remaining
        time_remaining = (lot.end_time - now).total_seconds()
        is_active = time_remaining > 0 and now >= lot.start_time

        # Get bid history (without revealing sealed bids)
        if lot.auction_type in (AuctionType.SEALED, AuctionType.VICKREY) and is_active:
            bid_history = [{"anonymous": True, "timestamp": b.timestamp.isoformat()} for b in bids]
        else:
            bid_history = [
                {
                    "bidder_id": b.bidder_id,
                    "amount": b.amount,
                    "timestamp": b.timestamp.isoformat(),
                }
                for b in sorted(bids, key=lambda x: x.timestamp)
            ]

        return {
            "lot_id": lot_id,
            "auction_type": lot.auction_type.value,
            "status": "active" if is_active else "ended",
            "current_price": self.current_price[lot_id],
            "current_winner": self.current_winner[lot_id],
            "total_bids": len(bids),
            "time_remaining_seconds": max(0, time_remaining),
            "bid_history": bid_history,
            "reserve_price": lot.reserve_price,
            "seller_id": lot.seller_id,
        }

    def list_active_auctions(self) -> List[Dict[str, Any]]:
        """List all currently active auctions."""
        now = datetime.now(timezone.utc)
        active = []

        for lot_id, lot in self.lots.items():
            if lot.start_time <= now < lot.end_time:
                active.append({
                    "lot_id": lot_id,
                    "auction_type": lot.auction_type.value,
                    "current_price": self.current_price[lot_id],
                    "asset_summary": lot.asset_summary,
                    "time_remaining": (lot.end_time - now).total_seconds(),
                })

        return active
