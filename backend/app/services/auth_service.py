import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.errors import ServiceError
from app.core.security.password import hash_password, verify_password
from app.core.security.jwt import create_access_token, safe_decode, TokenDecodeError
from app.repositories.user_repo import UserRepository
from app.repositories.user_auth_repo import UserAuthRepository
from app.repositories.space_repo import SpaceRepository
from app.schemas.schemas import AuthRequest, Token, TokenData
from app.db.models import Users


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
                    owner_user_id=new_user.id,
                    public_id=uuid.uuid4().hex
                )
                await self.auth.create(
                    user_id=new_user.id,
                    identity_type=req.identity_type,
                    identifier=req.identifier,
                    credential_hashed=hash_password(req.credential),
                )
            # begin() 正常退出会 commit
            return {"status": "OK", "user_id": new_user.id, "message": "User registered successfully"}

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

        access_token = create_access_token(data={"sub": str(user.id), "user_key": user.user_key})

        return Token(access_token=access_token, token_type="bearer")

    async def get_current_user(self, token: str) -> Users:
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

        user = await self.users.get_by_id(token_data.user_id)
        if not user:
            raise ServiceError(401, "Could not validate credentials")
        return user
