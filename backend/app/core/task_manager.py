"""
任务队列管理器
封装 Celery 任务操作，提供简单的任务管理接口
"""

import logging
import uuid
from typing import Any, Optional
from datetime import datetime

from celery.result import AsyncResult
from celery.states import PENDING, SUCCESS, FAILURE, RETRY, STARTED

from app.core.celery_config import celery_app

logger = logging.getLogger(__name__)

# 任务状态映射
TASK_STATUS_MAP = {
    PENDING: "queued",
    STARTED: "running",
    SUCCESS: "completed",
    FAILURE: "failed",
    RETRY: "retrying",
}


class TaskManager:
    """任务管理器"""

    @staticmethod
    def submit_ingest_job(ingest_id: str, priority: str = "normal") -> str:
        """
        提交 Ingest Job 到任务队列

        Args:
            ingest_id: Ingest Job ID
            priority: 优先级 (high, normal, low)

        Returns:
            str: Celery 任务 ID
        """
        # 延迟导入避免循环依赖
        from app.tasks.ingest_tasks import process_ingest_job

        # 根据优先级选择队列
        queue = "ingest"
        if priority == "high":
            queue = "high_priority"

        # 提交任务
        task = process_ingest_job.apply_async(
            args=[ingest_id],
            queue=queue,
            task_id=f"ingest_{ingest_id}",  # 自定义任务 ID，便于追踪
        )

        logger.info(
            f"[TaskManager] Submitted ingest job: {ingest_id}, task_id: {task.id}"
        )
        return task.id

    @staticmethod
    def get_task_status(task_id: str) -> dict[str, Any]:
        """
        获取任务状态

        Args:
            task_id: Celery 任务 ID

        Returns:
            dict: 任务状态信息
        """
        result = AsyncResult(task_id, app=celery_app)

        status = TASK_STATUS_MAP.get(result.state, result.state)

        info = {
            "task_id": task_id,
            "status": status,
            "state": result.state,
        }

        # 如果任务完成，获取结果
        if result.ready():
            if result.successful():
                info["result"] = result.result
            else:
                info["error"] = str(result.result) if result.result else "Unknown error"

        # 获取任务元数据
        if result.info and isinstance(result.info, dict):
            info.update(
                {
                    k: v
                    for k, v in result.info.items()
                    if k not in ["children", "parent_id"]
                }
            )

        return info

    @staticmethod
    def revoke_task(task_id: str, terminate: bool = False) -> bool:
        """
        取消任务

        Args:
            task_id: Celery 任务 ID
            terminate: 是否强制终止正在运行的任务

        Returns:
            bool: 是否成功取消
        """
        try:
            celery_app.control.revoke(
                task_id,
                terminate=terminate,
                signal="SIGTERM" if terminate else None,
            )
            logger.info(f"[TaskManager] Revoked task: {task_id}, terminate={terminate}")
            return True
        except Exception as e:
            logger.error(f"[TaskManager] Failed to revoke task: {e}")
            return False

    @staticmethod
    def get_queue_stats() -> dict[str, Any]:
        """
        获取队列统计信息

        Returns:
            dict: 队列统计
        """
        try:
            # 使用 inspect 获取队列信息
            inspect = celery_app.control.inspect()

            stats = {
                "active": inspect.active() or {},
                "scheduled": inspect.scheduled() or {},
                "reserved": inspect.reserved() or {},
                "stats": inspect.stats() or {},
            }

            return stats
        except Exception as e:
            logger.error(f"[TaskManager] Failed to get queue stats: {e}")
            return {}

    @staticmethod
    def list_active_tasks() -> list[dict[str, Any]]:
        """
        获取正在执行的任务列表

        Returns:
            list: 任务列表
        """
        try:
            inspect = celery_app.control.inspect()
            active = inspect.active()

            tasks = []
            if active:
                for worker, worker_tasks in active.items():
                    for task in worker_tasks:
                        tasks.append(
                            {
                                "task_id": task.get("id"),
                                "name": task.get("name"),
                                "worker": worker,
                                "args": task.get("args"),
                                "kwargs": task.get("kwargs"),
                                "time_start": task.get("time_start"),
                            }
                        )

            return tasks
        except Exception as e:
            logger.error(f"[TaskManager] Failed to list active tasks: {e}")
            return []


# 全局任务管理器实例
task_manager = TaskManager()
