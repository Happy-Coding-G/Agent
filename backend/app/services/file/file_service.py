from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.errors import ServiceError
from app.core.config import settings
from app.db.models import Users
from app.repositories.space_repo import SpaceRepository
from app.repositories.folder_repo import FolderRepository
from app.repositories.file_repo import FileRepository
from app.repositories.file_version_repo import FileVersionRepository
from app.repositories.upload_repo import UploadRepository
from app.services.base import SpaceAwareService
from app.utils.MinIO import minio_service
from app.services.ingest_service import IngestService


class SpaceFileService(SpaceAwareService):
    """文件服务 - 继承 SpaceAwareService"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.folders = FolderRepository(db)
        self.files = FileRepository(db)
        self.versions = FileVersionRepository(db)
        self.uploads = UploadRepository(db)

    async def create_folder(
        self, space_public_id: str, parent_id: int | None, name: str, user: Users
    ):
        if "/" in name:
            raise ServiceError(400, "Folder name cannot contain '/'")

        try:
            async with self.db.begin():
                space_db_id = await self._require_space(space_public_id, user)

                path_cache = f"/{name}"

                if parent_id:
                    parent = await self.folders.get_by_id_in_space(
                        space_db_id, parent_id
                    )
                    if not parent:
                        raise ServiceError(
                            404, "Parent folder not found in current space"
                        )
                    path_cache = f"{parent.path_cache.rstrip('/')}/{name}"

                folder = await self.folders.create(
                    public_id=uuid.uuid4().hex[:32],
                    space_db_id=space_db_id,
                    parent_id=parent_id,
                    name=name,
                    path_cache=path_cache,
                    created_by=user.id,
                )
            return folder
        except IntegrityError:
            raise ServiceError(400, "Folder already exists at this level")

    async def rename_folder(
        self, space_public_id: str, folder_public_id: str, new_name: str, user: Users
    ):
        try:
            async with self.db.begin():
                space_db_id = await self._require_space(space_public_id, user)

                folder = await self.folders.get_by_public_id_in_space(
                    space_db_id, folder_public_id
                )
                if not folder:
                    raise ServiceError(404, "Folder not found")

                old_path = folder.path_cache
                parent_path = old_path.rsplit("/", 1)[0]
                new_path = (
                    f"{parent_path}/{new_name}" if parent_path else f"/{new_name}"
                )

                await self.folders.update_descendant_paths_by_prefix(
                    space_db_id, old_path, new_path
                )
                folder.name = new_name
                folder.path_cache = new_path
            return {"status": "OK", "new_path": new_path}
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(500, f"Update failed: {str(e)}")

    async def init_upload(
        self,
        space_public_id: str,
        folder_public_id: str,
        filename: str,
        size_bytes: int,
        user: Users,
    ):
        async with self.db.begin():
            space = await self.spaces.get_by_public_id_for_owner(
                space_public_id, user.id
            )
            if not space:
                raise ServiceError(404, "Space not found or permission denied")
            space_id = space.id

            folder = await self.folders.get_by_public_id_in_space(
                space_id, folder_public_id
            )
            if not folder and folder_public_id.isdigit():
                folder = await self.folders.get_by_id_in_space(
                    space_id, int(folder_public_id)
                )
            if not folder:
                raise ServiceError(404, "Folder not found in current space")

            upload_id = uuid.uuid4().hex[:32]
            object_key = f"s/{space.public_id}/{uuid.uuid4().hex[:16]}/{filename}"

            await self.uploads.create(
                public_id=upload_id,
                space_id=space_id,
                folder_id=folder.id,
                filename=filename,
                size_bytes=size_bytes,
                status="init",
                created_by=user.id,
                expected_object_key=object_key,
            )

        presigned_url = await minio_service.get_upload_url(object_key)
        return {
            "upload_id": upload_id,
            "upload_url": presigned_url,
            "presigned_url": presigned_url,
            "object_key": object_key,
        }

    async def complete_upload(
        self,
        space_public_id: str,
        upload_id: str,
        object_key: str,
        user: Users,
    ):
        ingest_service = IngestService(self.db)
        async with self.db.begin():
            space_db_id = await self._require_space(space_public_id, user)

            task = await self.uploads.get_by_public_id(upload_id)
            if not task or task.space_id != space_db_id:
                raise ServiceError(404, "Upload task not found")

            if task.expected_object_key and task.expected_object_key != object_key:
                raise ServiceError(400, "Object key mismatch")

            if task.status == "completed":
                raise ServiceError(409, "Upload already completed")

            new_file = await self.files.create(
                public_id=uuid.uuid4().hex[:32],
                space_id=space_db_id,
                folder_db_id=task.folder_id,
                name=task.filename,
                size_bytes=task.size_bytes,
                created_by=user.id,
            )
            new_version = await self.versions.create(
                public_id=uuid.uuid4().hex[:32],
                file_id=new_file.id,
                version_no=1,
                object_key=object_key,
                size_bytes=task.size_bytes,
                created_by=user.id,
            )
            new_file.current_version_id = new_version.id
            task.status = "completed"

            doc, job = await ingest_service.create_ingest_job_from_version(
                space_id=space_db_id,
                file_id=new_file.id,
                file_version_id=new_version.id,
                object_key=object_key,
                created_by=user.id,
            )

        # 事务已提交后再投递 Celery 任务，避免 worker 竞态读不到数据
        if settings.SYNC_INGEST:
            from app.ai.ingest_pipeline import LangChainIngestPipeline

            pipeline = LangChainIngestPipeline(self.db)
            await pipeline.run(str(job.ingest_id))
        else:
            try:
                ingest_service.submit_ingest_job(str(job.ingest_id))
            except Exception as e:
                from sqlalchemy import select
                from app.db.models import IngestJobs

                result = await self.db.execute(
                    select(IngestJobs).where(IngestJobs.ingest_id == job.ingest_id)
                )
                job_record = result.scalar_one_or_none()
                if job_record:
                    job_record.status = "failed"
                    job_record.error = str(e)
                    await self.db.commit()
                raise ServiceError(503, f"Failed to enqueue ingest job: {e}")

        return {
            "status": "OK",
            "public_id": new_file.public_id,
            "doc_id": str(doc.doc_id),
            "ingest_id": str(job.ingest_id),
        }

    async def get_space_tree(self, space_id: str, user: Users):
        space = await self.spaces.get_by_public_id_for_owner(space_id, user.id)
        if not space:
            raise ServiceError(404, "Space not found or permission denied")
        space_db_id = space.id

        all_folders = await self.folders.list_all_in_space_not_deleted(space_db_id)
        all_files = await self.files.list_active_in_space(space_db_id)

        nodes = {
            f.id: {
                "id": f.id,
                "public_id": f.public_id,
                "name": f.name,
                "path_cache": f.path_cache,
                "children": [],
                "files": [],
            }
            for f in all_folders
        }

        for file in all_files:
            if file.folder_id in nodes:
                nodes[file.folder_id]["files"].append(
                    {
                        "id": file.id,
                        "public_id": file.public_id,
                        "name": file.name,
                        "size_bytes": file.size_bytes,
                        "mime": file.mime,
                    }
                )

        tree = []
        for f in all_folders:
            node = nodes[f.id]
            if f.parent_id is None:
                tree.append(node)
            elif f.parent_id in nodes:
                nodes[f.parent_id]["children"].append(node)
            else:
                tree.append(node)

        return tree
