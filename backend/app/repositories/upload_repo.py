from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models import Uploads


class UploadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        public_id: str,
        space_id: int,
        folder_id: int,
        filename: str,
        size_bytes: int,
        status: str,
        created_by: int,
        expected_object_key: str | None = None,
    ) -> Uploads:
        u = Uploads(
            public_id=public_id,
            space_id=space_id,
            folder_id=folder_id,
            filename=filename,
            size_bytes=size_bytes,
            status=status,
            created_by=created_by,
            expected_object_key=expected_object_key,
        )
        self.db.add(u)
        await self.db.flush()
        return u

    async def get_by_public_id(self, upload_id: str) -> Uploads | None:
        res = await self.db.execute(select(Uploads).where(Uploads.public_id == upload_id))
        return res.scalars().first()

