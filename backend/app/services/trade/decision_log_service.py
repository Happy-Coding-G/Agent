"""
Decision Log Service - 决策日志服务

记录 Agent 做出关键决策的原因，用于：
1. 审计和合规
2. 决策解释
3. 模型改进
4. 问题排查
"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.schemas.trade_goal import DecisionLog

logger = logging.getLogger(__name__)


class DecisionLogService:
    """
    决策日志服务

    集中记录 Agent 的所有关键决策。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_decision(
        self,
        task_id: str,
        decision_type: str,
        decision: str,
        reason: str,
        context: Dict[str, Any],
        session_id: Optional[str] = None,
        alternatives_considered: Optional[List[str]] = None,
    ) -> DecisionLog:
        """
        记录决策

        Args:
            task_id: 任务ID
            decision_type: 决策类型
            decision: 决策内容
            reason: 决策原因
            context: 决策上下文
            session_id: 会话ID
            alternatives_considered: 考虑的替代方案

        Returns:
            DecisionLog
        """
        log = DecisionLog(
            decision_id=str(uuid.uuid4())[:32],
            task_id=task_id,
            session_id=session_id,
            decision_type=decision_type,
            decision=decision,
            reason=reason,
            context=context,
            alternatives_considered=alternatives_considered or [],
            created_at=datetime.utcnow(),
        )

        # TODO: 持久化到数据库
        # 目前先记录到日志
        logger.info(
            f"Decision logged: {decision_type}={decision}, "
            f"task={task_id}, reason={reason}"
        )

        return log

    async def log_mechanism_selection(
        self,
        task_id: str,
        mechanism: str,
        reason: str,
        goal_context: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> DecisionLog:
        """
        记录机制选择决策
        """
        return await self.log_decision(
            task_id=task_id,
            session_id=session_id,
            decision_type="mechanism_selection",
            decision=mechanism,
            reason=reason,
            context={
                "goal": goal_context,
                "selected_mechanism": mechanism,
            },
            alternatives_considered=["direct"],
        )

    async def log_price_acceptance(
        self,
        task_id: str,
        price: float,
        accepted: bool,
        reason: str,
        session_id: str,
    ) -> DecisionLog:
        """
        记录价格接受/拒绝决策
        """
        return await self.log_decision(
            task_id=task_id,
            session_id=session_id,
            decision_type="price_acceptance",
            decision="accept" if accepted else "reject",
            reason=reason,
            context={
                "price": price,
                "accepted": accepted,
            },
        )

    async def log_approval_trigger(
        self,
        task_id: str,
        trigger_reason: str,
        policy_applied: str,
        session_id: Optional[str] = None,
    ) -> DecisionLog:
        """
        记录审批触发决策
        """
        return await self.log_decision(
            task_id=task_id,
            session_id=session_id,
            decision_type="approval_trigger",
            decision="approval_required",
            reason=trigger_reason,
            context={
                "policy": policy_applied,
                "trigger": trigger_reason,
            },
        )

    async def get_task_decisions(
        self,
        task_id: str,
    ) -> List[DecisionLog]:
        """
        获取任务的所有决策

        Args:
            task_id: 任务ID

        Returns:
            List[DecisionLog]
        """
        # TODO: 从数据库查询
        return []

    async def get_session_decisions(
        self,
        session_id: str,
    ) -> List[DecisionLog]:
        """
        获取会话的所有决策

        Args:
            session_id: 会话ID

        Returns:
            List[DecisionLog]
        """
        # TODO: 从数据库查询
        return []


# ============================================================================
# 便捷函数
# ============================================================================

async def log_decision(
    db: AsyncSession,
    task_id: str,
    decision_type: str,
    decision: str,
    reason: str,
    **kwargs
) -> DecisionLog:
    """便捷函数：记录决策"""
    service = DecisionLogService(db)
    return await service.log_decision(
        task_id=task_id,
        decision_type=decision_type,
        decision=decision,
        reason=reason,
        **kwargs
    )
