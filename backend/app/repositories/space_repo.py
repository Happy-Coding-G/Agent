from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from typing import Sequence

from app.db.models import Spaces


class SpaceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_owner(self, owner_user_id: int, limit: int, offset: int) -> Sequence[Spaces]:
        stmt = (
            select(Spaces)
            .where(Spaces.owner_user_id == owner_user_id)
            .limit(limit)
            .offset(offset)
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_by_public_id_for_owner(self, space_public_id: str, owner_user_id: int) -> Spaces | None:
        res = await self.db.execute(
            select(Spaces).where(Spaces.public_id == space_public_id, Spaces.owner_user_id == owner_user_id)
        )
        return res.scalars().first()

    async def count_by_owner(self, owner_user_id: int) -> int:
        res = await self.db.execute(
            select(func.count()).select_from(Spaces).where(Spaces.owner_user_id == owner_user_id)
        )
        return int(res.scalar() or 0)

    async def create(self, owner_user_id: int, public_id: str, name: str = "Default Space") -> Spaces:
        sp = Spaces(public_id=public_id, name=name, owner_user_id=owner_user_id)
        self.db.add(sp)
        await self.db.flush()
        return sp

    async def delete(self, space: Spaces) -> None:
        await self.db.delete(space)

