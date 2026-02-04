from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthService
from app.core.errors import ServiceError

security = HTTPBearer()


async def get_current_user(auth=Depends(security), db: AsyncSession = Depends(get_db)):
    try:
        token = auth.credentials
        user = await AuthService(db).get_current_user(token)
        if db.in_transaction():
            await db.commit()
        return user
    except ServiceError as e:
        if db.in_transaction():
            await db.rollback()
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail,
            headers={"WWW-Authenticate": "Bearer"} if e.status_code == 401 else None
        )
