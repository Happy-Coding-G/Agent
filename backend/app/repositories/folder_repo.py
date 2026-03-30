from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func
from typing import Sequence

from app.db.models import Folders


class FolderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id_in_space(self, space_db_id: int, folder_id: int) -> Folders | None:
        res = await self.db.execute(
            select(Folders).where(
                Folders.space_id == space_db_id,
                Folders.id == folder_id,
                Folders.deleted_at.is_(None),
            )
        )
        return res.scalars().first()

    async def get_by_public_id_in_space(self, space_db_id: int, folder_public_id: str) -> Folders | None:
        res = await self.db.execute(
            select(Folders).where(
                Folders.space_id == space_db_id,
                Folders.public_id == folder_public_id,
                Folders.deleted_at.is_(None),
            )
        )
        return res.scalars().first()

    async def create(
        self,
        *,
        public_id: str,
        space_db_id: int,
        parent_id: int | None,
        name: str,
        path_cache: str,
        created_by: int,
    ) -> Folders:
        f = Folders(
            public_id=public_id,
            space_id=space_db_id,
            parent_id=parent_id,
            name=name,
            path_cache=path_cache,
            created_by=created_by,
        )
        self.db.add(f)
        await self.db.flush()
        return f

    async def update_descendant_paths_by_prefix(self, space_db_id: int, old_path: str, new_path: str) -> None:
        stmt = (
            update(Folders)
            .where(
                Folders.space_id == space_db_id,
                Folders.path_cache.like(f"{old_path}/%")
            )
            .values(path_cache=func.concat(new_path, func.substring(Folders.path_cache, len(old_path) + 1)))
        )
        await self.db.execute(stmt)

    async def list_all_in_space_not_deleted(self, space_db_id: int) -> Sequence[Folders]:
        res = await self.db.execute(
            select(Folders).where(Folders.space_id == space_db_id, Folders.deleted_at.is_(None))
        )
        return res.scalars().all()

