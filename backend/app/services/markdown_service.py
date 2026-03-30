from __future__ import annotations

import asyncio
import datetime
import hashlib
import time
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ingest_pipeline import LangChainIngestPipeline
from app.ai.markdown_utils import normalize_markdown
from app.core.errors import ServiceError
from app.db.models import DocChunkEmbeddings, DocChunks, Documents, IngestJobs, Users
from app.repositories.space_repo import SpaceRepository
from app.services.base import SpaceAwareService, extract_title_from_text
from app.utils.MinIO import minio_service


class MarkdownDocumentService(SpaceAwareService):
    """Markdown 文档服务 - 继承 SpaceAwareService"""

    INGEST_WAIT_TIMEOUT_SECONDS = 30.0
    INGEST_WAIT_POLL_SECONDS = 0.5

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def _get_doc_in_space(self, space_db_id: int, doc_id: str) -> Documents:
        try:
            doc_uuid = uuid.UUID(str(doc_id))
        except ValueError as exc:
            raise ServiceError(400, "Invalid doc_id") from exc

        q = await self.db.execute(
            select(Documents).where(
                Documents.doc_id == doc_uuid, Documents.space_id == space_db_id
            )
        )
        doc = q.scalars().first()
        if not doc:
            raise ServiceError(404, "Markdown document not found")
        return doc

    async def list_documents(self, space_public_id: str, user: Users):
        space_db_id = await self._require_space(space_public_id, user)
        q = await self.db.execute(
            select(Documents)
            .where(Documents.space_id == space_db_id)
            .order_by(Documents.updated_at.desc())
        )
        docs = q.scalars().all()
        return [
            {
                "doc_id": str(doc.doc_id),
                "title": doc.title or f"Document {str(doc.doc_id)[:8]}",
                "status": doc.status,
                "updated_at": doc.updated_at,
                "content_hash": doc.content_hash,
                "chunk_count": await self._count_chunks(doc.doc_id),
            }
            for doc in docs
        ]

    async def get_document(self, space_public_id: str, doc_id: str, user: Users):
        space_db_id = await self._require_space(space_public_id, user)
        doc = await self._get_doc_in_space(space_db_id, doc_id)

        markdown_text = doc.markdown_text
        if (not markdown_text) and doc.markdown_object_key:
            markdown_text = self._read_markdown_from_minio(doc.markdown_object_key)

        return {
            "doc_id": str(doc.doc_id),
            "title": doc.title or f"Document {str(doc.doc_id)[:8]}",
            "status": doc.status,
            "markdown_text": markdown_text or "",
            "markdown_object_key": doc.markdown_object_key,
            "updated_at": doc.updated_at,
            "content_hash": doc.content_hash,
            "chunk_count": await self._count_chunks(doc.doc_id),
        }

    async def save_document(
        self,
        *,
        space_public_id: str,
        doc_id: str,
        markdown_text: str,
        title: str | None,
        user: Users,
    ):
        space_db_id = await self._require_space(space_public_id, user)
        doc = await self._get_doc_in_space(space_db_id, doc_id)
        await self._wait_for_ingest_idle(doc.doc_id)

        normalized = normalize_markdown(markdown_text)
        now = datetime.datetime.now(datetime.timezone.utc)

        doc.markdown_text = normalized
        doc.title = (
            (title or "").strip() or extract_title_from_text(normalized) or doc.title
        )
        doc.content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        doc.updated_at = now
        doc.status = "processing"
        doc.markdown_object_key = doc.markdown_object_key or self._default_markdown_key(
            doc
        )

        minio_service.upload_text(doc.markdown_object_key, normalized)
        await self.db.commit()

        try:
            await self._rebuild_vectors_for_document(doc)
        except Exception as exc:
            await self.db.rollback()
            failed_doc = await self._get_doc_in_space(space_db_id, doc_id)
            failed_doc.status = "failed"
            failed_doc.updated_at = datetime.datetime.now(datetime.timezone.utc)
            await self.db.commit()
            raise ServiceError(500, f"Failed to rebuild vectors: {exc}") from exc

        doc.status = "completed"
        doc.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await self.db.commit()

        return await self.get_document(space_public_id, doc_id, user)

    async def _count_chunks(self, doc_uuid: uuid.UUID) -> int:
        q = await self.db.execute(
            select(DocChunks.chunk_id).where(DocChunks.doc_id == doc_uuid)
        )
        return len(q.scalars().all())

    def _default_markdown_key(self, doc: Documents) -> str:
        if doc.object_key:
            return f"{doc.object_key}.md"
        return f"documents/{doc.doc_id}.md"

    def _read_markdown_from_minio(self, object_key: str) -> str:
        obj = minio_service.client.get_object(minio_service.bucket, object_key)
        try:
            return obj.read().decode("utf-8", errors="ignore")
        finally:
            obj.close()
            obj.release_conn()

    async def _rebuild_vectors_for_document(self, doc: Documents) -> None:
        chunk_id_rows = await self.db.execute(
            select(DocChunks.chunk_id).where(DocChunks.doc_id == doc.doc_id)
        )
        chunk_ids = chunk_id_rows.scalars().all()

        if chunk_ids:
            await self.db.execute(
                delete(DocChunkEmbeddings).where(
                    DocChunkEmbeddings.chunk_id.in_(chunk_ids)
                )
            )
        await self.db.execute(delete(DocChunks).where(DocChunks.doc_id == doc.doc_id))
        await self.db.commit()

        pipeline = LangChainIngestPipeline(self.db)
        chunk_docs = await pipeline._chunk_markdown(doc.markdown_text or "")
        if not chunk_docs:
            return
        await pipeline._store_chunks_and_embeddings(doc, chunk_docs)

    async def _wait_for_ingest_idle(self, doc_uuid: uuid.UUID) -> None:
        deadline = time.monotonic() + self.INGEST_WAIT_TIMEOUT_SECONDS
        while True:
            active = await self._has_active_ingest_job(doc_uuid)
            if not active:
                return
            if time.monotonic() >= deadline:
                raise ServiceError(
                    409, "Document is still ingesting, please retry shortly"
                )
            await asyncio.sleep(self.INGEST_WAIT_POLL_SECONDS)

    async def _has_active_ingest_job(self, doc_uuid: uuid.UUID) -> bool:
        q = await self.db.execute(
            select(IngestJobs.ingest_id).where(
                IngestJobs.doc_id == doc_uuid,
                IngestJobs.status.in_(("queued", "running")),
            )
        )
        return q.scalars().first() is not None
