"""
工作流检查点服务 (Workflow Checkpointing)

用于保存和恢复 Agent 工作流的中间状态，支持：
- 工作流步骤的断点续传
- 长时间运行的 Agent 任务状态保持
- 错误恢复和重试
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentIntermediateResults
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)


class WorkflowCheckpointService:
    """
    工作流检查点服务

    管理 Agent 工作流的中间结果：
    - 保存步骤结果
    - 恢复工作流状态
    - 清理过期检查点

    使用方式:
        checkpoint = WorkflowCheckpointService(db_session)
        await checkpoint.save_step(task_id, "step1", {"result": "data"})
        state = await checkpoint.restore_workflow(task_id)
    """

    # 默认检查点过期时间（7天）
    DEFAULT_TTL_DAYS = 7

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_step(
        self,
        task_id: str,
        step_name: str,
        result_data: dict[str, Any],
        ttl_days: Optional[int] = None,
    ) -> AgentIntermediateResults:
        """
        保存工作流步骤结果

        Args:
            task_id: 任务 ID
            step_name: 步骤名称
            result_data: 结果数据
            ttl_days: 过期天数

        Returns:
            检查点记录
        """
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=ttl_days or self.DEFAULT_TTL_DAYS
        )

        # 查找现有检查点
        result = await self.db.execute(
            select(AgentIntermediateResults).where(
                and_(
                    AgentIntermediateResults.task_id == task_id,
                    AgentIntermediateResults.step_name == step_name,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # 更新现有检查点
            existing.result_data = result_data
            existing.expires_at = expires_at
            checkpoint = existing
        else:
            # 创建新检查点
            checkpoint = AgentIntermediateResults(
                id=snowflake_id(),
                result_id=f"chk_{snowflake_id()}",
                task_id=task_id,
                step_name=step_name,
                result_data=result_data,
                expires_at=expires_at,
            )
            self.db.add(checkpoint)

        await self.db.commit()
        await self.db.refresh(checkpoint)

        logger.debug(f"Saved checkpoint for task {task_id}, step {step_name}")
        return checkpoint

    async def get_step_result(
        self,
        task_id: str,
        step_name: str,
    ) -> Optional[dict[str, Any]]:
        """
        获取步骤结果

        Args:
            task_id: 任务 ID
            step_name: 步骤名称

        Returns:
            结果数据或 None
        """
        result = await self.db.execute(
            select(AgentIntermediateResults).where(
                and_(
                    AgentIntermediateResults.task_id == task_id,
                    AgentIntermediateResults.step_name == step_name,
                    AgentIntermediateResults.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        checkpoint = result.scalar_one_or_none()

        return checkpoint.result_data if checkpoint else None

    async def restore_workflow(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """
        恢复工作流状态

        Args:
            task_id: 任务 ID

        Returns:
            工作流状态字典
        """
        result = await self.db.execute(
            select(AgentIntermediateResults).where(
                and_(
                    AgentIntermediateResults.task_id == task_id,
                    AgentIntermediateResults.expires_at > datetime.now(timezone.utc),
                )
            ).order_by(AgentIntermediateResults.created_at)
        )

        checkpoints = result.scalars().all()

        state = {
            "task_id": task_id,
            "restored_at": datetime.now(timezone.utc).isoformat(),
            "steps": {},
            "completed_steps": [],
        }

        for checkpoint in checkpoints:
            state["steps"][checkpoint.step_name] = checkpoint.result_data
            state["completed_steps"].append(checkpoint.step_name)

        logger.info(f"Restored workflow {task_id} with {len(checkpoints)} steps")
        return state

    async def delete_checkpoints(self, task_id: str) -> int:
        """
        删除任务的所有检查点

        Args:
            task_id: 任务 ID

        Returns:
            删除数量
        """
        result = await self.db.execute(
            delete(AgentIntermediateResults).where(
                AgentIntermediateResults.task_id == task_id
            )
        )
        await self.db.commit()

        deleted = result.rowcount or 0
        logger.info(f"Deleted {deleted} checkpoints for task {task_id}")
        return deleted

    async def cleanup_expired(self, batch_size: int = 1000) -> int:
        """
        清理过期检查点

        Args:
            batch_size: 批量大小

        Returns:
            清理数量
        """
        result = await self.db.execute(
            delete(AgentIntermediateResults).where(
                AgentIntermediateResults.expires_at < datetime.now(timezone.utc)
            ).execution_options(synchronize_session=False)
        )
        await self.db.commit()

        deleted = result.rowcount or 0
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired checkpoints")
        return deleted

    async def get_checkpoint_stats(self) -> dict[str, Any]:
        """
        获取检查点统计

        Returns:
            统计信息
        """
        from sqlalchemy import func

        # 总检查点数
        total = await self.db.scalar(
            select(func.count(AgentIntermediateResults.id))
        )

        # 过期检查点数
        expired = await self.db.scalar(
            select(func.count(AgentIntermediateResults.id)).where(
                AgentIntermediateResults.expires_at < datetime.now(timezone.utc)
            )
        )

        # 按任务统计
        task_counts = await self.db.execute(
            select(
                AgentIntermediateResults.task_id,
                func.count(AgentIntermediateResults.id),
            ).group_by(AgentIntermediateResults.task_id)
        )

        return {
            "total_checkpoints": total or 0,
            "expired_checkpoints": expired or 0,
            "active_checkpoints": (total or 0) - (expired or 0),
            "tasks_with_checkpoints": len(task_counts.all()),
        }


class ResumableWorkflow:
    """
    可恢复工作流基类

    使用检查点服务实现断点续传功能。
    """

    def __init__(
        self,
        task_id: str,
        checkpoint_service: WorkflowCheckpointService,
    ):
        self.task_id = task_id
        self.checkpoint = checkpoint_service
        self._state: dict[str, Any] = {}
        self._completed_steps: set[str] = set()

    async def initialize(self) -> None:
        """初始化工作流状态"""
        restored = await self.checkpoint.restore_workflow(self.task_id)
        self._state = restored.get("steps", {})
        self._completed_steps = set(restored.get("completed_steps", []))

    def is_step_completed(self, step_name: str) -> bool:
        """检查步骤是否已完成"""
        return step_name in self._completed_steps

    async def run_step(
        self,
        step_name: str,
        step_func: callable,
        *args,
        **kwargs,
    ) -> Any:
        """
        执行工作流步骤（带检查点）

        Args:
            step_name: 步骤名称
            step_func: 步骤执行函数
            *args, **kwargs: 传递给步骤函数的参数

        Returns:
            步骤结果
        """
        # 检查是否已有结果
        if self.is_step_completed(step_name):
            logger.debug(f"Step {step_name} already completed, using checkpoint")
            return self._state.get(step_name)

        # 执行步骤
        result = await step_func(*args, **kwargs)

        # 保存检查点
        await self.checkpoint.save_step(
            task_id=self.task_id,
            step_name=step_name,
            result_data={"result": result, "timestamp": datetime.now(timezone.utc).isoformat()},
        )

        # 更新状态
        self._state[step_name] = result
        self._completed_steps.add(step_name)

        return result

    async def complete(self) -> None:
        """完成工作流，清理检查点"""
        await self.checkpoint.delete_checkpoints(self.task_id)
        logger.info(f"Workflow {self.task_id} completed, checkpoints cleaned up")
