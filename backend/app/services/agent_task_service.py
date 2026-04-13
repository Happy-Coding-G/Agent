"""
Agent Task Service

Agent 任务管理服务
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import AgentTasks

logger = logging.getLogger(__name__)


class AgentTaskService:
    """Agent 任务服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_task(
        self,
        task_id: str,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[AgentTasks]:
        """
        更新任务状态

        Args:
            task_id: 任务公开ID
            status: 新状态
            output_data: 输出数据
            error: 错误信息

        Returns:
            更新后的任务对象
        """
        try:
            result = await self.db.execute(
                select(AgentTasks).where(AgentTasks.public_id == task_id)
            )
            task = result.scalar_one_or_none()

            if not task:
                logger.warning(f"Task {task_id} not found")
                return None

            task.status = status

            if output_data is not None:
                task.output_data = output_data

            if error is not None:
                task.error = error

            await self.db.commit()
            await self.db.refresh(task)

            return task

        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            await self.db.rollback()
            return None

    async def get_task(self, task_id: str) -> Optional[AgentTasks]:
        """
        获取任务

        Args:
            task_id: 任务公开ID

        Returns:
            任务对象
        """
        try:
            result = await self.db.execute(
                select(AgentTasks).where(AgentTasks.public_id == task_id)
            )
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None
