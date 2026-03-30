from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import Users


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Users | None:
        r = await self.db.execute(select(Users).where(Users.id == user_id))
        return r.scalars().first()

    async def create(self, user_key: str, display_name: str) -> Users:
        u = Users(user_key=user_key, display_name=display_name)
        self.db.add(u)
        await self.db.flush()
        return u

