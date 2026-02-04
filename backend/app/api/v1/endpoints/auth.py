from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.schemas import AuthRequest, AuthResponse, Token
from app.services.auth_service import AuthService
from app.core.errors import ServiceError

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
