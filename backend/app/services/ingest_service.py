"""
Ingest 服务
使用 Celery 任务队列处理文档摄取
"""

import logging
import uuid
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Documents, IngestJobs
from app.core.task_manager import task_manager

logger = logging.getLogger(__name__)


def get_minio_service():
    """延迟导入 MinIO 服务"""
    from app.utils.MinIO import minio_service

    return minio_service


class IngestService:
    """文档摄取服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _create_ingest_entities(
        self,
        *,
        space_id: int,
        file_id: int,
        file_version_id: int,
        object_key: str,
        source_url: str,
        created_by: int,
    ) -> Tuple[Documents, IngestJobs]:
        """创建 Ingest 实体（文档和任务）"""
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
        await self.db.flush()
        return doc, job

    async def create_ingest_job_from_version(
        self,
        *,
        space_id: int,
        file_id: int,
        file_version_id: int,
        object_key: str,
        created_by: int,
    ) -> Tuple[Documents, IngestJobs]:
        """
        从文件版本创建 Ingest Job

        创建文档记录和任务记录，然后提交到 Celery 任务队列
        """
        source_url = get_minio_service().get_download_url(object_key)

        if self.db.in_transaction():
            doc, job = await self._create_ingest_entities(
                space_id=space_id,
                file_id=file_id,
                file_version_id=file_version_id,
                object_key=object_key,
                source_url=source_url,
                created_by=created_by,
            )
        else:
            async with self.db.begin():
                doc, job = await self._create_ingest_entities(
                    space_id=space_id,
                    file_id=file_id,
                    file_version_id=file_version_id,
                    object_key=object_key,
                    source_url=source_url,
                    created_by=created_by,
                )

        # 提交到 Celery 任务队列
        try:
            task_id = self.submit_ingest_job(str(job.ingest_id))
            logger.info(
                f"[IngestService] Submitted job {job.ingest_id} to Celery, task_id: {task_id}"
            )
        except Exception as e:
            logger.error(f"[IngestService] Failed to submit job to Celery: {e}")
            # 即使提交失败，也返回 job，让上层决定如何处理

        return doc, job

    def submit_ingest_job(self, ingest_id: str, priority: str = "normal") -> str:
        """
        提交 Ingest Job 到 Celery 任务队列

        Args:
            ingest_id: Ingest Job ID
            priority: 任务优先级 (high, normal, low)

        Returns:
            str: Celery 任务 ID
        """
        return task_manager.submit_ingest_job(ingest_id, priority)

    async def get_job_status(self, ingest_id: str) -> dict:
        """
        获取 Ingest Job 状态

        返回包括：
        - 数据库中的状态
        - Celery 任务状态
        """
        from sqlalchemy import select

        # 查询数据库状态
        stmt = select(IngestJobs).where(IngestJobs.ingest_id == uuid.UUID(ingest_id))
        result = await self.db.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            return {"error": "Job not found"}

        # 查询 Celery 任务状态
        task_id = f"ingest_{ingest_id}"
        celery_status = task_manager.get_task_status(task_id)

        return {
            "ingest_id": ingest_id,
            "doc_id": str(job.doc_id),
            "db_status": job.status,
            "celery_status": celery_status,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }

    async def cancel_job(self, ingest_id: str) -> bool:
        """
        取消 Ingest Job

        尝试撤销 Celery 任务并更新数据库状态
        """
        from sqlalchemy import select

        # 查询任务
        stmt = select(IngestJobs).where(IngestJobs.ingest_id == uuid.UUID(ingest_id))
        result = await self.db.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            return False

        # 如果任务已完成或已失败，无需取消
        if job.status in ["completed", "failed", "cancelled"]:
            return False

        # 撤销 Celery 任务
        task_id = f"ingest_{ingest_id}"
        revoked = task_manager.revoke_task(task_id, terminate=True)

        if revoked:
            # 更新数据库状态
            job.status = "cancelled"
            await self.db.commit()
            logger.info(f"[IngestService] Cancelled job: {ingest_id}")

        return revoked


# 向后兼容的函数（用于代码迁移期）
def spawn_ingest_job(ingest_id: uuid.UUID):
    """
    提交 Ingest Job（向后兼容）

    使用 Celery 任务队列替代原来的 asyncio.create_task
    """
    try:
        task_id = task_manager.submit_ingest_job(str(ingest_id))
        logger.info(
            f"[spawn_ingest_job] Submitted job {ingest_id} to Celery, task_id: {task_id}"
        )
        return task_id
    except Exception as e:
        logger.error(f"[spawn_ingest_job] Failed to submit job: {e}")
        raise
