import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.cache import cache_manager
from app.core.errors import ServiceError
from app.core.security.password import hash_password, verify_password
from app.core.security.jwt import create_access_token, safe_decode, TokenDecodeError
from app.repositories.user_repo import UserRepository
from app.repositories.user_auth_repo import UserAuthRepository
from app.repositories.space_repo import SpaceRepository
from app.schemas.schemas import AuthRequest, Token, TokenData
from app.db.models import Users

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.auth = UserAuthRepository(db)
        self.spaces = SpaceRepository(db)

    async def register(self, req: AuthRequest) -> dict:
        try:
            # 强一致：事务里做 user + space + auth
            async with self.db.begin():
                existed = await self.auth.get_by_identifier(req.identifier)
                if existed:
                    raise ServiceError(400, "Identifier already registered")
                new_user = await self.users.create(
                    user_key=str(uuid.uuid4()),
                    display_name=req.display_name or req.identifier,
                )
                await self.spaces.create(
                    owner_user_id=new_user.id, public_id=uuid.uuid4().hex
                )
                await self.auth.create(
                    user_id=new_user.id,
                    identity_type=req.identity_type,
                    identifier=req.identifier,
                    credential_hashed=hash_password(req.credential),
                )
            # 正常退出会 commit
            return {
                "status": "OK",
                "user_id": new_user.id,
                "message": "User registered successfully",
            }

        except ServiceError:
            raise
        except IntegrityError:
            raise ServiceError(400, "Identifier already registered")
        except OperationalError as e:
            raise ServiceError(
                503,
                "Database unavailable: cannot connect to PostgreSQL. "
                "Check DATABASE_URL/DB_SSLMODE and ensure PostgreSQL is reachable.",
            ) from e
        except Exception as e:
            msg = str(e).lower()
            if "winerror 1225" in msg or "connection refused" in msg:
                raise ServiceError(
                    503,
                    "Database unavailable: cannot connect to PostgreSQL. "
                    "Check DATABASE_URL/DB_SSLMODE and ensure PostgreSQL is reachable.",
                ) from e
            raise ServiceError(500, f"Registration failed: {str(e)}")

    async def login(self, req: AuthRequest) -> Token:
        auth_obj = await self.auth.get_by_identifier(req.identifier)
        if not auth_obj:
            raise ServiceError(401, "Invalid identifier or password")

        user = await self.users.get_by_id(auth_obj.user_id)
        if not user:
            raise ServiceError(401, "Invalid identifier or password")

        if not verify_password(req.credential, auth_obj.credential):
            raise ServiceError(401, "Invalid identifier or password")

        access_token = create_access_token(
            data={"sub": str(user.id), "user_key": user.user_key}
        )

        # 登录成功后缓存用户信息
        await cache_manager.set_user(user.id, user)
        logger.debug(f"User cached on login: {user.id}")

        return Token(access_token=access_token, token_type="bearer")

    async def get_current_user(self, token: str) -> Users:
        """获取当前用户 - 使用缓存优化"""
        try:
            payload = safe_decode(token)
        except TokenDecodeError:
            raise ServiceError(401, "Could not validate credentials")

        sub = payload.get("sub")
        if sub is None:
            raise ServiceError(401, "Could not validate credentials")

        try:
            token_data = TokenData(user_id=int(sub), user_key=payload.get("user_key"))
        except ValueError:
            raise ServiceError(401, "Could not validate credentials")

        user_id = token_data.user_id

        # 先尝试从缓存获取
        cached_user = await cache_manager.get_user(user_id)
        if cached_user is not None:
            # 验证 user_key 匹配（防止 token 被篡改）
            if cached_user.user_key == token_data.user_key:
                return cached_user
            else:
                # user_key 不匹配，缓存可能已过期，清除缓存
                await cache_manager.invalidate_user(user_id)
                logger.warning(
                    f"User cache invalidated due to user_key mismatch: {user_id}"
                )

        # 缓存未命中或验证失败，从数据库获取
        user = await self.users.get_by_id(user_id)
        if not user:
            raise ServiceError(401, "Could not validate credentials")

        # 缓存用户
        await cache_manager.set_user(user_id, user)
        logger.debug(f"User loaded from DB and cached: {user_id}")

        return user
