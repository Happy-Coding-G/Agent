"""
Main Agent Orchestrator - Multi-Agent System

This module implements the MainAgent that orchestrates all sub-agents
using LangGraph subgraphs for each specialized agent.
"""
import logging
import uuid
from typing import AsyncGenerator, Dict, Any, Optional, Callable
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from .state import MainAgentState, AgentType, TaskStatus
from .prompts import INTENT_DETECTION_PROMPT

logger = logging.getLogger(__name__)


class SubAgents:
    """
    Container for all sub-agents.
    Manages the lifecycle of all sub-agent instances and provides
    a unified interface for invoking them.
    """

    def __init__(self, db: AsyncSession, llm_client=None, space_path: Optional[str] = None):
        """
        Initialize SubAgents container.

        Args:
            db: AsyncSession for database operations
            llm_client: LLM client for agents that need it
            space_path: Root path for file query agent (space directory)
        """
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path
        self._agents: Dict[AgentType, Any] = {}
        self._graphs: Dict[AgentType, Any] = {}
        self._initialized = False

    def _lazy_init(self):
        """Lazy initialization of all sub-agents on first use."""
        if self._initialized:
            return

        try:
            # Import subagent classes
            from app.agents.subagents.file_query_agent import FileQueryAgent
            from app.agents.subagents.qa_agent import QAAgent
            from app.agents.subagents.data_process_agent import DataProcessAgent
            from app.agents.subagents.review_agent import ReviewAgent
            from app.agents.subagents.asset_organize_agent import AssetOrganizeAgent
            from app.agents.subagents.trade_agent import TradeAgent

            # Initialize each agent with its required dependencies
            if self._space_path:
                self._agents[AgentType.FILE_QUERY] = FileQueryAgent(self._space_path)
                self._graphs[AgentType.FILE_QUERY] = self._agents[AgentType.FILE_QUERY].graph

            self._agents[AgentType.QA] = QAAgent(self._db)
            self._graphs[AgentType.QA] = self._agents[AgentType.QA].graph

            self._agents[AgentType.DATA_PROCESS] = DataProcessAgent(self._db)
            self._graphs[AgentType.DATA_PROCESS] = self._agents[AgentType.DATA_PROCESS].graph

            self._agents[AgentType.REVIEW] = ReviewAgent(self._db)
            self._graphs[AgentType.REVIEW] = self._agents[AgentType.REVIEW].graph

            self._agents[AgentType.ASSET_ORGANIZE] = AssetOrganizeAgent(self._db)
            self._graphs[AgentType.ASSET_ORGANIZE] = self._agents[AgentType.ASSET_ORGANIZE].graph

            self._agents[AgentType.TRADE] = TradeAgent(self._db)
            # TradeAgent has multiple graphs (listing, purchase, yield)
            self._graphs[AgentType.TRADE] = self._agents[AgentType.TRADE]

            self._initialized = True
            logger.info("All sub-agents initialized successfully")

        except ImportError as e:
            logger.error(f"Failed to import subagent classes: {e}")
            raise

    async def invoke_subagent(
        self,
        agent_type: AgentType,
        input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Invoke a sub-agent by type with proper state transformation.

        Args:
            agent_type: The type of agent to invoke
            input_state: The input state from MainAgent

        Returns:
            The result from the sub-agent execution
        """
        # Ensure agents are initialized
        self._lazy_init()

        if agent_type not in self._graphs:
            return {
                "error": f"Sub-agent {agent_type.value} not available",
                "success": False
            }

        try:
            agent = self._agents.get(agent_type)
            graph = self._graphs.get(agent_type)

            if agent_type == AgentType.FILE_QUERY:
                # FileQueryAgent has different interface
                query = input_state.get("user_request", "")
                return await agent.run(query)

            elif agent_type == AgentType.QA:
                # Use new unified QAAgent interface
                from app.db.models import Users
                qa_agent = self._agents.get(AgentType.QA)

                # Get user for permission checking
                user = None
                user_id = input_state.get("user_id")
                if user_id:
                    from sqlalchemy import select
                    from app.db.models import Users
                    result = await self._db.execute(select(Users).where(Users.id == user_id))
                    user = result.scalar_one_or_none()

                if not user:
                    return {
                        "success": False,
                        "error": "User not found for QA agent",
                        "agent_type": "qa"
                    }

                # Call unified QAAgent.run() interface
                return await qa_agent.run(
                    query=input_state.get("user_request", ""),
                    space_public_id=input_state.get("space_id", ""),
                    user=user,
                    top_k=input_state.get("top_k", 5),
                )

            elif agent_type == AgentType.DATA_PROCESS:
                # DataProcessAgent
                doc_input = {
                    "source_type": input_state.get("source_type", "minio"),
                    "source_path": input_state.get("source_path", ""),
                    "source_content": None,
                    "extracted_text": None,
                    "markdown_content": None,
                    "chunks": [],
                    "embedding_ids": [],
                    "graph_nodes": 0,
                    "doc_id": None,
                    "status": "pending",
                    "error": None
                }
                result = await graph.ainvoke(doc_input)
                return {
                    "success": result.get("status") == "done",
                    "doc_id": result.get("doc_id"),
                    "chunks": result.get("chunks", []),
                    "graph_nodes": result.get("graph_nodes", 0),
                    "error": result.get("error")
                }

            elif agent_type == AgentType.REVIEW:
                # ReviewAgent
                review_input = {
                    "doc_id": input_state.get("doc_id", ""),
                    "review_type": input_state.get("review_type", "quality"),
                    "review_result": {},
                    "rework_needed": False,
                    "rework_count": 0,
                    "max_rework": 3,
                    "final_status": "pending"
                }
                result = await graph.ainvoke(review_input)
                return {
                    "success": result.get("final_status") == "approved",
                    "doc_id": result.get("doc_id"),
                    "score": result.get("review_result", {}).get("score", 0),
                    "passed": result.get("final_status") == "approved",
                    "issues": result.get("review_result", {}).get("issues", []),
                    "final_status": result.get("final_status"),
                    "rework_count": result.get("rework_count", 0)
                }

            elif agent_type == AgentType.ASSET_ORGANIZE:
                # AssetOrganizeAgent
                asset_input = {
                    "asset_ids": input_state.get("asset_ids", []),
                    "clustering_result": {},
                    "graph_updates": [],
                    "summary_report": None,
                    "publication_ready": False
                }
                result = await graph.ainvoke(asset_input)
                return {
                    "success": result.get("publication_ready", False),
                    "clusters": result.get("clustering_result", {}).get("clusters", []),
                    "summary_report": result.get("summary_report"),
                    "graph_updates": result.get("graph_updates", [])
                }

            elif agent_type == AgentType.TRADE:
                # TradeAgent has multiple workflows - determine which to use
                action = input_state.get("action", "listing")
                if action == "listing":
                    return await self._invoke_trade_listing(agent, input_state)
                elif action == "purchase":
                    return await self._invoke_trade_purchase(agent, input_state)
                elif action == "yield":
                    return await self._invoke_trade_yield(agent, input_state)
                else:
                    return {"error": f"Unknown trade action: {action}"}

            elif agent_type == AgentType.CHAT:
                # Fallback for general chat - use QA agent
                return await self.invoke_subagent(AgentType.QA, input_state)

            else:
                return {"error": f"Unhandled agent type: {agent_type}"}

        except Exception as e:
            logger.exception(f"Error invoking sub-agent {agent_type}: {e}")
            return {
                "error": str(e),
                "success": False,
                "agent_type": agent_type.value
            }

    async def _invoke_trade_listing(
        self, agent: Any, input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Invoke TradeAgent listing workflow using hybrid market architecture."""
        from app.db.models import Users
        from sqlalchemy import select

        # Get user for permission checking
        user = None
        user_id = input_state.get("user_id")
        if user_id:
            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            return {"success": False, "error": "User not found for trade listing"}

        # Use new hybrid market architecture API
        pricing_strategy = input_state.get("pricing_strategy", "negotiable")
        reserve_price = input_state.get("reserve_price")

        try:
            result = await agent.create_listing(
                space_public_id=input_state.get("space_id", ""),
                asset_id=input_state.get("asset_id", ""),
                user=user,
                pricing_strategy=pricing_strategy,
                reserve_price=reserve_price,
                license_scope=input_state.get("license_scope"),
                mechanism_hint=input_state.get("mechanism_hint"),
                category=input_state.get("category"),
                tags=input_state.get("tags", []),
            )
            return {
                "success": result.get("success", False),
                "listing_id": result.get("listing_id"),
                "negotiation_id": result.get("negotiation_id"),
                "reserve_price": result.get("reserve_price"),
                "mechanism": result.get("mechanism", pricing_strategy),
                "error": None if result.get("success") else result.get("error", "Listing failed"),
            }
        except Exception as e:
            logger.exception(f"Trade listing failed: {e}")
            return {"success": False, "error": str(e)}

    async def _invoke_trade_purchase(
        self, agent: Any, input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Invoke TradeAgent purchase workflow using hybrid market architecture."""
        from app.db.models import Users
        from sqlalchemy import select

        # Get user for permission checking
        user = None
        user_id = input_state.get("user_id")
        if user_id:
            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            return {"success": False, "error": "User not found for trade purchase"}

        try:
            # Determine purchase type
            purchase_type = input_state.get("purchase_type", "direct")

            if purchase_type == "auction_bid":
                # Place auction bid
                result = await agent.place_auction_bid(
                    lot_id=input_state.get("lot_id", ""),
                    user=user,
                    amount=input_state.get("bid_amount", 0),
                )
            elif purchase_type == "bilateral":
                # Create bilateral negotiation
                result = await agent.create_bilateral_negotiation(
                    listing_id=input_state.get("listing_id", ""),
                    buyer=user,
                    initial_offer=input_state.get("initial_offer", 0),
                    max_rounds=input_state.get("max_rounds", 10),
                )
            else:
                # Direct purchase or initiate negotiation
                result = await agent.initiate_purchase(
                    user=user,
                    listing_id=input_state.get("listing_id"),
                    requirements=input_state.get("requirements"),
                    budget_max=input_state.get("budget_max", 0),
                    mechanism_hint=input_state.get("mechanism_hint"),
                )

                # If immediate settlement possible (fixed price)
                if result.get("status") == "awarding":
                    settlement = result.get("settlement", {})
                    return {
                        "success": True,
                        "order_id": settlement.get("order_id"),
                        "final_price": settlement.get("final_price"),
                        "platform_fee": settlement.get("platform_fee"),
                        "mechanism": result.get("mechanism", "fixed_price"),
                        "status": "completed",
                    }

            return {
                "success": result.get("success", False),
                "negotiation_id": result.get("negotiation_id"),
                "session_id": result.get("session_id"),
                "mechanism": result.get("mechanism", purchase_type),
                "status": result.get("status", "pending"),
                "error": None if result.get("success") else result.get("error"),
            }

        except Exception as e:
            logger.exception(f"Trade purchase failed: {e}")
            return {"success": False, "error": str(e)}

    async def _invoke_trade_yield(
        self, agent: Any, input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Invoke TradeAgent yield workflow (legacy - maintained for compatibility)."""
        from app.db.models import Users
        from sqlalchemy import select

        # Get user
        user = None
        user_id = input_state.get("user_id")
        if user_id:
            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            return {"success": False, "error": "User not found for yield calculation"}

        try:
            # Use legacy API for yield calculation
            result = await agent.run_auto_yield(
                space_public_id=input_state.get("space_id", ""),
                user=user,
                strategy=input_state.get("strategy", "balanced"),
            )

            return {
                "success": result.get("success", False),
                "yield_amount": result.get("yield_amount", 0),
                "annual_rate": result.get("annual_rate", 0),
                "elapsed_days": result.get("elapsed_days", 0),
                "wallet_after": result.get("wallet_after", {}),
                "report": result.get("report", {}),
                "error": result.get("error"),
            }

        except Exception as e:
            logger.exception(f"Trade yield failed: {e}")
            return {"success": False, "error": str(e)}

    def get_registered_agents(self) -> list[str]:
        """Return list of registered agent types."""
        self._lazy_init()
        return [agent_type.value for agent_type in self._graphs.keys()]


class MainAgent:
    """
    Main Agent Orchestrator that routes user requests to appropriate sub-agents.
    Uses LangGraph for state management and agent coordination.
    """

    def __init__(self, db: AsyncSession, llm_client=None, space_path: Optional[str] = None):
        """
        Initialize MainAgent.

        Args:
            db: AsyncSession for database operations
            llm_client: Optional LLM client for intent detection
            space_path: Root path for file queries
        """
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path
        self._subagents: Optional[SubAgents] = None
        self.graph = self._build_graph()

    @property
    def subagents(self) -> SubAgents:
        """Lazy-load subagents."""
        if self._subagents is None:
            self._subagents = SubAgents(
                db=self._db,
                llm_client=self._llm_client,
                space_path=self._space_path
            )
        return self._subagents

    @subagents.setter
    def subagents(self, value):
        """Allow setting subagents externally."""
        self._subagents = value

    def _build_graph(self) -> StateGraph:
        """Build the main agent state graph."""
        workflow = StateGraph(MainAgentState)

        workflow.add_node("intent_detection", self._detect_intent)
        workflow.add_node("route_to_subagent", self._route_to_subagent)
        workflow.add_node("execute_subagent", self._execute_subagent)
        workflow.add_node("aggregate_results", self._aggregate_results)
        workflow.add_node("handle_error", self._handle_error)
        workflow.add_node("format_response", self._format_response)

        workflow.set_entry_point("intent_detection")

        workflow.add_conditional_edges(
            "execute_subagent",
            self._should_handle_error,
            {"error": "handle_error", "success": "aggregate_results"}
        )

        workflow.add_edge("intent_detection", "route_to_subagent")
        workflow.add_edge("route_to_subagent", "execute_subagent")
        workflow.add_edge("aggregate_results", "format_response")
        workflow.add_edge("format_response", END)
        workflow.add_edge("handle_error", END)

        checkpointer = MemorySaver()
        return workflow.compile(checkpointer=checkpointer)

    def _should_handle_error(self, state: MainAgentState) -> str:
        """Determine if we should route to error handler based on state."""
        if state.get("error"):
            return "error"
        task_status = state.get("task_status")
        if task_status == TaskStatus.FAILED:
            return "error"
        return "success"

    async def _detect_intent(self, state: MainAgentState) -> MainAgentState:
        """Detect user intent from the request."""
        user_request = state.get("user_request", "")

        if not self._llm_client:
            intent = self._simple_intent_detection(user_request)
            state["intent"] = intent
            return state

        try:
            prompt = INTENT_DETECTION_PROMPT.format(user_request=user_request)
            response = await self._llm_client.ainvoke(prompt)
            intent_str = response.content.strip().lower()

            intent_map = {
                "file_query": AgentType.FILE_QUERY,
                "data_process": AgentType.DATA_PROCESS,
                "review": AgentType.REVIEW,
                "qa": AgentType.QA,
                "asset_organize": AgentType.ASSET_ORGANIZE,
                "trade": AgentType.TRADE,
                "chat": AgentType.CHAT,
            }
            state["intent"] = intent_map.get(intent_str, AgentType.CHAT)
        except Exception as e:
            logger.warning(f"Intent detection failed, using fallback: {e}")
            state["intent"] = self._simple_intent_detection(user_request)

        return state

    def _simple_intent_detection(self, text: str) -> AgentType:
        """Simple keyword-based intent detection as fallback."""
        text_lower = text.lower()

        if any(kw in text_lower for kw in ["查看", "文件", "查找", "搜索", "目录"]):
            return AgentType.FILE_QUERY
        elif any(kw in text_lower for kw in ["导入", "处理", "上传", "摄取"]):
            return AgentType.DATA_PROCESS
        elif any(kw in text_lower for kw in ["审查", "检查", "审核", "质量"]):
            return AgentType.REVIEW
        elif any(kw in text_lower for kw in ["问答", "回答", "问题", "查询", "检索"]):
            return AgentType.QA
        elif any(kw in text_lower for kw in ["整理", "分类", "聚类", "资产"]):
            return AgentType.ASSET_ORGANIZE
        elif any(kw in text_lower for kw in ["交易", "购买", "出售", "卖出", "买入", "上架"]):
            return AgentType.TRADE
        else:
            return AgentType.CHAT

    async def _route_to_subagent(self, state: MainAgentState) -> MainAgentState:
        """Route to the appropriate sub-agent based on detected intent."""
        intent = state.get("intent", AgentType.CHAT)
        state["active_subagent"] = intent
        state["task_status"] = TaskStatus.RUNNING
        return state

    async def _execute_subagent(self, state: MainAgentState) -> MainAgentState:
        """Execute the active sub-agent."""
        agent_type = state.get("active_subagent", AgentType.CHAT)

        try:
            result = await self.subagents.invoke_subagent(agent_type, state)
            state["subagent_result"] = result
            state["task_status"] = TaskStatus.COMPLETED
        except Exception as e:
            logger.exception(f"Sub-agent execution failed: {e}")
            state["error"] = str(e)
            state["task_status"] = TaskStatus.FAILED

        return state

    async def _aggregate_results(self, state: MainAgentState) -> MainAgentState:
        """Aggregate results from sub-agents."""
        subagent_result = state.get("subagent_result", {})
        state["task_result"] = subagent_result
        return state

    async def _handle_error(self, state: MainAgentState) -> MainAgentState:
        """Handle errors and implement retry logic."""
        retry_count = state.get("retry_count", 0)

        if retry_count < 3:
            state["retry_count"] = retry_count + 1
            state["task_status"] = TaskStatus.PENDING
        else:
            state["task_status"] = TaskStatus.FAILED

        return state

    async def _format_response(self, state: MainAgentState) -> MainAgentState:
        """Format the final response."""
        return state

    async def stream_chat(
        self,
        message: str,
        space_id: str,
        user_id: Optional[int] = None,
        context: Optional[Dict] = None,
        top_k: int = 5,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main chat interface with unified streaming protocol.

        Stream events:
            - {"type": "intent", "data": "qa"} - Intent detected
            - {"type": "agent_type", "data": "qa"} - Agent type selected
            - {"type": "status", "data": "running"} - Status updates
            - {"type": "token", "data": "..."} - Streaming tokens (QA only)
            - {"type": "result", "data": {...}} - Final result
            - {"type": "error", "data": "..."} - Error message
        """
        initial_state: MainAgentState = {
            "user_request": message,
            "space_id": space_id,
            "user_id": user_id,
            "intent": None,
            "active_subagent": None,
            "subagent_result": None,
            "task_id": str(uuid.uuid4()),
            "task_status": TaskStatus.PENDING,
            "task_result": None,
            "conversation_history": [],
            "context": context or {},
            "error": None,
            "retry_count": 0,
        }

        # Step 1: Intent Detection
        yield {"type": "status", "data": "detecting_intent"}
        initial_state = await self._detect_intent(initial_state)

        intent = initial_state.get("intent", AgentType.CHAT)
        intent_str = intent.value if hasattr(intent, "value") else str(intent)
        yield {"type": "intent", "data": intent_str}
        yield {"type": "agent_type", "data": intent_str}

        # Step 2: Route to subagent
        yield {"type": "status", "data": "routing"}
        initial_state = await self._route_to_subagent(initial_state)

        # Step 3: Execute subagent with streaming support for QA
        yield {"type": "status", "data": "running"}

        agent_type = initial_state.get("active_subagent", AgentType.CHAT)

        try:
            # Special handling for QA agent - support streaming
            if agent_type == AgentType.QA:
                async for event in self._stream_qa_agent(initial_state, top_k):
                    yield event
            else:
                # Non-streaming agents
                initial_state = await self._execute_subagent(initial_state)

                if initial_state.get("error"):
                    yield {"type": "error", "data": initial_state["error"]}
                else:
                    result = initial_state.get("subagent_result", {})
                    yield {"type": "result", "data": result}

        except Exception as e:
            logger.exception(f"Sub-agent execution failed: {e}")
            yield {"type": "error", "data": str(e)}

        yield {"type": "status", "data": "completed"}

    async def _stream_qa_agent(
        self,
        state: MainAgentState,
        top_k: int = 5,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream QA agent execution with token-level events."""
        from app.db.models import Users
        from sqlalchemy import select

        # Get user
        user = None
        user_id = state.get("user_id")
        if user_id:
            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            yield {"type": "error", "data": "User not found"}
            return

        # Get QA agent
        qa_agent = self.subagents._agents.get(AgentType.QA)
        if not qa_agent:
            # Fallback to non-streaming
            state = await self._execute_subagent(state)
            yield {"type": "result", "data": state.get("subagent_result", {})}
            return

        # Stream from QA agent
        space_id = state.get("space_id", "")
        message = state.get("user_request", "")

        try:
            async for event in qa_agent.stream(
                query=message,
                space_public_id=space_id,
                user=user,
                top_k=top_k,
            ):
                # Forward events with transformation
                if event["type"] == "token":
                    yield {"type": "token", "data": event["content"]}
                elif event["type"] == "status":
                    yield {"type": "status", "data": event["content"]}
                elif event["type"] == "sources":
                    yield {"type": "status", "data": "sources_found"}
                elif event["type"] == "result":
                    result = event["content"]
                    # Update state
                    state["subagent_result"] = result
                    state["task_result"] = result
                    state["task_status"] = TaskStatus.COMPLETED
                    yield {"type": "result", "data": result}
                elif event["type"] == "error":
                    state["error"] = event["content"]
                    state["task_status"] = TaskStatus.FAILED
                    yield {"type": "error", "data": event["content"]}

        except Exception as e:
            logger.exception(f"QA streaming failed: {e}")
            state["error"] = str(e)
            state["task_status"] = TaskStatus.FAILED
            yield {"type": "error", "data": str(e)}

    async def chat(
        self,
        message: str,
        space_id: str,
        user_id: Optional[int] = None,
        context: Optional[Dict] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Non-streaming chat interface with unified response format.

        Returns:
            {
                "success": bool,
                "intent": str,
                "agent_type": str,
                "result": Dict,
                "answer": str,
                "sources": List[Dict],
                "error": Optional[str]
            }
        """
        # Collect all events
        intent = None
        agent_type = None
        result = None
        error = None

        async for chunk in self.stream_chat(message, space_id, user_id, context, top_k):
            if chunk["type"] == "intent":
                intent = chunk["data"]
            elif chunk["type"] == "agent_type":
                agent_type = chunk["data"]
            elif chunk["type"] == "result":
                result = chunk["data"]
            elif chunk["type"] == "error":
                error = chunk["data"]

        # Build unified response
        response = {
            "success": error is None and result is not None,
            "intent": intent,
            "agent_type": agent_type or intent or "unknown",
            "result": result or {},
            "error": error,
        }

        # Add QA-specific fields if applicable
        if result and isinstance(result, dict):
            if "answer" in result:
                response["answer"] = result["answer"]
            if "sources" in result:
                response["sources"] = result["sources"]
            if "retrieval_debug" in result:
                response["retrieval_debug"] = result["retrieval_debug"]

        return response
