from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthService
from app.core.errors import ServiceError
from app.core.rate_limit import UserTier

security = HTTPBearer()


async def get_current_user(
    request: Request,
    auth=Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """
    获取当前用户并设置请求状态。

    包括:
    - 用户对象
    - 用户等级 (用于限流)
    """
    try:
        token = auth.credentials
        user = await AuthService(db).get_current_user(token)

        # 设置用户到请求状态
        request.state.user = user

        # 设置用户等级到请求状态 (用于限流)
        # 根据用户属性判断等级，这里简化处理
        # 实际应该根据用户的 subscription_tier 字段判断
        if hasattr(user, 'subscription_tier') and user.subscription_tier:
            tier_map = {
                'free': UserTier.FREE,
                'pro': UserTier.PRO,
                'enterprise': UserTier.ENTERPRISE,
                'internal': UserTier.INTERNAL,
            }
            request.state.user_tier = tier_map.get(
                user.subscription_tier.lower(),
                UserTier.FREE
            )
        else:
            # 默认免费用户
            request.state.user_tier = UserTier.FREE

        # Close the implicit read transaction opened by SQLAlchemy autobegin.
        # Service layer methods use explicit `session.begin()` blocks.
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
