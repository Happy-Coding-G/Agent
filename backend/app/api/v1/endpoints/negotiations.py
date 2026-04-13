from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.simple_negotiation_service import SimpleNegotiationService
from app.services.trade.negotiation_kernel import NegotiationKernel
from app.core.errors import ServiceError

router = APIRouter(prefix="/negotiations", tags=["negotiations"])


class CreateNegotiationRequest(BaseModel):
    listing_id: str = Field(..., description="商品上架ID")
    initial_offer: Optional[float] = Field(None, description="初始报价")
    max_rounds: int = Field(default=10, ge=1, le=50, description="最大协商轮数")
    message: Optional[str] = Field(None, description="初始消息")


class MakeOfferRequest(BaseModel):
    price: float = Field(..., gt=0, description="报价金额")
    message: Optional[str] = Field(None, description="附言")
    expected_version: Optional[int] = Field(None, description="乐观锁版本号")


class RespondOfferRequest(BaseModel):
    response: str = Field(..., description="响应类型: accept 或 reject")
    expected_version: Optional[int] = Field(None, description="乐观锁版本号")


class NegotiationResponse(BaseModel):
    success: bool
    negotiation_id: Optional[str] = None
    status: Optional[str] = None
    message: str
    data: dict = Field(default_factory=dict)


class NegotiationDetailResponse(BaseModel):
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
    version: int
    engine_type: str


@router.post("", response_model=NegotiationResponse)
async def create_negotiation(
    request: CreateNegotiationRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    status: Optional[str] = Query(None, description="筛选状态"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    try:
        service = SimpleNegotiationService(db)
        result = await service.get_negotiation_status(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
        )

        kernel = NegotiationKernel(db)
        state = await kernel.get_state(negotiation_id)
        engine_type = state.engine_type if state else "unknown"

        return NegotiationDetailResponse(
            **result,
            version=state.version if state else 1,
            engine_type=engine_type,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/offer", response_model=NegotiationResponse)
async def make_offer(
    negotiation_id: str,
    request: MakeOfferRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = SimpleNegotiationService(db)
        result = await service.make_offer(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
            price=request.price,
            message=request.message or "",
            expected_version=request.expected_version,
        )

        return NegotiationResponse(
            success=result.success,
            negotiation_id=negotiation_id,
            status=result.status.value if result.status else None,
            message=result.message,
            data={
                "current_round": result.current_round,
                "remaining_rounds": result.remaining_rounds,
            },
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/respond", response_model=NegotiationResponse)
async def respond_to_offer(
    negotiation_id: str,
    request: RespondOfferRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = SimpleNegotiationService(db)
        result = await service.respond_to_offer(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
            response=request.response,
            expected_version=request.expected_version,
        )

        return NegotiationResponse(
            success=result.success,
            negotiation_id=negotiation_id,
            status=result.status.value if result.status else None,
            message=result.message,
            data={
                "offer_accepted": result.offer_accepted,
                "new_price": result.new_price,
            },
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/{negotiation_id}/withdraw", response_model=NegotiationResponse)
async def withdraw_negotiation(
    negotiation_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = SimpleNegotiationService(db)
        result = await service.withdraw_negotiation(
            negotiation_id=negotiation_id,
            user_id=current_user.id,
        )

        return NegotiationResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/{negotiation_id}/version")
async def get_negotiation_version(
    negotiation_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        kernel = NegotiationKernel(db)
        state = await kernel.get_state(negotiation_id)

        if not state:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        return {
            "negotiation_id": negotiation_id,
            "version": state.version,
            "engine_type": state.engine_type,
            "status": state.status.value,
        }

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
