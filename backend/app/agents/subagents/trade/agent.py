"""
TradeAgent - LangGraph-based Trading Agent (Direct Trade Mode)

直接交易模式：用户通过聊天输入购买/出售意图，
Agent 检索资产目录、评估匹配度后直接执行交易。

移除了协商和拍卖场景，流程大幅简化：
normalize_goal -> load_context -> evaluate -> execute_direct_trade -> settle
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Users
from app.core.errors import ServiceError
from app.services.base import SpaceAwareService
from app.services.asset_service import AssetService
from app.repositories.trade_repo import TradeRepository
from app.utils.sanitizer import redact_sensitive_info, compact_text
from app.services.skills import (
    PricingSkill,
    DataLineageSkill,
    MarketAnalysisSkill,
    PrivacyComputationSkill,
    AuditSkill,
)
from app.services.user_agent_service import UserAgentService, UserAgentSettings

# LangGraph imports
from app.agents.subagents.trade.graph import create_direct_trade_graph
from app.agents.subagents.trade.state import TradeState

# Agent-First imports
from app.schemas.trade_goal import (
    TradeGoal,
    TradeConstraints,
    MechanismSelection,
    TradeExecutionPlan,
)
from app.services.trade.mechanism_selection_policy import (
    select_mechanism,
    MarketContext,
    RiskContext,
)

logger = logging.getLogger(__name__)


class TradeAgent(SpaceAwareService):
    """
    TradeAgent - 直接交易模式

    核心设计：
    1. 使用 LangGraph 编排交易流程
    2. 用户输入意图 -> Agent 检索评估 -> 直接下单/上架
    3. 仅支持直接交易，移除协商和拍卖
    4. 集成 5 个 Skills 提供业务能力
    """

    PLATFORM_FEE_RATE = 0.05

    def __init__(self, db: AsyncSession, llm_client: Optional[Any] = None):
        super().__init__(db)
        self.assets = AssetService(db)
        self.repo = TradeRepository(db)
        self.user_agent_service = UserAgentService(db)
        self.skills = self._init_skills()
        # 创建 LangGraph 实例（直接交易图）
        self.graph = create_direct_trade_graph(db, self.skills)

    def _init_skills(self) -> Dict[str, Any]:
        """初始化 Skills"""
        return {
            "pricing": PricingSkill(self.db),
            "lineage": DataLineageSkill(self.db),
            "market": MarketAnalysisSkill(self.db),
            "privacy": PrivacyComputationSkill(self.db),
            "audit": AuditSkill(self.db),
        }

    async def _get_user_config(self, user_id: int) -> UserAgentSettings:
        """获取用户 Agent 配置"""
        return await self.user_agent_service.get_user_agent_settings(user_id)

    # ========================================================================
    # Agent-First API (Unified Trade Goal Execution)
    # ========================================================================

    async def execute_trade_goal(
        self,
        goal: TradeGoal,
        constraints: TradeConstraints,
        user: Users,
        task_id: Optional[str] = None,
        space_public_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> TradeExecutionPlan:
        """
        统一交易目标执行入口

        Agent 负责：
        1. 理解目标
        2. 检索匹配资产
        3. 评估价格/信誉
        4. 直接执行下单/上架
        5. 执行风控与结算
        """
        # 空间权限检查
        if space_public_id:
            await self._require_space(space_public_id, user)

        plan_id = str(uuid.uuid4())[:32]

        # 1. 构建初始状态
        initial_state: TradeState = {
            "goal_type": goal.intent.value,
            "trade_goal": goal.dict(),
            "trade_constraints": constraints.dict(),
            "task_id": task_id,
            "plan_id": plan_id,
            "user_id": user.id,
            "autonomy_mode": constraints.autonomy_mode.value,
            "approval_required": False,
            "current_step": "normalize_goal",
            "success": True,
            "result": {},
            "decisions": [],
            "started_at": datetime.now(timezone.utc),
        }

        if space_public_id:
            initial_state["space_public_id"] = space_public_id
        if session_id:
            initial_state["session_id"] = session_id

        # 2. 执行完整交易目标图
        try:
            final_state = await self.graph.ainvoke(initial_state)

            # 3. 同步交易状态到记忆层
            if session_id:
                await self._sync_trade_memory(session_id, user, space_public_id, final_state)

            # 4. 构建执行计划结果
            plan = TradeExecutionPlan(
                plan_id=plan_id,
                goal=goal,
                constraints=constraints,
                mechanism=MechanismSelection(
                    **final_state.get("mechanism_selection", {})
                ),
                status="completed" if final_state.get("success") else "failed",
                steps=final_state.get("decisions", []),
                task_id=task_id,
                session_id=session_id,
                result=final_state.get("result", {}),
            )

            return plan

        except Exception as e:
            logger.exception(f"Trade goal execution failed: {e}")
            return TradeExecutionPlan(
                plan_id=plan_id,
                goal=goal,
                constraints=constraints,
                mechanism=MechanismSelection(
                    mechanism_type="direct",
                    engine_type="simple",
                    selection_reason=f"Error during execution: {e}",
                    expected_participants=1,
                    requires_approval=True,
                ),
                status="failed",
                error=str(e),
                task_id=task_id,
                session_id=session_id,
            )

    async def run_goal(
        self,
        goal: TradeGoal,
        constraints: TradeConstraints,
        user: Users,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        便捷的 TradeGoal 执行接口
        """
        plan = await self.execute_trade_goal(
            goal=goal,
            constraints=constraints,
            user=user,
            session_id=session_id,
            **kwargs
        )

        return {
            "success": plan.status == "completed",
            "plan_id": plan.plan_id,
            "status": plan.status,
            "mechanism": plan.mechanism.dict() if plan.mechanism else None,
            "result": plan.result,
            "error": plan.error,
        }

    # ========================================================================
    # High-Level API (Unified Interface via LangGraph)
    # ========================================================================

    async def run(
        self,
        action: str,
        space_public_id: str,
        user: Users,
        session_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的 LangGraph 入口

        Args:
            action: 操作类型 ("listing", "purchase")
            space_public_id: Space ID
            user: 当前用户
            **kwargs: 其他参数

        Returns:
            执行结果
        """
        try:
            # 空间权限检查（purchase action 在 Legacy API 中传空字符串，跳过）
            if space_public_id:
                await self._require_space(space_public_id, user)

            initial_state: TradeState = {
                "action": action,
                "space_public_id": space_public_id,
                "user_id": user.id,
                "user_role": "seller" if action == "listing" else "buyer",
                "started_at": datetime.now(timezone.utc),
                "success": True,
                "result": {},
            }

            if session_id:
                initial_state["session_id"] = session_id
            initial_state.update(kwargs)

            final_state = await self.graph.ainvoke(initial_state)

            if session_id:
                await self._sync_trade_memory(session_id, user, space_public_id, final_state)

            return final_state.get("result", {
                "success": False,
                "error": "No result generated"
            })

        except Exception as e:
            logger.exception(f"TradeAgent run failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "agent_type": "trade",
            }

    # ========================================================================
    # Legacy API (保持向后兼容)
    # ========================================================================

    async def create_listing(
        self,
        space_public_id: str,
        asset_id: str,
        user: Users,
        pricing_strategy: str = "fixed",
        reserve_price: Optional[float] = None,
        license_scope: Optional[List[str]] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """创建资产上架"""
        return await self.run(
            action="listing",
            space_public_id=space_public_id,
            user=user,
            asset_id=asset_id,
            pricing_strategy=pricing_strategy,
            reserve_price=reserve_price,
            license_scope=license_scope,
            category=category,
            tags=tags,
        )

    async def initiate_purchase(
        self,
        user: Users,
        listing_id: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
        budget_max: float = 0.0,
    ) -> Dict[str, Any]:
        """发起购买请求"""
        return await self.run(
            action="purchase",
            space_public_id="",
            user=user,
            listing_id=listing_id,
            requirements=requirements,
            budget_max=budget_max,
        )

    # ========================================================================
    # Approval API
    # ========================================================================

    async def approve_trade_task(
        self,
        task_id: str,
        approved: bool,
        user: Users,
    ) -> Dict[str, Any]:
        """
        审批通过/拒绝交易任务

        更新 AgentTask 的 approval_granted 标记，若批准则重新加载之前状态并继续执行图。
        """
        from sqlalchemy import select
        from app.db.models import AgentTasks

        try:
            result = await self.db.execute(
                select(AgentTasks).where(AgentTasks.public_id == task_id)
            )
            task = result.scalar_one_or_none()
            if not task:
                return {"success": False, "error": "Task not found"}

            if task.created_by != user.id:
                return {"success": False, "error": "Not authorized to approve this task"}

            output_data = task.output_data or {}
            output_data["approval_granted"] = approved
            output_data["approval_decision_at"] = datetime.now(timezone.utc).isoformat()
            output_data["approved_by"] = user.id
            task.output_data = output_data

            if not approved:
                task.status = "cancelled"
                await self.db.commit()
                return {
                    "success": True,
                    "approved": False,
                    "message": "Trade task rejected by user",
                }

            previous_state = output_data.get("pending_state", {})
            previous_state["approval_granted"] = True
            previous_state["approval_required"] = False
            previous_state["result"] = previous_state.get("result", {})
            previous_state["result"]["approval_granted"] = True

            task.status = "running"
            await self.db.commit()

            final_state = await self.graph.ainvoke(previous_state)

            task.status = "completed" if final_state.get("success") else "failed"
            task_output = task.output_data or {}
            task_output["result"] = final_state.get("result")
            task_output["decisions"] = final_state.get("decisions", [])
            task.output_data = task_output
            await self.db.commit()

            return {
                "success": final_state.get("success", False),
                "approved": True,
                "result": final_state.get("result", {}),
            }

        except Exception as e:
            logger.exception(f"Trade task approval failed: {e}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """清理标签"""
        return [t.strip()[:32] for t in tags if t.strip()][:10]

    async def _sync_trade_memory(
        self,
        session_id: str,
        user: Users,
        space_public_id: Optional[str],
        final_state: Dict[str, Any],
    ) -> None:
        """将 Trade 状态同步到 L3 Redis 和 L4 PostgreSQL"""
        try:
            from app.services.memory import UnifiedMemoryService

            memory = UnifiedMemoryService(
                db=self.db,
                user_id=user.id,
                space_id=space_public_id,
                session_id=session_id,
            )

            # L3: trade_result
            trade_result = {
                "current_price": final_state.get("calculated_price"),
                "plan_id": final_state.get("plan_id"),
                "result": final_state.get("result"),
            }
            await memory.set_working_memory(
                key="trade_result",
                value=trade_result,
                session_id=session_id,
                agent_type="trade",
            )

            # L3: approval_state
            approval_state = {
                "approval_required": final_state.get("approval_required", False),
                "approval_status": final_state.get("approval_status"),
                "pending_decision": final_state.get("pending_decision"),
            }
            await memory.set_working_memory(
                key="approval_state",
                value=approval_state,
                session_id=session_id,
                agent_type="trade",
            )

            # L4: 记录关键事件
            if final_state.get("approval_required"):
                await memory.log_event(
                    event_type="approval_required",
                    payload={
                        "summary": "交易需要审批",
                        "plan_id": final_state.get("plan_id"),
                        "pending_decision": final_state.get("pending_decision"),
                    },
                    session_id=session_id,
                    agent_type="trade",
                )

            await memory.log_event(
                event_type="trade_executed",
                payload={
                    "summary": f"直接交易执行完成: {final_state.get('current_step')}",
                    "plan_id": final_state.get("plan_id"),
                    "success": final_state.get("success", False),
                    "result_summary": str(final_state.get("result", {}))[:200],
                },
                session_id=session_id,
                agent_type="trade",
            )

        except Exception as exc:
            logger.warning(f"Failed to sync trade memory: {exc}")
