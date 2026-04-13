"""
Trade Agent Worker V3 - Agent-First Autonomous Executor

Agent-First 架构中的自治执行器：
1. 将 AgentTasks 与 NegotiationSessions 串联
2. 自动推进下一轮协商
3. 审批等待和恢复
4. 超时处理
5. 自动接受、反报价、拒绝
6. 结束后结算触发

这是"Agent 自主完成交易协商任务"的关键执行层。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.services.trade.trade_negotiation_service import TradeNegotiationService
from app.services.trade.negotiation_kernel import NegotiationKernel
from app.services.trade.mechanism_selection_policy import select_mechanism
from app.services.trade.approval_policy_service import ApprovalPolicyService
from app.services.trade.decision_log_service import DecisionLogService
from app.db.models import UserAgentConfig, NegotiationSessions, AgentTasks
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class TradeAgentWorker:
    """
    交易Agent工作器V3 - Agent-First 自治执行器。

    Agent-First 架构中的关键执行层：
    1. 轮询活跃的 AgentTasks（trade 类型）
    2. 将任务与 NegotiationSessions 串联
    3. 自动推进协商回合
    4. 处理审批等待和恢复
    5. 超时处理
    6. 结算触发

    自治能力：
    - 自动选择机制（调用 mechanism_selection_policy）
    - 自动出价/报价（基于用户配置）
    - 自动接受/拒绝（基于价格阈值）
    - 自动触发审批（基于审批策略）
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.negotiation_service = TradeNegotiationService(db)
        self.negotiation_kernel = NegotiationKernel(db)
        self.decision_log = DecisionLogService(db)
        self.running = False
        self.worker_id = f"worker_{id(self)}"

    async def start(self, poll_interval: float = 5.0):
        """启动Worker。"""
        self.running = True
        logger.info(f"TradeAgentWorkerV2 {self.worker_id} started")

        while self.running:
            try:
                await self._process_new_events()
                await self._check_expired_negotiations()
            except Exception as e:
                logger.exception(f"Worker error: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """停止Worker。"""
        self.running = False
        logger.info(f"TradeAgentWorkerV2 {self.worker_id} stopped")

    async def _process_new_events(self):
        """
        处理新事件 - 事件驱动核心逻辑。

        流程：
        1. 查询活跃协商会话
        2. 对每个会话获取最新事件
        3. 根据状态决定是否需要自动响应
        4. 加载用户配置
        5. 执行自动决策
        """
        from sqlalchemy import select, and_

        # 查询活跃协商
        stmt = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.status.in_(["pending", "active"]),
                NegotiationSessions.expires_at > datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        if not sessions:
            return

        logger.debug(f"Processing {len(sessions)} active sessions")

        for session in sessions:
            try:
                await self._process_session(session)
            except Exception as e:
                logger.exception(f"Failed to process session {session.negotiation_id}: {e}")

    async def _process_session(self, session: NegotiationSessions):
        """处理单个协商会话。"""
        negotiation_id = session.negotiation_id

        # 获取当前状态投影
        state = await self.negotiation_service.state_projector.project_negotiation_state(
            negotiation_id
        )
        if not state:
            return

        # 确定当前轮到谁
        current_turn = state.current_turn
        if not current_turn:
            return

        # 确定当前应该行动的用户ID
        if current_turn == "seller":
            current_user_id = state.seller_id
        elif current_turn == "buyer":
            current_user_id = state.buyer_id
        else:
            return

        if not current_user_id:
            return

        # 获取最新事件（用于防止自循环）
        latest_events = await self.negotiation_service.event_store.get_events(
            negotiation_id, start_seq=0
        )
        if not latest_events:
            return

        latest_event = latest_events[-1]

        # 防止自循环：如果最新事件就是自己发出的，不响应
        if latest_event.agent_id == current_user_id:
            logger.debug(f"Skipping self-event for user {current_user_id}")
            return

        # 加载用户Agent配置
        config = await self.negotiation_service.get_or_create_agent_config(
            current_user_id, current_turn
        )

        # 检查是否自动处理
        if not config.use_llm_decision:
            logger.debug(f"User {current_user_id} is in manual mode, skipping")
            return

        # 根据事件类型和当前回合执行自动决策
        await self._execute_auto_decision(
            negotiation_id=negotiation_id,
            session=session,
            state=state,
            latest_event=latest_event,
            current_user_id=current_user_id,
            current_turn=current_turn,
            config=config,
        )

    async def _execute_auto_decision(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        latest_event,
        current_user_id: int,
        current_turn: str,
        config: UserAgentConfig,
    ):
        """执行自动决策。"""
        event_type = latest_event.event_type

        try:
            # 买方决策场景
            if current_turn == "buyer":
                if event_type in ["ANNOUNCE", "COUNTER"]:
                    # 评估并投标/出价
                    await self._buyer_respond_to_offer(
                        negotiation_id, session, state, current_user_id, config
                    )
                elif event_type == "OFFER" and latest_event.agent_role == "seller":
                    # 卖方出价，买方决定接受/拒绝/反报价
                    await self._buyer_evaluate_offer(
                        negotiation_id, state, current_user_id, config
                    )

            # 卖方决策场景
            elif current_turn == "seller":
                if event_type in ["BID", "OFFER"] and latest_event.agent_role == "buyer":
                    # 买方投标/出价，卖方决定接受/拒绝/反报价
                    await self._seller_evaluate_bid(
                        negotiation_id, session, state, latest_event, current_user_id, config
                    )

        except ServiceError as e:
            logger.warning(f"Auto-decision failed for {negotiation_id}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in auto-decision: {e}")

    async def _buyer_respond_to_offer(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        buyer_id: int,
        config: UserAgentConfig,
    ):
        """买方响应卖方公告或反报价。"""
        # 获取当前价格
        current_price = state.current_price / 100 if state.current_price else 0

        # 检查预算
        max_budget = config.auto_accept_threshold or 1000.0

        if current_price > max_budget * 1.2:
            logger.info(f"Buyer {buyer_id}: Price {current_price} exceeds budget")
            return

        # 自动出价
        if session.mechanism_type == "auction":
            # 拍卖：出价略高于当前价格
            bid_amount = min(current_price * 1.1, max_budget * 0.9)
            if bid_amount <= current_price:
                bid_amount = current_price + 1.0

            await self.negotiation_service.buyer_place_bid(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                amount=bid_amount,
                qualifications={"auto": True, "agent_config": config.pricing_strategy},
            )
            logger.info(f"Buyer {buyer_id}: Auto-placed bid {bid_amount}")

        else:
            # 协商：提出初始报价
            offer_price = min(current_price * 0.95, max_budget * 0.9)
            if offer_price <= 0:
                offer_price = max_budget * 0.8

            await self.negotiation_service.buyer_make_offer(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                price=offer_price,
                message="Auto-generated offer",
            )
            logger.info(f"Buyer {buyer_id}: Auto-made offer {offer_price}")

    async def _buyer_evaluate_offer(
        self,
        negotiation_id: str,
        state,
        buyer_id: int,
        config: UserAgentConfig,
    ):
        """买方评估卖方报价。"""
        current_price = state.current_price / 100 if state.current_price else 0
        max_budget = config.auto_accept_threshold or 1000.0

        # 检查轮数限制
        if state.current_round >= config.max_auto_rounds:
            logger.info(f"Buyer {buyer_id}: Max rounds reached, stopping auto-negotiation")
            return

        # 决策逻辑
        if current_price <= max_budget * 0.95:
            # 接受报价
            await self.negotiation_service.accept_offer_v2(
                negotiation_id=negotiation_id,
                agent_id=buyer_id,
            )
            logger.info(f"Buyer {buyer_id}: Auto-accepted offer at {current_price}")

        elif current_price <= max_budget:
            # 反报价
            counter_price = (current_price + max_budget) / 2
            await self.negotiation_service.buyer_make_offer(
                negotiation_id=negotiation_id,
                buyer_user_id=buyer_id,
                price=counter_price,
                message="Counter offer",
            )
            logger.info(f"Buyer {buyer_id}: Auto-countered with {counter_price}")

        else:
            logger.info(f"Buyer {buyer_id}: Offer {current_price} exceeds budget, no action")

    async def _seller_evaluate_bid(
        self,
        negotiation_id: str,
        session: NegotiationSessions,
        state,
        latest_event,
        seller_id: int,
        config: UserAgentConfig,
    ):
        """卖方评估买方投标/出价。"""
        # 获取报价
        payload = latest_event.payload
        bid_amount = payload.get("price", 0)
        reserve_price = (session.reserve_price or 0) / 100

        if bid_amount <= 0:
            bid_amount = state.current_price / 100 if state.current_price else 0

        # 决策逻辑
        if bid_amount >= reserve_price * (config.auto_accept_threshold or 0.95):
            # 自动接受
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="accept",
            )
            logger.info(f"Seller {seller_id}: Auto-accepted bid {bid_amount}")

        elif bid_amount >= reserve_price * (config.auto_counter_threshold or 0.8):
            # 自动反报价
            counter_amount = (bid_amount + reserve_price) / 2
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="counter",
                counter_amount=counter_amount,
            )
            logger.info(f"Seller {seller_id}: Auto-countered bid {bid_amount} with {counter_amount}")

        else:
            # 拒绝
            await self.negotiation_service.seller_respond_to_bid(
                negotiation_id=negotiation_id,
                seller_user_id=seller_id,
                response="reject",
            )
            logger.info(f"Seller {seller_id}: Auto-rejected bid {bid_amount}")

    async def _check_expired_negotiations(self):
        """检查并处理过期的协商。"""
        from sqlalchemy import select, and_

        stmt = select(NegotiationSessions).where(
            and_(
                NegotiationSessions.status.in_(["pending", "active"]),
                NegotiationSessions.expires_at < datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(stmt)
        expired = result.scalars().all()

        for session in expired:
            # 追加TIMEOUT事件
            try:
                await self.negotiation_service.event_store.append_event(
                    session_id=session.negotiation_id,
                    session_type="negotiation",
                    event_type="TIMEOUT",
                    agent_id=0,
                    agent_role="system",
                    payload={"reason": "negotiation_expired"},
                )
            except Exception as e:
                logger.warning(f"Failed to append TIMEOUT event: {e}")

            session.status = "terminated"
            logger.info(f"Negotiation {session.negotiation_id} expired and terminated")

        await self.db.commit()

    # =====================================================================
    # Agent-First: New Capabilities
    # =====================================================================

    async def _process_trade_tasks(self):
        """
        处理交易目标类型的 AgentTasks。

        Agent-First 核心逻辑：
        1. 查询 pending/running 的 trade 类型任务
        2. 关联到 NegotiationSessions
        3. 推进任务执行
        """
        stmt = select(AgentTasks).where(
            and_(
                AgentTasks.agent_type == "trade",
                AgentTasks.status.in_(["pending", "running"]),
            )
        )
        result = await self.db.execute(stmt)
        tasks = result.scalars().all()

        for task in tasks:
            try:
                await self._process_trade_task(task)
            except Exception as e:
                logger.exception(f"Failed to process trade task {task.public_id}: {e}")

    async def _process_trade_task(self, task: AgentTasks):
        """处理单个交易任务。"""
        input_data = task.input_data or {}

        # 检查是否有关联的协商会话
        session_id = task.negotiation_session_id

        if not session_id:
            # 需要创建新的协商会话
            await self._create_negotiation_for_task(task)
        else:
            # 推进现有协商
            await self._advance_negotiation(task, session_id)

    async def _create_negotiation_for_task(self, task: AgentTasks):
        """为任务创建协商会话。"""
        input_data = task.input_data or {}
        goal_data = input_data.get("goal", {})
        constraints_data = input_data.get("constraints", {})

        # 机制选择
        from app.schemas.trade_goal import TradeGoal, TradeConstraints

        goal = TradeGoal(**goal_data)
        constraints = TradeConstraints(**constraints_data)

        mechanism = select_mechanism(
            goal=goal,
            constraints=constraints,
        )

        # 审批检查
        approval = ApprovalPolicyService.evaluate_transaction(
            goal=goal,
            constraints=constraints,
        )

        if approval.requires_approval:
            # 更新任务状态为等待审批
            task.status = "pending_approval"
            task.output_data = {
                **task.output_data,
                "approval_required": True,
                "approval_reason": approval.reason,
                "mechanism": mechanism.dict(),
            }
            await self.db.commit()

            # 记录决策
            await self.decision_log.log_approval_trigger(
                task_id=task.public_id,
                trigger_reason=approval.reason,
                policy_applied=approval.policy_applied,
            )
            return

        # 创建协商会话
        try:
            result = await self.negotiation_kernel.create_session(
                mechanism=mechanism.mechanism_type,
                engine=mechanism.engine_type,
                seller_id=goal_data.get("seller_id", 0),
                listing_id=goal_data.get("listing_id"),
                buyer_id=task.created_by,
                starting_price=goal.target_price,
                reserve_price=goal_data.get("min_price") or goal_data.get("max_price"),
                expected_participants=mechanism.expected_participants,
                selection_reason=mechanism.selection_reason,
            )

            if result.success:
                task.negotiation_session_id = result.session_id
                task.status = "running"
                task.output_data = {
                    **task.output_data,
                    "session_created": True,
                    "session_id": result.session_id,
                    "mechanism": mechanism.dict(),
                }
                await self.db.commit()

                logger.info(f"Created session {result.session_id} for task {task.public_id}")
            else:
                task.status = "failed"
                task.error = result.error
                await self.db.commit()

        except Exception as e:
            logger.error(f"Failed to create session for task {task.public_id}: {e}")
            task.status = "failed"
            task.error = str(e)
            await self.db.commit()

    async def _advance_negotiation(self, task: AgentTasks, session_id: str):
        """推进协商会话。"""
        # 获取当前状态
        state = await self.negotiation_kernel.get_state(session_id)
        if not state:
            logger.warning(f"Session {session_id} not found for task {task.public_id}")
            return

        # 根据状态决定下一步
        if state.status.value in ["accepted", "rejected", "cancelled"]:
            # 协商结束，触发结算
            await self._finalize_task(task, state)
        elif state.status.value == "pending_approval":
            # 等待审批，不处理
            pass
        else:
            # 活跃状态，尝试自动推进
            await self._auto_advance_round(task, state)

    async def _auto_advance_round(self, task: AgentTasks, state):
        """自动推进一轮协商。"""
        # 获取用户配置
        user_config = await self.negotiation_service.get_or_create_agent_config(
            task.created_by, "buyer"
        )

        if not user_config.use_llm_decision:
            logger.debug(f"Task {task.public_id}: Manual mode, skipping auto-advance")
            return

        # 根据引擎类型选择推进策略
        if state.engine_type == "simple":
            await self._advance_bilateral(task, state, user_config)
        else:
            await self._advance_auction(task, state, user_config)

    async def _advance_bilateral(self, task: AgentTasks, state, config):
        """推进双边协商。"""
        # 简化实现：基于价格阈值自动决策
        current_price = state.current_price or 0

        # 获取约束
        input_data = task.input_data or {}
        constraints_data = input_data.get("constraints", {})
        max_budget = constraints_data.get("budget_limit", float("inf"))

        if current_price <= max_budget * 0.95:
            # 接受报价
            await self.negotiation_kernel.submit_offer(
                session_id=state.session_id,
                user_id=task.created_by,
                price=current_price,
                message="Auto-accepted by worker",
            )
            logger.info(f"Task {task.public_id}: Auto-accepted offer at {current_price}")

    async def _advance_auction(self, task: AgentTasks, state, config):
        """推进拍卖。"""
        # 拍卖自动出价逻辑
        current_price = state.current_price or 0

        input_data = task.input_data or {}
        constraints_data = input_data.get("constraints", {})
        max_budget = constraints_data.get("budget_limit", float("inf"))

        if current_price < max_budget * 0.9:
            # 自动加价
            bid_amount = min(current_price * 1.05, max_budget * 0.9)
            await self.negotiation_kernel.submit_bid(
                session_id=state.session_id,
                bidder_id=task.created_by,
                amount=bid_amount,
            )
            logger.info(f"Task {task.public_id}: Auto-placed bid at {bid_amount}")

    async def _finalize_task(self, task: AgentTasks, state):
        """完成任务。"""
        task.status = "completed" if state.status.value == "accepted" else "failed"
        task.finished_at = datetime.now(timezone.utc)
        task.output_data = {
            **task.output_data,
            "final_status": state.status.value,
            "final_price": state.agreed_price,
            "session_id": state.session_id,
        }
        task.progress_percentage = 100
        await self.db.commit()

        logger.info(f"Task {task.public_id} finalized with status {state.status.value}")


# ========================================================================
# Factory and Runner
# ========================================================================

_agent_worker: Optional[TradeAgentWorker] = None


async def start_agent_worker(db: AsyncSession, poll_interval: float = 5.0):
    """启动全局Agent Worker。"""
    global _agent_worker
    _agent_worker = TradeAgentWorker(db)
    await _agent_worker.start(poll_interval)


def stop_agent_worker():
    """停止全局Agent Worker。"""
    global _agent_worker
    if _agent_worker:
        _agent_worker.stop()
        _agent_worker = None
