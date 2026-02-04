from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import UserAuth


class UserAuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_identifier(self, identifier: str) -> UserAuth | None:
        r = await self.db.execute(select(UserAuth).where(UserAuth.identifier == identifier))
        return r.scalars().first()

    async def create(self, user_id: int, identity_type: str, identifier: str, credential_hashed: str) -> UserAuth:
        ua = UserAuth(
            user_id=user_id,
            identity_type=identity_type,
            identifier=identifier,
            credential=credential_hashed,
            verified=0,
        )
        self.db.add(ua)
        return ua
