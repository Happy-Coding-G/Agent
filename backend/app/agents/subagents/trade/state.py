"""
TradeAgent State Definitions

定义交易协商过程中的状态类型
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime


class TradeState(TypedDict, total=False):
    """交易协商状态 - Agent-First 架构

    支持新的交易目标执行流程：
    normalize_goal -> load_context -> evaluate -> select_mechanism -> execute -> settle
    """
    # =========================================================================
    # 输入参数（Agent-First 新增）
    # =========================================================================
    # 核心目标
    goal_type: str  # "sell_asset", "buy_asset", "price_inquiry"
    trade_goal: Dict[str, Any]  # TradeGoal 字典
    trade_constraints: Dict[str, Any]  # TradeConstraints 字典

    # 兼容性参数（旧接口）
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

    # =========================================================================
    # Agent-First 新增：执行上下文
    # =========================================================================
    # 用户配置
    user_config: Optional[Dict[str, Any]]
    autonomy_mode: Optional[str]  # "full_auto", "notify", "approval", "manual_step"

    # 市场与资产上下文
    asset_context: Optional[Dict[str, Any]]
    market_context: Optional[Dict[str, Any]]
    lineage_context: Optional[Dict[str, Any]]
    risk_context: Optional[Dict[str, Any]]

    # 机制选择结果
    mechanism_selection: Optional[Dict[str, Any]]  # MechanismSelection 字典
    engine_type: Optional[str]  # "simple", "event_sourced"
    selection_reason: Optional[str]

    # 审批状态
    approval_status: Optional[str]  # "pending", "approved", "rejected"
    approval_required: bool
    pending_decision: Optional[Dict[str, Any]]

    # 任务与会话关联
    task_id: Optional[str]  # AgentTask ID
    plan_id: Optional[str]  # TradeExecutionPlan ID

    # =========================================================================
    # 执行结果
    # =========================================================================
    success: bool
    error: Optional[str]
    result: Dict[str, Any]
    decisions: List[Dict[str, Any]]  # 决策日志

    # =========================================================================
    # 中间状态
    # =========================================================================
    current_step: Optional[str]  # 当前执行步骤
    asset_info: Optional[Dict[str, Any]]
    calculated_price: Optional[float]
    selected_mechanism: Optional[str]
    negotiation_id: Optional[str]
    session_id: Optional[str]

    # =========================================================================
    # 元数据
    # =========================================================================
    started_at: datetime
    completed_at: Optional[datetime]
    last_updated_at: Optional[datetime]
