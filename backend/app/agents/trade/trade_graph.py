"""
Trade Multi-Agent System - LangGraph Implementation

基于 LangGraph 的多 Agent 分布式协商架构：
- ExchangeOrchestrator Node: 交易协调与治理
- SellerAgent Node: 卖方 Agent（策略、报价、决策）
- BuyerAgent Node: 买方 Agent（需求、出价、评估）
- MarketMechanism Nodes: 拍卖/合同网/双边协商机制
- Settlement Node: 结算与交付

状态流转：
    [Init] -> [Orchestrator] -> [Seller] <-> [Buyer] -> [Settlement] -> [End]
                         ↓
              [Auction/ContractNet/Bilateral]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Callable, Literal, Annotated
from enum import Enum
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver

from sqlalchemy.ext.asyncio import AsyncSession

from . import (
    TradeState,
    SellerAgentState,
    BuyerAgentState,
    SharedStateBoard,
    SettlementState,
    NegotiationStatus,
    MarketMechanismType,
)
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


# ============================================================================
# Message Types for Inter-Agent Communication
# ============================================================================

class MessageType(str, Enum):
    """Agent 间通信消息类型。"""
    ANNOUNCE = "announce"           # 卖方发布公告
    BID = "bid"                     # 买方投标
    OFFER = "offer"                 # 报价
    COUNTER = "counter"             # 反报价
    ACCEPT = "accept"               # 接受
    REJECT = "reject"               # 拒绝
    QUERY = "query"                 # 查询
    RESPONSE = "response"           # 响应
    COMMIT = "commit"               # 承诺
    SETTLE = "settle"               # 结算


@dataclass
class AgentMessage:
    """Agent 间传递的消息。"""
    msg_id: str
    msg_type: MessageType
    from_agent: str                 # 发送方 Agent ID
    to_agent: str                   # 接收方 Agent ID
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = 0               # 优先级


# ============================================================================
# Enhanced Trade State for LangGraph
# ============================================================================

class TradeAgentState(TradeState):
    """扩展的 TradeState，支持 LangGraph 状态流转。"""
    # 消息队列（Agent 间通信）
    message_queue: List[AgentMessage] = []

    # 当前活跃的 Agent
    current_turn: str = ""          # 当前轮到的 Agent

    # 循环控制
    round_count: int = 0
    max_rounds: int = 10

    # 干预/暂停
    human_in_the_loop: bool = False
    pending_human_decision: Optional[Dict[str, Any]] = None

    # 错误处理
    error_count: int = 0
    last_error: Optional[str] = None


# ============================================================================
# Agent Nodes
# ============================================================================

class SellerAgentNode:
    """
    Seller Agent Node - 卖方 Agent。

    职责：
    - 制定定价策略
    - 评估买方出价
    - 决定是否接受/拒绝/反报价
    - 管理资产隐私和许可
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm = llm_client
        self.agent_id = f"seller_{uuid.uuid4().hex[:8]}"

    async def __call__(self, state: TradeAgentState) -> TradeAgentState:
        """
        Seller Agent 主逻辑。

        输入：当前状态（包含买方消息）
        输出：更新后的状态（包含卖方决策）
        """
        logger.info(f"[{self.agent_id}] Seller Agent processing...")

        seller_state = state.get("seller_agent_state", {})
        messages = state.get("message_queue", [])

        # 处理收到的消息
        pending_messages = [m for m in messages if m.to_agent == self.agent_id]

        for msg in pending_messages:
            if msg.msg_type == MessageType.BID:
                # 处理投标
                await self._evaluate_bid(state, msg)
            elif msg.msg_type == MessageType.OFFER:
                # 处理报价
                await self._evaluate_offer(state, msg)
            elif msg.msg_type == MessageType.QUERY:
                # 处理查询
                await self._handle_query(state, msg)

        # 主动行为：如果是卖方轮次
        if state.get("current_turn") == "seller":
            await self._take_action(state)

        # 标记消息已处理
        state["message_queue"] = [m for m in messages if m not in pending_messages]

        return state

    async def _evaluate_bid(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """评估买方投标。"""
        bid_amount = msg.payload.get("amount", 0)
        seller_state = state["seller_agent_state"]
        reserve_price = seller_state.get("reserve_price", 0)

        # 决策逻辑
        if bid_amount >= reserve_price:
            # 接受投标
            response = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.ACCEPT,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"accepted_bid": bid_amount, "terms": {}},
            )
            state["negotiation_status"] = "awarding"
        else:
            # 拒绝或要求更高出价
            response = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.COUNTER,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={
                    "min_acceptable": reserve_price * 1.05,
                    "reason": "Bid below reserve price",
                },
            )

        state["message_queue"].append(response)

    async def _evaluate_offer(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """评估买方报价。"""
        offer_price = msg.payload.get("price", 0)
        seller_state = state["seller_agent_state"]
        target_price = seller_state.get("target_price", offer_price * 1.2)

        # 使用 LLM 辅助决策（如果配置了）
        if self.llm and offer_price < target_price * 0.9:
            # 复杂场景使用 LLM 分析
            decision = await self._llm_decision(state, msg)
        else:
            # 简单规则决策
            if offer_price >= target_price * 0.95:
                decision = "accept"
            elif offer_price >= target_price * 0.8:
                decision = "counter"
            else:
                decision = "reject"

        # 生成响应
        if decision == "accept":
            response_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.ACCEPT,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"agreed_price": offer_price},
            )
            state["negotiation_status"] = "awarding"

        elif decision == "counter":
            counter_price = (offer_price + target_price) / 2
            response_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.COUNTER,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"counter_price": counter_price, "justification": "..."},
            )

        else:  # reject
            response_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.REJECT,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"reason": "Offer too low"},
            )
            state["negotiation_status"] = "cancelled"

        state["message_queue"].append(response_msg)

    async def _handle_query(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """处理买方查询。"""
        query_type = msg.payload.get("query_type")

        if query_type == "asset_details":
            # 返回脱敏后的资产信息
            asset_summary = state["seller_agent_state"].get("asset_summary", {})
            response = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.RESPONSE,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"asset_info": asset_summary},
            )
            state["message_queue"].append(response)

    async def _take_action(self, state: TradeAgentState) -> None:
        """卖方主动行为。"""
        mechanism = state.get("mechanism_type")

        if mechanism == "contract_net":
            # 发布任务公告
            await self._announce_task(state)
        elif mechanism == "auction":
            # 启动拍卖
            await self._start_auction(state)

    async def _announce_task(self, state: TradeAgentState) -> None:
        """发布合同网任务公告。"""
        announcement = AgentMessage(
            msg_id=str(uuid.uuid4()),
            msg_type=MessageType.ANNOUNCE,
            from_agent=self.agent_id,
            to_agent="broadcast",  # 广播给所有潜在买方
            payload={
                "task_description": state["seller_agent_state"].get("asset_summary"),
                "eligibility_criteria": state["seller_agent_state"].get("license_scope"),
                "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            },
        )
        state["message_queue"].append(announcement)
        state["negotiation_status"] = "announcing"

    async def _start_auction(self, state: TradeAgentState) -> None:
        """启动拍卖。"""
        announcement = AgentMessage(
            msg_id=str(uuid.uuid4()),
            msg_type=MessageType.ANNOUNCE,
            from_agent=self.agent_id,
            to_agent="broadcast",
            payload={
                "auction_type": "english",
                "starting_price": state["seller_agent_state"].get("reserve_price", 0),
                "reserve_price": state["seller_agent_state"].get("reserve_price", 0) * 0.8,
            },
        )
        state["message_queue"].append(announcement)

    async def _llm_decision(self, state: TradeAgentState, msg: AgentMessage) -> str:
        """使用 LLM 辅助决策。"""
        # TODO: 实现 LLM 决策逻辑
        return "counter"


class BuyerAgentNode:
    """
    Buyer Agent Node - 买方 Agent。

    职责：
    - 分析需求
    - 搜索和评估卖方公告
    - 制定出价策略
    - 管理预算和风险
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm = llm_client
        self.agent_id = f"buyer_{uuid.uuid4().hex[:8]}"

    async def __call__(self, state: TradeAgentState) -> TradeAgentState:
        """
        Buyer Agent 主逻辑。
        """
        logger.info(f"[{self.agent_id}] Buyer Agent processing...")

        messages = state.get("message_queue", [])
        pending_messages = [m for m in messages if m.to_agent == self.agent_id or m.to_agent == "broadcast"]

        for msg in pending_messages:
            if msg.msg_type == MessageType.ANNOUNCE:
                # 评估卖方公告
                await self._evaluate_announcement(state, msg)
            elif msg.msg_type == MessageType.COUNTER:
                # 处理反报价
                await self._handle_counter(state, msg)
            elif msg.msg_type == MessageType.ACCEPT:
                # 投标被接受
                await self._handle_acceptance(state, msg)

        # 主动行为
        if state.get("current_turn") == "buyer":
            await self._take_action(state)

        # 清理已处理消息
        state["message_queue"] = [m for m in messages if m not in pending_messages]

        return state

    async def _evaluate_announcement(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """评估卖方公告。"""
        buyer_state = state["buyer_agent_state"]
        budget_max = buyer_state.get("budget_max", 0)

        task = msg.payload.get("task_description", {})
        starting_price = msg.payload.get("starting_price", float('inf'))

        # 决策：是否参与
        if starting_price <= budget_max:
            # 发送投标
            bid_amount = min(starting_price * 1.1, budget_max * 0.9)
            bid_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.BID,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={
                    "amount": bid_amount,
                    "qualifications": buyer_state.get("requirements", {}),
                },
            )
            state["message_queue"].append(bid_msg)

    async def _handle_counter(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """处理卖方反报价。"""
        counter_price = msg.payload.get("counter_price", 0)
        buyer_state = state["buyer_agent_state"]
        budget_max = buyer_state.get("budget_max", 0)

        if counter_price <= budget_max * 0.95:
            # 接受反报价
            accept_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.ACCEPT,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"agreed_price": counter_price},
            )
            state["message_queue"].append(accept_msg)
        elif counter_price <= budget_max:
            # 继续协商
            new_offer = (counter_price + buyer_state.get("current_bid", counter_price * 0.9)) / 2
            offer_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.OFFER,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"price": new_offer},
            )
            state["message_queue"].append(offer_msg)
        else:
            # 超出预算，退出
            reject_msg = AgentMessage(
                msg_id=str(uuid.uuid4()),
                msg_type=MessageType.REJECT,
                from_agent=self.agent_id,
                to_agent=msg.from_agent,
                payload={"reason": "Exceeds budget"},
            )
            state["message_queue"].append(reject_msg)

    async def _handle_acceptance(self, state: TradeAgentState, msg: AgentMessage) -> None:
        """处理接受消息。"""
        state["negotiation_status"] = "awarding"

    async def _take_action(self, state: TradeAgentState) -> None:
        """买方主动行为。"""
        # 可以主动查询资产详情等
        pass


class ExchangeOrchestratorNode:
    """
    Exchange Orchestrator Node - 交易协调器。

    职责：
    - 初始化交易会话
    - 路由消息到相应 Agent
    - 控制协商轮次
    - 检测终止条件
    - 触发结算
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.agent_id = "orchestrator"

    async def __call__(self, state: TradeAgentState) -> TradeAgentState:
        """
        Orchestrator 主逻辑。
        """
        logger.info(f"[Orchestrator] Processing negotiation {state.get('negotiation_id')}...")

        # 检查终止条件
        if self._should_terminate(state):
            state["negotiation_status"] = "terminated"
            return state

        # 检查是否达成交易
        if self._is_agreement_reached(state):
            state["negotiation_status"] = "awarding"
            return state

        # 轮次控制
        round_count = state.get("round_count", 0)
        max_rounds = state.get("max_rounds", 10)

        if round_count >= max_rounds:
            state["negotiation_status"] = "cancelled"
            state["last_error"] = "Max rounds reached"
            return state

        # 确定下一步哪个 Agent 行动
        current_turn = self._determine_next_turn(state)
        state["current_turn"] = current_turn
        state["round_count"] = round_count + 1

        # 更新共享状态板
        self._update_shared_board(state)

        return state

    def _should_terminate(self, state: TradeAgentState) -> bool:
        """检查是否应该终止协商。"""
        status = state.get("negotiation_status")
        return status in ["cancelled", "settled", "disputed"]

    def _is_agreement_reached(self, state: TradeAgentState) -> bool:
        """检查是否达成交易协议。"""
        messages = state.get("message_queue", [])
        for msg in messages:
            if msg.msg_type == MessageType.ACCEPT:
                return True
        return False

    def _determine_next_turn(self, state: TradeAgentState) -> str:
        """确定下一个行动的 Agent。"""
        mechanism = state.get("mechanism_type")
        current = state.get("current_turn", "")

        if mechanism == "auction":
            # 拍卖：买方轮流出价
            return "buyer"
        elif mechanism == "bilateral":
            # 双边协商：轮流
            return "buyer" if current == "seller" else "seller"
        elif mechanism == "contract_net":
            # 合同网：卖方发布 -> 买方投标 -> 卖方选择
            if current == "":
                return "seller"
            elif current == "seller":
                return "buyer"
            else:
                return "seller"
        else:
            return "seller"

    def _update_shared_board(self, state: TradeAgentState) -> None:
        """更新共享状态板。"""
        shared_board = state.get("shared_board", {})
        shared_board["updated_at"] = datetime.now(timezone.utc).isoformat()
        shared_board["current_round"] = state.get("round_count", 0)
        shared_board["current_phase"] = state.get("negotiation_status", "unknown")


class SettlementNode:
    """
    Settlement Node - 结算节点。

    职责：
    - 验证交易协议
    - 执行支付
    - 生成访问令牌
    - 记录审计日志
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.agent_id = "settlement"

    async def __call__(self, state: TradeAgentState) -> TradeAgentState:
        """
        Settlement 主逻辑。
        """
        logger.info("[Settlement] Processing settlement...")

        if state.get("negotiation_status") != "awarding":
            return state

        # 提取协议详情
        agreement = self._extract_agreement(state)

        if not agreement:
            state["last_error"] = "No agreement found"
            state["negotiation_status"] = "error"
            return state

        # 执行结算
        settlement_result = await self._execute_settlement(state, agreement)

        if settlement_result.get("success"):
            state["negotiation_status"] = "settled"
            state["settlement_result"] = settlement_result
        else:
            state["last_error"] = settlement_result.get("error", "Settlement failed")
            state["negotiation_status"] = "disputed"

        return state

    def _extract_agreement(self, state: TradeAgentState) -> Optional[Dict[str, Any]]:
        """从消息中提取协议。"""
        messages = state.get("message_queue", [])
        for msg in messages:
            if msg.msg_type == MessageType.ACCEPT:
                return msg.payload
        return None

    async def _execute_settlement(
        self,
        state: TradeAgentState,
        agreement: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行结算。"""
        try:
            final_price = agreement.get("agreed_price") or agreement.get("accepted_bid", 0)
            platform_fee = final_price * 0.05
            seller_proceeds = final_price - platform_fee

            # TODO: 实际的数据库操作

            return {
                "success": True,
                "final_price": final_price,
                "platform_fee": platform_fee,
                "seller_proceeds": seller_proceeds,
                "access_token": str(uuid.uuid4())[:32],
                "settled_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# Graph Builder
# ============================================================================

def create_trade_graph(
    db: Optional[AsyncSession] = None,
    llm_client: Optional[Any] = None,
    checkpointer: Optional[Any] = None,
) -> StateGraph:
    """
    创建 Trade Multi-Agent 状态图。

    状态流转：
        init -> orchestrator -> {seller, buyer} -> {auction, bilateral, contract_net} -> settlement -> end
    """

    # 初始化 Nodes
    orchestrator = ExchangeOrchestratorNode(db)
    seller = SellerAgentNode(llm_client)
    buyer = BuyerAgentNode(llm_client)
    settlement = SettlementNode(db)

    # 创建状态图
    workflow = StateGraph(TradeAgentState)

    # 添加 Nodes
    workflow.add_node("orchestrator", orchestrator)
    workflow.add_node("seller", seller)
    workflow.add_node("buyer", buyer)
    workflow.add_node("settlement", settlement)

    # 设置入口
    workflow.set_entry_point("orchestrator")

    # 定义边
    def route_from_orchestrator(state: TradeAgentState) -> str:
        """从 Orchestrator 路由到下一个节点。"""
        status = state.get("negotiation_status")

        if status in ["cancelled", "terminated"]:
            return END
        elif status == "awarding":
            return "settlement"
        else:
            return state.get("current_turn", "seller")

    def route_from_agent(state: TradeAgentState) -> str:
        """从 Agent 返回 Orchestrator。"""
        status = state.get("negotiation_status")

        if status in ["cancelled", "terminated", "settled"]:
            return END
        elif status == "awarding":
            return "settlement"
        else:
            return "orchestrator"

    def route_from_settlement(state: TradeAgentState) -> str:
        """从 Settlement 路由。"""
        status = state.get("negotiation_status")

        if status == "settled":
            return END
        elif status == "disputed":
            return "orchestrator"  # 争议处理
        else:
            return END

    # 添加条件边
    workflow.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "seller": "seller",
            "buyer": "buyer",
            "settlement": "settlement",
            END: END,
        }
    )

    workflow.add_conditional_edges(
        "seller",
        route_from_agent,
        {
            "orchestrator": "orchestrator",
            "settlement": "settlement",
            END: END,
        }
    )

    workflow.add_conditional_edges(
        "buyer",
        route_from_agent,
        {
            "orchestrator": "orchestrator",
            "settlement": "settlement",
            END: END,
        }
    )

    workflow.add_conditional_edges(
        "settlement",
        route_from_settlement,
        {
            "orchestrator": "orchestrator",
            END: END,
        }
    )

    # 编译图
    if checkpointer:
        return workflow.compile(checkpointer=checkpointer)
    else:
        return workflow.compile()


# ============================================================================
# Trade Graph Service
# ============================================================================

class TradeGraphService:
    """
    Trade Graph Service - 对外提供 Trade Multi-Agent 服务。

    封装 LangGraph 的复杂性，提供简单的 API。
    """

    def __init__(self, db: AsyncSession, llm_client: Optional[Any] = None):
        self.db = db
        self.llm = llm_client
        self.checkpointer = MemorySaver()
        self.graph = create_trade_graph(db, llm_client, self.checkpointer)

    async def initiate_negotiation(
        self,
        seller_id: int,
        buyer_id: Optional[int],
        asset_id: str,
        mechanism_type: str,
        initial_state: Dict[str, Any],
    ) -> str:
        """
        启动新的协商会话。

        Returns:
            negotiation_id: 协商会话 ID
        """
        negotiation_id = str(uuid.uuid4())[:32]

        # 初始化状态
        state: TradeAgentState = {
            "action": "negotiation",
            "asset_to_list": initial_state.get("asset_summary"),
            "policy": {},
            "listing": None,
            "listing_id": None,
            "order": None,
            "delivery": None,
            "mechanism_type": mechanism_type,
            "negotiation_id": negotiation_id,
            "shared_board": {
                "negotiation_id": negotiation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "public_quotes": [],
                "announced_conditions": {},
                "current_conditions": {},
                "agreed_conditions": {},
                "event_log": [],
                "message_log": [],
                "commitment_hashes": [],
                "timestamp_proofs": [],
                "active_participants": [seller_id] if seller_id else [],
                "current_phase": "init",
                "estimated_completion": None,
            },
            "seller_agent_state": {
                "seller_user_id": seller_id,
                "seller_alias": f"seller_{uuid.uuid4().hex[:8]}",
                "asset_id": asset_id,
                "asset_summary": initial_state.get("asset_summary", {}),
                "asset_metadata": {},
                "reserve_price": initial_state.get("reserve_price", 0),
                "target_price": initial_state.get("target_price", 0),
                "pricing_strategy": mechanism_type,
                "license_scope": initial_state.get("license_scope", ["personal_use"]),
                "usage_restrictions": {},
                "redistribution_allowed": False,
                "max_usage_count": None,
                "desensitization_level": "partial",
                "visible_fields": [],
                "hidden_fields": [],
                "current_quote": None,
                "quote_history": [],
                "is_open_to_negotiate": mechanism_type != "fixed_price",
                "min_acceptable_price": initial_state.get("reserve_price", 0) * 0.9,
                "announced_tasks": [],
                "received_bids": [],
                "awarded_buyers": [],
            },
            "buyer_agent_state": {
                "buyer_user_id": buyer_id,
                "buyer_alias": f"buyer_{uuid.uuid4().hex[:8]}",
                "requirements": initial_state.get("buyer_requirements", {}),
                "quality_preferences": {},
                "risk_constraints": {},
                "intended_use": "personal",
                "budget_max": initial_state.get("budget_max", 0),
                "budget_preferred": initial_state.get("budget_max", 0) * 0.8,
                "payment_terms": "immediate",
                "candidate_sellers": [],
                "comparing_offers": [],
                "shortlisted": [],
                "current_bid": None,
                "bid_history": [],
                "counter_offer_ready": False,
                "max_rounds_acceptable": 5,
                "submitted_bids": [],
                "awarded_contracts": [],
            } if buyer_id else None,
            "negotiation_round": 0,
            "max_rounds": initial_state.get("max_rounds", 10),
            "negotiation_status": "pending",
            "settlement_result": None,
            "audit_log": [],
            # TradeAgentState 扩展字段
            "message_queue": [],
            "current_turn": "seller",
            "round_count": 0,
            "human_in_the_loop": False,
            "pending_human_decision": None,
            "error_count": 0,
            "last_error": None,
        }

        # 启动图执行
        config = {"configurable": {"thread_id": negotiation_id}}

        # 异步执行图
        # 注意：LangGraph 的 ainvoke 是异步的
        result = await self.graph.ainvoke(state, config)

        return negotiation_id

    async def execute_step(
        self,
        negotiation_id: str,
        action: str,
        payload: Dict[str, Any],
        from_agent: str,
    ) -> Dict[str, Any]:
        """
        执行协商步骤。

        Args:
            negotiation_id: 协商会话 ID
            action: 动作类型
            payload: 动作数据
            from_agent: 发送方 Agent ID
        """
        config = {"configurable": {"thread_id": negotiation_id}}

        # 获取当前状态
        current_state = await self.graph.aget_state(config)

        if not current_state:
            raise ServiceError(404, "Negotiation not found")

        # 添加消息到队列
        message = AgentMessage(
            msg_id=str(uuid.uuid4()),
            msg_type=MessageType(action),
            from_agent=from_agent,
            to_agent="orchestrator",  # 发送给协调器处理
            payload=payload,
        )

        current_state.values["message_queue"].append(message)

        # 继续执行图
        result = await self.graph.ainvoke(current_state.values, config)

        return {
            "negotiation_id": negotiation_id,
            "status": result.get("negotiation_status"),
            "current_turn": result.get("current_turn"),
            "round_count": result.get("round_count"),
            "shared_board": result.get("shared_board"),
        }

    async def get_status(self, negotiation_id: str) -> Optional[Dict[str, Any]]:
        """获取协商状态。"""
        config = {"configurable": {"thread_id": negotiation_id}}

        try:
            state = await self.graph.aget_state(config)
            if state:
                return {
                    "negotiation_id": negotiation_id,
                    "status": state.values.get("negotiation_status"),
                    "mechanism": state.values.get("mechanism_type"),
                    "round_count": state.values.get("round_count"),
                    "current_turn": state.values.get("current_turn"),
                    "settlement": state.values.get("settlement_result"),
                }
        except Exception as e:
            logger.error(f"Error getting status: {e}")

        return None
