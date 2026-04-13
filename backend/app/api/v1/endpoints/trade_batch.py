"""
Trade Batch Operations API - 交易批量操作接口

提供批量操作功能，提高管理效率。
"""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.batch_operations_service import TradeBatchOperationsService
from app.core.errors import ServiceError

router = APIRouter(prefix="/batch", tags=["trade-batch"])


class BatchUpdatePriceRequest(BaseModel):
    """批量更新价格请求"""
    listing_ids: List[str] = Field(..., min_items=1, max_items=100, description="上架ID列表")
    new_price: Optional[float] = Field(None, gt=0, description="新价格（绝对值）")
    price_adjustment: Optional[float] = Field(None, ge=-0.5, le=0.5, description="价格调整百分比，如 0.1 = +10%")


class BatchCancelRequest(BaseModel):
    """批量取消请求"""
    listing_ids: List[str] = Field(..., min_items=1, max_items=100, description="上架ID列表")


class BatchWithdrawRequest(BaseModel):
    """批量撤回请求"""
    negotiation_ids: List[str] = Field(..., min_items=1, max_items=100, description="协商ID列表")


class BatchRejectRequest(BaseModel):
    """批量拒绝请求"""
    negotiation_ids: List[str] = Field(..., min_items=1, max_items=100, description="协商ID列表")


class BatchOperationResponse(BaseModel):
    """批量操作响应"""
    success: bool
    total: int
    succeeded: int
    failed: int
    results: List[dict]


class ListingsSummaryResponse(BaseModel):
    """上架汇总响应"""
    total: int
    active: int
    sold: int
    cancelled: int
    active_total_value: float
    active_listing_ids: List[str]


class NegotiationsSummaryResponse(BaseModel):
    """协商汇总响应"""
    total: int
    active: int
    accepted: int
    others: int
    active_negotiation_ids: List[str]


@router.get("/listings/summary", response_model=ListingsSummaryResponse)
async def get_my_listings_summary(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取我的上架汇总统计

    用于批量操作前的概览，显示各状态的数量和可操作的ID列表。
    """
    try:
        service = TradeBatchOperationsService(db)
        result = await service.get_listings_summary(current_user.id)
        return ListingsSummaryResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/listings/update-price", response_model=BatchOperationResponse)
async def batch_update_listing_prices(
    request: BatchUpdatePriceRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量更新上架价格

    可以指定新价格（绝对值）或价格调整百分比（相对值）。

    示例：
    ```json
    {
        "listing_ids": ["lst_abc", "lst_def"],
        "new_price": 1000
    }
    ```

    或按比例调整：
    ```json
    {
        "listing_ids": ["lst_abc", "lst_def"],
        "price_adjustment": -0.1  // 降价10%
    }
    ```
    """
    if request.new_price is None and request.price_adjustment is None:
        raise HTTPException(status_code=400, detail="Either new_price or price_adjustment must be provided")

    try:
        service = TradeBatchOperationsService(db)
        result = await service.batch_update_listing_prices(
            user_id=current_user.id,
            listing_ids=request.listing_ids,
            new_price=request.new_price,
            price_adjustment=request.price_adjustment,
        )

        return BatchOperationResponse(
            success=result.success,
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            results=result.results,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/listings/cancel", response_model=BatchOperationResponse)
async def batch_cancel_listings(
    request: BatchCancelRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量取消上架

    取消多个商品的上架状态。
    """
    try:
        service = TradeBatchOperationsService(db)
        result = await service.batch_cancel_listings(
            user_id=current_user.id,
            listing_ids=request.listing_ids,
        )

        return BatchOperationResponse(
            success=result.success,
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            results=result.results,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/negotiations/summary", response_model=NegotiationsSummaryResponse)
async def get_my_negotiations_summary(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取我的协商汇总统计

    用于批量操作前的概览。
    """
    try:
        service = TradeBatchOperationsService(db)
        result = await service.get_negotiations_summary(current_user.id)
        return NegotiationsSummaryResponse(**result)

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/negotiations/withdraw", response_model=BatchOperationResponse)
async def batch_withdraw_negotiations(
    request: BatchWithdrawRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量撤回协商

    撤回多个进行中的协商，诚意金将全额退还。
    """
    try:
        service = TradeBatchOperationsService(db)
        result = await service.batch_withdraw_negotiations(
            user_id=current_user.id,
            negotiation_ids=request.negotiation_ids,
        )

        return BatchOperationResponse(
            success=result.success,
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            results=result.results,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/negotiations/reject", response_model=BatchOperationResponse)
async def batch_reject_offers(
    request: BatchRejectRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量拒绝报价

    拒绝多个协商中的当前报价。
    """
    try:
        service = TradeBatchOperationsService(db)
        result = await service.batch_reject_offers(
            user_id=current_user.id,
            negotiation_ids=request.negotiation_ids,
        )

        return BatchOperationResponse(
            success=result.success,
            total=result.total,
            succeeded=result.succeeded,
            failed=result.failed,
            results=result.results,
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
