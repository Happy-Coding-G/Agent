"""
任务队列管理 API
提供任务状态查询、取消、队列监控等功能
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.db.models import Users
from app.db.session import get_db
from app.core.task_manager import task_manager
from app.services.ingest_service import IngestService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Task Queue"])


@router.get("/tasks/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user: Users = Depends(get_current_user),
):
    """
    获取任务状态

    Args:
        task_id: Celery 任务 ID
    """
    try:
        status = task_manager.get_task_status(task_id)
        return status
    except Exception:
        logger.exception("Failed to get task status for task_id=%s", task_id)
        raise HTTPException(status_code=500, detail="Failed to get task status")


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    terminate: bool = True,
    current_user: Users = Depends(get_current_user),
):
    """
    取消任务

    Args:
        task_id: Celery 任务 ID
        terminate: 是否强制终止正在运行的任务
    """
    try:
        success = task_manager.revoke_task(task_id, terminate=terminate)
        if success:
            return {"status": "success", "message": f"Task {task_id} cancelled"}
        else:
            raise HTTPException(status_code=400, detail="Failed to cancel task")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to cancel task task_id=%s", task_id)
        raise HTTPException(status_code=500, detail="Failed to cancel task")


@router.get("/tasks/queue/stats")
async def get_queue_stats(
    current_user: Users = Depends(get_current_user),
):
    """
    获取队列统计信息（仅管理员）

    返回各队列的任务数量、worker 状态等
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        stats = task_manager.get_queue_stats()
        return {
            "status": "success",
            "stats": stats,
        }
    except Exception:
        logger.exception("Failed to get queue stats")
        raise HTTPException(status_code=500, detail="Failed to get queue stats")


@router.get("/tasks/active")
async def list_active_tasks(
    current_user: Users = Depends(get_current_user),
):
    """
    获取正在执行的任务列表（仅管理员）
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        tasks = task_manager.list_active_tasks()
        return {
            "status": "success",
            "tasks": tasks,
            "count": len(tasks),
        }
    except Exception:
        logger.exception("Failed to list active tasks")
        raise HTTPException(status_code=500, detail="Failed to list active tasks")


@router.post("/ingest-jobs/{ingest_id}/requeue")
async def requeue_ingest_job(
    ingest_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """
    重新入队 Ingest Job

    仅允许对 failed 或 cancelled 状态的任务重新提交到 Celery
    """
    try:
        service = IngestService(db)
        result = await service.requeue_job(ingest_id)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Requeue failed"))

        return {
            "status": "success",
            "message": f"Ingest job {ingest_id} requeued",
            "task_id": result.get("task_id"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to requeue ingest job ingest_id=%s", ingest_id)
        raise HTTPException(status_code=500, detail="Failed to requeue job")


@router.get("/ingest-jobs/{ingest_id}/status")
async def get_ingest_job_status(
    ingest_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """
    获取 Ingest Job 详细状态

    包括数据库状态和 Celery 任务状态
    """
    try:
        service = IngestService(db)
        status = await service.get_job_status(ingest_id)

        if "error" in status:
            raise HTTPException(status_code=404, detail=status["error"])

        return status
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get ingest job status ingest_id=%s", ingest_id)
        raise HTTPException(status_code=500, detail="Failed to get job status")


@router.post("/ingest-jobs/{ingest_id}/cancel")
async def cancel_ingest_job(
    ingest_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """
    取消 Ingest Job

    撤销 Celery 任务并更新数据库状态
    """
    try:
        service = IngestService(db)
        success = await service.cancel_job(ingest_id)

        if success:
            return {
                "status": "success",
                "message": f"Ingest job {ingest_id} cancelled",
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Failed to cancel job (may already be completed or not found)",
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to cancel ingest job ingest_id=%s", ingest_id)
        raise HTTPException(status_code=500, detail="Failed to cancel job")
