"""
Ingest 任务定义
文档摄取的 Celery 任务
"""

import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.celery_config import celery_app
from app.core.config import settings
from app.db.session import _build_connect_args
from app.ai.ingest_pipeline import LangChainIngestPipeline

logger = logging.getLogger(__name__)


def _create_task_session_maker():
    """为每个 Celery 任务创建独立的 engine + session（避免 asyncpg 跨 event loop 问题）"""
    engine = create_async_engine(
        settings.ASYNC_DATABASE_URL,
        pool_pre_ping=True,
        connect_args=_build_connect_args(),
        poolclass=NullPool,
    )
    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    return engine, session_maker


@celery_app.task(
    bind=True,
    name="app.tasks.ingest_tasks.process_ingest_job",
    queue="ingest",
    max_retries=3,
    default_retry_delay=60,
    time_limit=3600,  # 1 小时
    soft_time_limit=3000,  # 50 分钟
)
def process_ingest_job(self, ingest_id: str):
    """
    处理 Ingest Job 的 Celery 任务

    Args:
        ingest_id: Ingest Job 的 UUID 字符串

    Returns:
        dict: 任务执行结果
    """
    logger.info(f"[Celery] Starting ingest job: {ingest_id}")

    try:
        # 使用异步执行
        import asyncio

        result = asyncio.run(_run_ingest_pipeline(ingest_id))

        logger.info(f"[Celery] Ingest job completed: {ingest_id}")
        return {
            "status": "success",
            "ingest_id": ingest_id,
            "result": result,
        }

    except Exception as exc:
        logger.exception(f"[Celery] Ingest job failed: {ingest_id}")

        # 检查是否应该重试
        if self.request.retries < self.max_retries:
            logger.info(
                f"[Celery] Retrying ingest job: {ingest_id} (attempt {self.request.retries + 1}/{self.max_retries})"
            )
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))

        # 超过重试次数，标记为失败
        asyncio.run(_mark_job_failed(ingest_id, str(exc)))

        return {
            "status": "failed",
            "ingest_id": ingest_id,
            "error": str(exc),
            "retries": self.request.retries,
        }


async def _run_ingest_pipeline(ingest_id: str):
    """运行 Ingest Pipeline"""
    engine, SessionLocal = _create_task_session_maker()
    try:
        async with SessionLocal() as session:
            try:
                pipeline = LangChainIngestPipeline(session)
                await pipeline.run(ingest_id)
                return {"success": True}
            except Exception as e:
                logger.exception(f"Pipeline execution failed: {e}")
                raise
    finally:
        await engine.dispose()


async def _mark_job_failed(ingest_id: str, error_message: str):
    """标记任务为失败状态"""
    engine, SessionLocal = _create_task_session_maker()
    try:
        async with SessionLocal() as session:
            try:
                from sqlalchemy import select
                from app.db.models import IngestJobs

                stmt = select(IngestJobs).where(
                    IngestJobs.ingest_id == uuid.UUID(ingest_id)
                )
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()

                if job:
                    job.status = "failed"
                    job.error = error_message
                    await session.commit()
                    logger.info(f"[Celery] Marked job as failed: {ingest_id}")
            except Exception as e:
                logger.exception(f"[Celery] Failed to mark job as failed: {e}")
                await session.rollback()
    finally:
        await engine.dispose()
