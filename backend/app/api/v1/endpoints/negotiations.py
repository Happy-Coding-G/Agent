"""
Negotiation API - 简化版协商接口

提供简洁的协商管理接口，基于 SimpleNegotiationService。
"""
from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.simple_negotiation_service import SimpleNegotiationService
from app.core.errors import ServiceError

router = APIRouter(prefix="/negotiations", tags=["negotiations"])


class CreateNegotiationRequest(BaseModel):
    """创建协商请求"""
    listing_id: str = Field(..., description="商品上架ID")
    initial_offer: Optional[float] = Field(None, description="初始报价")
    max_rounds: int = Field(default=10, ge=1, le=50, description="最大协商轮数")
    message: Optional[str] = Field(None, description="初始消息")


class MakeOfferRequest(BaseModel):
    """提交报价请求"""
    price: float = Field(..., gt=0, description="报价金额")
    message: Optional[str] = Field(None, description="附言")


class RespondOfferRequest(BaseModel):
    """响应报价请求"""
    response: str = Field(..., description="响应类型: accept 或 reject")


class NegotiationResponse(BaseModel):
    """协商响应"""
    success: bool
    negotiation_id: Optional[str] = None
    status: Optional[str] = None
    message: str
    data: dict = Field(default_factory=dict)


class NegotiationDetailResponse(BaseModel):
    """协商详情响应"""
    negotiation_id: str
    status: str
    listing_id: str
    buyer_id: int
    seller_id: int
    current_round: int
    current_price: Optional[float]
    agreed_price: Optional[float]
    expires_at: Optional[str]
    history: list
    price_evolution: list
    current_offer: Optional[dict]


@router.post("", response_model=NegotiationResponse)
async def create_negotiation(
    request: CreateNegotiationRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建协商会话

    发起与卖方的价格协商，可选择提交初始报价。
    系统会自动锁定诚意金（标价的5%或最低10元）。
    """
    try:
        service = SimpleNegotiationService(db)

        requirements = {
            "max_budget": request.initial_offer,
            "preferred_price": request.initial_offer,
            "max_rounds": request.max_rounds,
            "message": request.message,
        }

        result = await service.create_negotiation(
            buyer_id=current_user.id,
            listing_id=request.listing_id,
            requirements=requirements,
        )

        return NegotiationResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=List[dict])
async def list_my_negotiations(
    status: Optional[str] = Query(None, description="筛选状态: pending/active/accepted/rejected/cancelled"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取我的协商列表

    返回当前用户作为买方的所有协商。
    """
    try:
        service = SimpleNegotiationService(db)
        negotiations = await service.list_user_negotiations(
            user_id=current_user.id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return negotiations

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/{negotiation_id}", response_model=NegotiationDetailResponse)
async def get_negotiation_detail(
    negotiation_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取协商详情

    包括完整的历史记录和价格演进。
    """
    try:
        service = SimpleNegotiationService(db)
        result = await service.get_negotiation_status(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
        )
        return NegotiationDetailResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/offer", response_model=NegotiationResponse)
async def make_offer(
    negotiation_id: str,
    request: MakeOfferRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    提交报价

    在协商中提交新的价格报价。
    不能连续报价，需要等待对方响应。
    """
    try:
        service = SimpleNegotiationService(db)
        result = await service.make_offer(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
            price=request.price,
            message=request.message or "",
        )
        return NegotiationResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/respond", response_model=NegotiationResponse)
async def respond_to_offer(
    negotiation_id: str,
    request: RespondOfferRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    响应报价

    - accept: 接受当前报价，完成交易
    - reject: 拒绝当前报价
    """
    try:
        service = SimpleNegotiationService(db)
        result = await service.respond_to_offer(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
            response=request.response,
        )
        return NegotiationResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/withdraw", response_model=NegotiationResponse)
async def withdraw_negotiation(
    negotiation_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    撤回协商

    买方可以撤回进行中的协商，诚意金将全额退还。
    """
    try:
        service = SimpleNegotiationService(db)
        result = await service.withdraw_negotiation(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
        )
        return NegotiationResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
