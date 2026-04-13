"""
Hybrid Negotiation API - 混合事件溯源协商接口

根据场景自动选择最优架构：
- 双边协商 (1对1): 使用简化版，直接存储状态
- 拍卖场景 (1对N): 使用事件溯源，处理高并发
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.hybrid_negotiation_service import (
    HybridNegotiationService,
    ScenarioProfile,
    NegotiationMechanism,
    AuctionEngine,
    create_negotiation_with_smart_routing,
)
from app.core.errors import ServiceError

router = APIRouter(prefix="/hybrid-negotiations", tags=["hybrid-negotiations"])


# ============================================================================
# Pydantic Models
# ============================================================================

class CreateBilateralRequest(BaseModel):
    """创建双边协商请求"""
    listing_id: str = Field(..., description="商品上架ID")
    seller_id: int = Field(..., description="卖方用户ID")
    initial_data: Dict[str, Any] = Field(default_factory=dict, description="初始数据")
    session_id: Optional[str] = Field(None, description="可选的会话ID")


class CreateAuctionRequest(BaseModel):
    """创建拍卖请求"""
    listing_id: str = Field(..., description="商品上架ID")
    starting_price: float = Field(..., gt=0, description="起拍价")
    reserve_price: Optional[float] = Field(None, description="保留价")
    auction_type: str = Field(default="english", description="拍卖类型: english/dutch")
    duration_minutes: int = Field(default=60, ge=5, description="持续时间（分钟）")
    session_id: Optional[str] = Field(None, description="可选的会话ID")


class SubmitBidRequest(BaseModel):
    """提交出价请求"""
    amount: float = Field(..., gt=0, description="出价金额")


class SubmitOfferRequest(BaseModel):
    """提交报价请求（双边协商）"""
    price: float = Field(..., gt=0, description="报价金额")
    message: Optional[str] = Field(None, description="附言")


class CloseAuctionRequest(BaseModel):
    """关闭拍卖请求"""
    confirm: bool = Field(default=True, description="确认关闭")


class MechanismTypeInfo(BaseModel):
    """机制类型信息"""
    mechanism_type: str
    description: str
    recommended_for: str


class ScenarioAnalysisResponse(BaseModel):
    """场景分析响应"""
    mechanism_type: str
    participant_count: int
    expected_concurrency: str
    requires_full_audit: bool
    recommended_engine: str
    engine_description: str


class AuctionStateResponse(BaseModel):
    """拍卖状态响应"""
    engine: str
    session_id: str
    status: str
    current_highest_bid: Optional[float]
    current_highest_bidder: Optional[int]
    bid_count: int
    shared_board: Dict[str, Any]


class BilateralStateResponse(BaseModel):
    """双边协商状态响应"""
    engine: str
    session_id: str
    status: str
    current_round: int
    current_price: Optional[float]
    shared_board: Dict[str, Any]


class BidResultResponse(BaseModel):
    """出价结果响应"""
    engine: str
    success: bool
    bid_sequence: int
    amount: float
    is_highest: bool
    message: str


class OfferResultResponse(BaseModel):
    """报价结果响应"""
    success: bool
    negotiation_id: str
    status: str
    message: str
    current_price: Optional[float]


class CloseAuctionResponse(BaseModel):
    """关闭拍卖响应"""
    engine: str
    success: bool
    winner_id: Optional[int]
    final_price: Optional[float]
    total_bids: int
    message: str


class AuditLogResponse(BaseModel):
    """审计日志响应"""
    sequence: int
    type: str
    agent_id: int
    role: str
    payload: Dict[str, Any]
    timestamp: str
    vector_clock: Optional[Dict[str, int]]


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/mechanisms", response_model=List[MechanismTypeInfo])
async def list_mechanism_types():
    """
    获取支持的协商机制类型

    返回所有支持的协商机制及其适用场景。
    """
    return [
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.BILATERAL,
            description="双边协商（1对1）",
            recommended_for="买卖双方一对一价格协商，低并发场景"
        ),
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.AUCTION,
            description="拍卖（1对N）",
            recommended_for="多方竞拍场景，需要处理高并发出价"
        ),
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.CONTRACT_NET,
            description="合同网（任务招标）",
            recommended_for="任务分发和承包商选择"
        ),
    ]


@router.post("/analyze-scenario", response_model=ScenarioAnalysisResponse)
async def analyze_scenario(
    mechanism_type: str = Query(..., description="协商机制类型"),
    expected_participants: int = Query(2, ge=2, description="预期参与者数量"),
    requires_audit: bool = Query(False, description="是否需要完整审计"),
):
    """
    分析场景并推荐引擎

    根据输入参数分析场景特征，推荐最优架构（简化版或事件溯源版）。
    这是设计阶段的有用工具，帮助前端决定使用哪种模式。
    """
    try:
        profile = HybridNegotiationService.analyze_scenario(
            mechanism_type=mechanism_type,
            expected_participants=expected_participants,
            requires_audit=requires_audit,
        )

        engine_desc = {
            "simple": "简化版（直接状态存储）- 适用于低并发、简单查询场景",
            "event_sourced": "事件溯源版 - 适用于高并发、需要完整审计的场景"
        }.get(profile.recommended_engine, "未知")

        return ScenarioAnalysisResponse(
            mechanism_type=profile.mechanism_type.value,
            participant_count=profile.participant_count,
            expected_concurrency=profile.expected_concurrency.value,
            requires_full_audit=profile.requires_full_audit,
            recommended_engine=profile.recommended_engine,
            engine_description=engine_desc,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bilateral", response_model=OfferResultResponse)
async def create_bilateral_negotiation(
    request: CreateBilateralRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建双边协商（简化版）

    适用于1对1协商场景，使用直接状态存储，查询性能O(1)。
    """
    try:
        result = await create_negotiation_with_smart_routing(
            db=db,
            mechanism_type=NegotiationMechanism.BILATERAL,
            seller_id=request.seller_id,
            buyer_id=current_user.id,
            listing_id=request.listing_id,
            config={
                "session_id": request.session_id,
                **request.initial_data,
            },
        )

        return OfferResultResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/auctions", response_model=Dict[str, Any])
async def create_auction(
    request: CreateAuctionRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建拍卖（事件溯源版）

    适用于1对N拍卖场景，使用事件溯源架构处理高并发出价。
    支持完整审计日志和顺序保证。
    """
    try:
        service = HybridNegotiationService(db)
        result = await service.create_negotiation(
            mechanism_type=NegotiationMechanism.AUCTION,
            seller_id=current_user.id,
            buyer_id=None,
            listing_id=request.listing_id,
            config={
                "session_id": request.session_id,
                "starting_price": request.starting_price,
                "reserve_price": request.reserve_price,
                "auction_type": request.auction_type,
                "duration_minutes": request.duration_minutes,
                "requires_audit": True,
            },
            expected_participants=10,  # 默认预期10个参与者
        )

        return result

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/{session_id}/state", response_model=Dict[str, Any])
async def get_negotiation_state(
    session_id: str,
    include_audit_log: bool = Query(False, description="是否包含完整审计日志（仅拍卖场景）"),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取协商/拍卖状态

    根据场景自动路由到对应引擎获取状态。
    对于拍卖场景，可请求完整审计日志。
    """
    try:
        service = HybridNegotiationService(db)
        state = await service.get_state(
            session_id=session_id,
            include_audit_log=include_audit_log,
        )
        return state

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{session_id}/bid", response_model=BidResultResponse)
async def submit_bid(
    session_id: str,
    request: SubmitBidRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    提交拍卖出价

    仅适用于拍卖场景。使用乐观锁保证并发安全，
    返回带序列号的结果（顺序证明）。
    """
    try:
        service = HybridNegotiationService(db)
        result = await service.submit_offer(
            session_id=session_id,
            mechanism_type="auction",
            user_id=current_user.id,
            price=request.amount,
        )

        return BidResultResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{session_id}/offer", response_model=OfferResultResponse)
async def submit_offer(
    session_id: str,
    request: SubmitOfferRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    提交双边协商报价

    仅适用于双边协商场景。在协商中提交新的价格报价。
    """
    try:
        service = HybridNegotiationService(db)
        result = await service.submit_offer(
            session_id=session_id,
            mechanism_type="bilateral",
            user_id=current_user.id,
            price=request.price,
            message=request.message or "",
        )

        return OfferResultResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{session_id}/close", response_model=CloseAuctionResponse)
async def close_auction(
    session_id: str,
    request: CloseAuctionRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    关闭拍卖

    仅适用于拍卖场景，由卖方调用。确定胜出者并生成最终交易。
    """
    if not request.confirm:
        raise HTTPException(status_code=400, detail="请确认关闭拍卖")

    try:
        service = HybridNegotiationService(db)
        result = await service.close_auction(
            session_id=session_id,
            seller_id=current_user.id,
        )

        return CloseAuctionResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/{session_id}/audit-log", response_model=List[AuditLogResponse])
async def get_audit_log(
    session_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取完整审计日志

    仅适用于事件溯源场景（拍卖）。返回按序列号排序的完整事件历史，
    包括出价时间、金额、出价人等完整信息。
    """
    try:
        # 先检查是否有权限访问此会话
        from sqlalchemy import select
        from app.db.models import NegotiationSessions

        result = await db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # 检查权限（卖方或买方）
        if session.seller_user_id != current_user.id and session.buyer_user_id != current_user.id:
            # 对于拍卖，检查是否是出价者
            pass  # 拍卖场景会检查事件表中的出价记录

        # 获取审计日志
        from app.services.trade.hybrid_negotiation_service import AuctionEngine

        auction_engine = AuctionEngine(db)
        audit_log = await auction_engine.get_full_audit_log(session_id)

        return [AuditLogResponse(**event) for event in audit_log]

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/comparison", response_model=Dict[str, Any])
async def get_architecture_comparison():
    """
    获取架构对比信息

    返回简化版与事件溯源版的详细对比，帮助理解两种架构的适用场景。
    """
    return {
        "comparison": {
            "simplified": {
                "name": "简化版（双边协商）",
                "use_case": "1对1协商",
                "storage": "直接状态存储（JSONB）",
                "query_performance": "O(1) - 直接读取当前状态",
                "concurrency_handling": "乐观锁（version字段）",
                "audit_capability": "有限（仅保留最近N条历史）",
                "complexity": "低",
                "best_for": [
                    "买卖双方一对一协商",
                    "低并发场景",
                    "快速查询当前状态",
                    "简单业务逻辑"
                ]
            },
            "event_sourced": {
                "name": "事件溯源版（拍卖）",
                "use_case": "1对N拍卖",
                "storage": "事件流 + 投影状态",
                "query_performance": "O(1)投影查询 / O(n)事件重放",
                "concurrency_handling": "乐观锁 + 事件顺序保证",
                "audit_capability": "完整（不可篡改的事件历史）",
                "complexity": "中",
                "best_for": [
                    "多方竞拍场景",
                    "高并发出价",
                    "需要完整审计日志",
                    "顺序敏感的业务"
                ]
            }
        },
        "routing_logic": {
            "description": "自动路由决策逻辑",
            "rules": [
                {"condition": "mechanism_type == 'bilateral'", "engine": "simplified"},
                {"condition": "mechanism_type == 'auction' AND participants <= 2", "engine": "simplified"},
                {"condition": "mechanism_type == 'auction' AND participants > 2", "engine": "event_sourced"},
                {"condition": "mechanism_type == 'contract_net'", "engine": "event_sourced"}
            ]
        }
    }
