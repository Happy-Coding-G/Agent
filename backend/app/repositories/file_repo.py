from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import and_
from typing import Sequence

from app.db.models import Files


class FileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_in_space(self, space_id: int) -> Sequence[Files]:
        res = await self.db.execute(
            select(Files).where(and_(Files.space_id == space_id, Files.status == "active"))
        )
        return res.scalars().all()

    async def create(
        self,
        *,
        public_id: str,
        space_id: int,
        folder_db_id: int,
        name: str,
        size_bytes: int,
        created_by: int,
    ) -> Files:
        f = Files(
            public_id=public_id,
            space_id=space_id,
            folder_id=folder_db_id,
            name=name,
            size_bytes=size_bytes,
            created_by=created_by,
        )
        self.db.add(f)
        await self.db.flush()
        return f
