"""
Trade Result Types - 交易领域结果对象

统一领域结果对象，避免 service 返回 endpoint 风格结构。

这是 Agent-first 架构的一部分：Service 层返回领域对象，
API 层负责转换为 HTTP 响应格式。
"""
from __future__ import annotations

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class NegotiationStatus(str, Enum):
    """协商状态"""
    PENDING = "pending"
    ACTIVE = "active"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SETTLED = "settled"


class MechanismType(str, Enum):
    """机制类型"""
    BILATERAL = "bilateral"
    AUCTION = "auction"
    CONTRACT_NET = "contract_net"
    DIRECT = "direct"


class EngineType(str, Enum):
    """引擎类型"""
    SIMPLE = "simple"
    EVENT_SOURCED = "event_sourced"


@dataclass
class NegotiationResult:
    """
    协商结果 - 领域对象

    统一的协商结果表示，不针对特定接口。
    """
    success: bool
    session_id: Optional[str] = None
    status: NegotiationStatus = NegotiationStatus.PENDING
    mechanism: MechanismType = MechanismType.BILATERAL
    engine: EngineType = EngineType.SIMPLE

    # 参与者
    seller_id: Optional[int] = None
    buyer_id: Optional[int] = None
    winner_id: Optional[int] = None

    # 价格信息
    current_price: Optional[float] = None
    agreed_price: Optional[float] = None
    starting_price: Optional[float] = None
    reserve_price: Optional[float] = None

    # 协商进展
    current_round: int = 0
    max_rounds: int = 10
    bid_count: int = 0

    # 消息和元数据
    message: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 时间戳
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "session_id": self.session_id,
            "status": self.status.value,
            "mechanism": self.mechanism.value,
            "engine": self.engine.value,
            "seller_id": self.seller_id,
            "buyer_id": self.buyer_id,
            "winner_id": self.winner_id,
            "current_price": self.current_price,
            "agreed_price": self.agreed_price,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "bid_count": self.bid_count,
            "message": self.message,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class OfferResult:
    """报价结果"""
    success: bool
    session_id: str
    offer_accepted: bool = False
    counter_offered: bool = False
    new_price: Optional[float] = None
    message: str = ""
    error: Optional[str] = None

    # 状态
    status: NegotiationStatus = NegotiationStatus.ACTIVE
    current_round: int = 0
    remaining_rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "offer_accepted": self.offer_accepted,
            "counter_offered": self.counter_offered,
            "new_price": self.new_price,
            "message": self.message,
            "error": self.error,
            "status": self.status.value,
            "current_round": self.current_round,
            "remaining_rounds": self.remaining_rounds,
        }


@dataclass
class BidResult:
    """出价结果（拍卖）"""
    success: bool
    session_id: str
    bid_sequence: int = 0
    amount: float = 0.0
    is_highest: bool = False
    is_winner: bool = False
    message: str = ""
    error: Optional[str] = None

    # 拍卖状态
    current_highest_bid: Optional[float] = None
    total_bids: int = 0
    auction_status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "bid_sequence": self.bid_sequence,
            "amount": self.amount,
            "is_highest": self.is_highest,
            "is_winner": self.is_winner,
            "message": self.message,
            "error": self.error,
            "current_highest_bid": self.current_highest_bid,
            "total_bids": self.total_bids,
            "auction_status": self.auction_status,
        }


@dataclass
class SessionState:
    """会话状态 - 统一状态表示"""
    session_id: str
    mechanism: MechanismType
    engine: EngineType
    status: NegotiationStatus

    # 配置
    seller_id: int
    buyer_id: Optional[int] = None
    listing_id: Optional[str] = None

    # 价格
    current_price: Optional[float] = None
    agreed_price: Optional[float] = None
    starting_price: Optional[float] = None
    reserve_price: Optional[float] = None

    # 进展
    current_round: int = 0
    max_rounds: int = 10
    bid_count: int = 0

    # 引擎特定
    version: int = 1  # 简化版乐观锁版本号
    shared_board: Dict[str, Any] = field(default_factory=dict)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)

    # 元数据
    engine_type: str = "simple"
    selection_reason: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mechanism": self.mechanism.value,
            "engine": self.engine.value,
            "status": self.status.value,
            "seller_id": self.seller_id,
            "buyer_id": self.buyer_id,
            "listing_id": self.listing_id,
            "current_price": self.current_price,
            "agreed_price": self.agreed_price,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "bid_count": self.bid_count,
            "version": self.version,
            "shared_board": self.shared_board,
            "engine_type": self.engine_type,
        }


@dataclass
class AuditEvent:
    """审计事件"""
    sequence: int
    event_type: str
    agent_id: int
    role: str
    payload: Dict[str, Any]
    timestamp: datetime
    vector_clock: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "type": self.event_type,
            "agent_id": self.agent_id,
            "role": self.role,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "vector_clock": self.vector_clock,
        }


@dataclass
class EngineCapabilities:
    """引擎能力描述"""
    engine_type: EngineType
    supports_concurrent_bids: bool
    supports_full_audit: bool
    optimistic_locking: bool
    max_participants: int
    best_for: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_type": self.engine_type.value,
            "supports_concurrent_bids": self.supports_concurrent_bids,
            "supports_full_audit": self.supports_full_audit,
            "optimistic_locking": self.optimistic_locking,
            "max_participants": self.max_participants,
            "best_for": self.best_for,
        }


# ============================================================================
# 便捷函数
# ============================================================================

def create_success_result(
    session_id: str,
    message: str = "Success",
    **kwargs
) -> NegotiationResult:
    """创建成功结果"""
    return NegotiationResult(
        success=True,
        session_id=session_id,
        message=message,
        **kwargs
    )


def create_error_result(
    error: str,
    session_id: Optional[str] = None,
) -> NegotiationResult:
    """创建错误结果"""
    return NegotiationResult(
        success=False,
        session_id=session_id,
        error=error,
        message=f"Error: {error}",
    )


# 引擎能力定义
BILATERAL_ENGINE_CAPABILITIES = EngineCapabilities(
    engine_type=EngineType.SIMPLE,
    supports_concurrent_bids=False,
    supports_full_audit=False,
    optimistic_locking=True,
    max_participants=2,
    best_for="1对1双边协商，低并发场景",
)

AUCTION_ENGINE_CAPABILITIES = EngineCapabilities(
    engine_type=EngineType.EVENT_SOURCED,
    supports_concurrent_bids=True,
    supports_full_audit=True,
    optimistic_locking=True,
    max_participants=1000,
    best_for="1对N拍卖，高并发场景",
)
