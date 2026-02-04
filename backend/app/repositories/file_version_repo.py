from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import FileVersions


class FileVersionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        public_id: str,
        file_id: int,
        version_no: int,
        object_key: str,
        size_bytes: int,
        created_by: int,
    ) -> FileVersions:
        v = FileVersions(
            public_id=public_id,
            file_id=file_id,
            version_no=version_no,
            object_key=object_key,
            size_bytes=size_bytes,
            created_by=created_by,
        )
        self.db.add(v)
        await self.db.flush()
        return v
