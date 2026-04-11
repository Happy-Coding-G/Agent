"""
TradeAgent State Definitions

定义交易协商过程中的状态类型
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime


class TradeState(TypedDict, total=False):
    """交易协商状态"""
    # 输入参数
    action: str  # "listing", "purchase", "auction_bid", "bilateral", "yield"
    space_public_id: str
    asset_id: str
    user_id: int
    user_role: str  # "seller", "buyer"

    # 交易参数
    pricing_strategy: str
    reserve_price: Optional[float]
    license_scope: Optional[List[str]]
    mechanism_hint: Optional[str]
    category: Optional[str]
    tags: Optional[List[str]]

    # 购买参数
    listing_id: Optional[str]
    requirements: Optional[Dict[str, Any]]
    budget_max: float
    bid_amount: Optional[float]

    # 执行结果
    success: bool
    error: Optional[str]
    result: Dict[str, Any]

    # 中间状态
    asset_info: Optional[Dict[str, Any]]
    calculated_price: Optional[float]
    selected_mechanism: Optional[str]
    negotiation_id: Optional[str]

    # 元数据
    started_at: datetime
    completed_at: Optional[datetime]
