from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.schemas import AuthRequest, AuthResponse, Token
from app.services.auth_service import AuthService
from app.core.errors import ServiceError

router = APIRouter(prefix="/auth", tags=["Authentication"])

_bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(req: AuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await AuthService(db).register(req)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/login", response_model=Token)
async def login(req: AuthRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await AuthService(db).login(req)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: AsyncSession = Depends(get_db),
    auth=Depends(_bearer),
):
    """吊销当前 Bearer token，使其立即失效（黑名单机制）。"""
    if auth and auth.credentials:
        await AuthService(db).logout(auth.credentials)
