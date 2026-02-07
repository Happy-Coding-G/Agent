import asyncio
import uuid
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Documents, IngestJobs
from app.db.session import AsyncSessionLocal
from app.utils.MinIO import minio_service
from app.ai.ingest_pipeline import LangChainIngestPipeline


class IngestService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_ingest_job_from_version(
        self,
        *,
        space_id: int,
        file_id: int,
        file_version_id: int,
        object_key: str,
        created_by: int,
    ) -> Tuple[Documents, IngestJobs]:
        source_url = minio_service.get_download_url(object_key)
        async with self.db.begin():
            doc = Documents(
                space_id=space_id,
                file_id=file_id,
                file_version_id=file_version_id,
                graph_id=uuid.uuid4(),
                source_url=source_url,
                object_key=object_key,
                status="pending",
                created_by=created_by,
            )
            self.db.add(doc)
            await self.db.flush()

            job = IngestJobs(
                doc_id=doc.doc_id,
                status="queued",
            )
            self.db.add(job)
        return doc, job


def spawn_ingest_job(ingest_id: uuid.UUID):
    async def _runner():
        async with AsyncSessionLocal() as session:
            pipeline = LangChainIngestPipeline(session)
            await pipeline.run(ingest_id)

    asyncio.create_task(_runner())
