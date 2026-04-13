"""
Trade Goal Schemas - 交易目标标准定义

为 Agent-first 架构提供统一的输入对象。
用户提交的是目标，不是机制细节。
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, validator


class TradeIntent(str, Enum):
    """交易意图类型"""
    SELL_ASSET = "sell_asset"           # 出售资产
    BUY_ASSET = "buy_asset"             # 购买资产
    PRICE_INQUIRY = "price_inquiry"     # 价格查询
    MARKET_ANALYSIS = "market_analysis" # 市场分析


class AutonomyMode(str, Enum):
    """自治模式 - Agent 自主程度"""
    FULL_AUTO = "full_auto"             # 完全自动
    NOTIFY_BEFORE_ACTION = "notify"     # 行动前通知
    REQUIRE_APPROVAL = "approval"       # 需要审批
    MANUAL_STEP = "manual_step"         # 逐步手动


class ApprovalPolicy(str, Enum):
    """审批策略"""
    NONE = "none"                       # 无需审批
    PRICE_THRESHOLD = "price_threshold" # 价格阈值触发
    ALWAYS = "always"                   # 总是审批
    FIRST_TRANSACTION = "first_tx"      # 首次交易审批


class TradeGoal(BaseModel):
    """
    交易目标 - 用户提交的核心意图

    这是 Agent-first 架构的入口对象。
    用户描述的是"目标"，不是"实现方式"。
    """
    intent: TradeIntent = Field(
        ...,
        description="交易意图：sell_asset/buy_asset/price_inquiry"
    )
    asset_id: Optional[str] = Field(
        None,
        description="资产ID（出售或指定购买时使用）"
    )
    listing_id: Optional[str] = Field(
        None,
        description="上架ID（针对特定上架购买时使用）"
    )

    # 价格相关
    target_price: Optional[float] = Field(
        None,
        gt=0,
        description="目标价格（期望成交价）"
    )
    max_price: Optional[float] = Field(
        None,
        gt=0,
        description="最高可接受价格（购买时）"
    )
    min_price: Optional[float] = Field(
        None,
        gt=0,
        description="最低可接受价格（出售时）"
    )
    price_flexibility: float = Field(
        default=0.1,
        ge=0,
        le=1,
        description="价格弹性：0-1之间，越大越灵活"
    )

    # 时间相关
    deadline: Optional[datetime] = Field(
        None,
        description="交易截止时间"
    )
    urgency: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="紧急程度"
    )

    # 偏好
    preferred_mechanism: Optional[Literal["bilateral", "auction", "auto"]] = Field(
        default="auto",
        description="偏好的协商机制，auto 由 Agent 决定"
    )
    require_immediate_settlement: bool = Field(
        default=False,
        description="是否要求即时结算"
    )

    # 扩展字段
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="额外上下文信息"
    )

    @validator('min_price', 'max_price', 'target_price')
    def validate_prices(cls, v, values):
        """价格验证"""
        if v is not None and v <= 0:
            raise ValueError('价格必须大于0')
        return v


class TradeConstraints(BaseModel):
    """
    交易约束 - 用户设定的边界条件

    这些是硬性约束，Agent 必须遵守。
    """
    # 自治相关
    autonomy_mode: AutonomyMode = Field(
        default=AutonomyMode.NOTIFY_BEFORE_ACTION,
        description="Agent 自主程度"
    )
    approval_policy: ApprovalPolicy = Field(
        default=ApprovalPolicy.PRICE_THRESHOLD,
        description="审批策略"
    )
    approval_threshold: Optional[float] = Field(
        None,
        description="审批触发阈值（价格超出此值需要审批）"
    )

    # 风险控制
    max_rounds: int = Field(
        default=10,
        ge=1,
        le=50,
        description="最大协商轮数"
    )
    min_participants: int = Field(
        default=1,
        ge=1,
        description="最少参与者数量"
    )
    max_participants: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="最多参与者数量"
    )

    # 预算和数量
    budget_limit: Optional[float] = Field(
        None,
        gt=0,
        description="预算上限（购买时使用）"
    )
    quantity: int = Field(
        default=1,
        ge=1,
        description="交易数量"
    )

    # 对手方约束
    allowed_sellers: Optional[List[int]] = Field(
        None,
        description="允许的卖方ID列表（白名单）"
    )
    blocked_sellers: Optional[List[int]] = Field(
        None,
        description="禁止的卖方ID列表（黑名单）"
    )
    require_verified_counterparty: bool = Field(
        default=False,
        description="是否要求已验证的对手方"
    )

    # 时间约束
    max_negotiation_duration_minutes: int = Field(
        default=1440,  # 24小时
        ge=10,
        le=10080,  # 7天
        description="最大协商持续时间（分钟）"
    )
    response_timeout_seconds: int = Field(
        default=300,  # 5分钟
        ge=30,
        le=86400,
        description="响应超时时间（秒）"
    )

    # 扩展约束
    custom_rules: Dict[str, Any] = Field(
        default_factory=dict,
        description="自定义规则"
    )


class MechanismSelection(BaseModel):
    """
    机制选择结果

    由 mechanism_selection_policy 统一决策输出。
    """
    mechanism_type: Literal["bilateral", "auction", "direct"] = Field(
        ...,
        description="选择的机制类型"
    )
    engine_type: Literal["simple", "event_sourced"] = Field(
        ...,
        description="引擎类型：简化版或事件溯源版"
    )
    selection_reason: str = Field(
        ...,
        description="选择原因说明"
    )
    expected_participants: int = Field(
        ...,
        description="预期参与者数量"
    )
    requires_approval: bool = Field(
        ...,
        description="是否需要人工审批"
    )
    requires_full_audit: bool = Field(
        default=False,
        description="是否需要完整审计"
    )

    # 执行参数
    execution_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="执行参数"
    )


class TradeExecutionPlan(BaseModel):
    """
    交易执行计划

    Agent 根据目标和约束制定的执行计划。
    """
    plan_id: str = Field(..., description="计划ID")
    goal: TradeGoal = Field(..., description="交易目标")
    constraints: TradeConstraints = Field(..., description="交易约束")
    mechanism: MechanismSelection = Field(..., description="机制选择")

    # 执行步骤
    steps: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="执行步骤"
    )

    # 状态
    status: Literal["pending", "active", "completed", "failed", "cancelled"] = Field(
        default="pending",
        description="计划状态"
    )

    # 关联
    task_id: Optional[str] = Field(
        None,
        description="关联的 AgentTask ID"
    )
    session_id: Optional[str] = Field(
        None,
        description="关联的协商会话ID"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间"
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="更新时间"
    )


class TradeGoalRequest(BaseModel):
    """
    交易目标请求

    API 层接收的用户请求格式。
    """
    goal: TradeGoal = Field(..., description="交易目标")
    constraints: TradeConstraints = Field(
        default_factory=TradeConstraints,
        description="交易约束"
    )
    user_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="用户上下文"
    )


class TradeGoalResponse(BaseModel):
    """
    交易目标响应

    API 层返回的响应格式。
    """
    success: bool = Field(..., description="是否成功")
    task_id: Optional[str] = Field(
        None,
        description="创建的任务ID"
    )
    plan_id: Optional[str] = Field(
        None,
        description="执行计划ID"
    )
    status: str = Field(..., description="初始状态")
    message: str = Field(..., description="状态消息")
    estimated_duration_seconds: Optional[int] = Field(
        None,
        description="预计执行时长"
    )
    requires_immediate_attention: bool = Field(
        default=False,
        description="是否需要立即关注"
    )
    next_steps: List[str] = Field(
        default_factory=list,
        description="下一步操作提示"
    )


class TradeGoalStatus(BaseModel):
    """
    交易目标状态查询响应
    """
    task_id: str = Field(..., description="任务ID")
    plan_id: Optional[str] = Field(None, description="计划ID")
    goal_summary: str = Field(..., description="目标摘要")

    status: str = Field(..., description="当前状态")
    progress_percentage: int = Field(
        default=0,
        ge=0,
        le=100,
        description="进度百分比"
    )

    # 执行信息
    current_step: Optional[str] = Field(None, description="当前步骤")
    current_mechanism: Optional[str] = Field(None, description="当前机制")
    session_id: Optional[str] = Field(None, description="会话ID")

    # 决策信息
    decisions_made: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="已做出的决策"
    )
    pending_decisions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="待处理决策"
    )

    # 时间和结果
    created_at: datetime = Field(..., description="创建时间")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    estimated_completion: Optional[datetime] = Field(
        None,
        description="预计完成时间"
    )

    # 结果
    result: Optional[Dict[str, Any]] = Field(
        None,
        description="执行结果"
    )
    error: Optional[str] = Field(
        None,
        description="错误信息"
    )


class DecisionLog(BaseModel):
    """
    Agent 决策日志

    记录 Agent 做出关键决策的原因。
    """
    decision_id: str = Field(..., description="决策ID")
    task_id: str = Field(..., description="任务ID")
    session_id: Optional[str] = Field(None, description="会话ID")

    decision_type: Literal[
        "mechanism_selection",
        "price_acceptance",
        "price_rejection",
        "counter_offer",
        "approval_trigger",
        "timeout_action"
    ] = Field(..., description="决策类型")

    decision: str = Field(..., description="决策内容")
    reason: str = Field(..., description="决策原因")

    # 上下文
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="决策上下文"
    )
    alternatives_considered: List[str] = Field(
        default_factory=list,
        description="考虑的替代方案"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="决策时间"
    )


# ============================================================================
# 便捷函数
# ============================================================================

def create_sell_goal(
    asset_id: str,
    min_price: float,
    target_price: Optional[float] = None,
    deadline: Optional[datetime] = None,
    **kwargs
) -> TradeGoal:
    """便捷创建出售目标"""
    return TradeGoal(
        intent=TradeIntent.SELL_ASSET,
        asset_id=asset_id,
        min_price=min_price,
        target_price=target_price or min_price * 1.1,
        deadline=deadline,
        **kwargs
    )


def create_buy_goal(
    asset_id: Optional[str] = None,
    listing_id: Optional[str] = None,
    max_price: Optional[float] = None,
    target_price: Optional[float] = None,
    **kwargs
) -> TradeGoal:
    """便捷创建购买目标"""
    return TradeGoal(
        intent=TradeIntent.BUY_ASSET,
        asset_id=asset_id,
        listing_id=listing_id,
        max_price=max_price,
        target_price=target_price,
        **kwargs
    )
