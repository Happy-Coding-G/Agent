from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Users
from app.schemas.schemas import SpaceCreate, SpaceResponse
from app.core.errors import ServiceError
from app.services.space_service import SpaceService
from app.api.deps.auth import get_current_user

router = APIRouter(prefix="/spaces", tags=["Spaces"])


@router.get("", response_model=List[SpaceResponse])
async def get_spaces(
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
    limit: int = 10,
    offset: int = 0
):
    return await SpaceService(db).list_spaces(current_user, limit, offset)


@router.post("", response_model=SpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_space(
    req: SpaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    try:
        return await SpaceService(db).create_space(current_user, req.name)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{spaceId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    spaceId: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    try:
        await SpaceService(db).delete_space(current_user, spaceId)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/{spaceId}/switch", response_model=SpaceResponse)
async def switch_space(
    spaceId: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    try:
        return await SpaceService(db).switch_space(current_user, spaceId)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
