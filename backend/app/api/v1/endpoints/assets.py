from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.core.errors import ServiceError
from app.db.models import Users
from app.db.session import get_db
from app.schemas.schemas import AssetDetail, AssetGenerateRequest, AssetSummary
from app.services.asset_service import AssetService

router = APIRouter(prefix="/spaces/{space_id}/assets", tags=["Assets"])


@router.get("", response_model=list[AssetSummary])
async def list_assets(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await AssetService(db).list_assets(space_id, current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/{asset_id}", response_model=AssetDetail)
async def get_asset(
    space_id: str,
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await AssetService(db).get_asset(space_id, asset_id, current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/generate", response_model=AssetDetail, status_code=status.HTTP_201_CREATED)
async def generate_asset(
    space_id: str,
    req: AssetGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await AssetService(db).generate_asset(
            space_public_id=space_id,
            prompt=req.prompt,
            user=current_user,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
