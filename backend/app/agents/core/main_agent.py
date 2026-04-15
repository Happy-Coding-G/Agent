"""主 Agent 编排入口。

MainAgent 负责做 capability routing：
- direct answer
- tool
- skill
- subagent
"""

import json
import logging
import uuid
from typing import AsyncGenerator, Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .state import MainAgentState, AgentType, TaskStatus
from .prompts import CAPABILITY_ROUTING_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# =============================================================================
# SubAgents (legacy helper, currently retained for QA streaming compatibility)
# =============================================================================


async def _get_user(db: AsyncSession, user_id: Optional[int]) -> Optional["Users"]:
    """按 user_id 查询 User 对象，找不到返回 None。"""
    if not user_id:
        return None
    from app.db.models import Users

    result = await db.execute(select(Users).where(Users.id == user_id))
    return result.scalar_one_or_none()


class SubAgents:
    def __init__(
        self, db: AsyncSession, llm_client=None, space_path: Optional[str] = None
    ):
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path
        self._agents: Dict[AgentType, Any] = {}
        self._graphs: Dict[AgentType, Any] = {}
        self._handlers: Dict[AgentType, Any] = {}  # 注册表：AgentType → handler
        self._initialized = False

    def _lazy_init(self):
        if self._initialized:
            return
        try:
            from app.agents.subagents.file_query_agent import FileQueryAgent
            from app.agents.subagents.qa_agent import QAAgent
            from app.agents.subagents.review_agent import ReviewAgent
            from app.agents.subagents.asset_organize_agent import AssetOrganizeAgent
            from app.agents.subagents.trade.agent import TradeAgent

            if self._space_path:
                self._agents[AgentType.FILE_QUERY] = FileQueryAgent(self._space_path)
                self._graphs[AgentType.FILE_QUERY] = self._agents[
                    AgentType.FILE_QUERY
                ].graph

            self._agents[AgentType.QA] = QAAgent(self._db)
            self._graphs[AgentType.QA] = self._agents[AgentType.QA].graph

            self._agents[AgentType.REVIEW] = ReviewAgent(self._db)
            self._graphs[AgentType.REVIEW] = self._agents[AgentType.REVIEW].graph

            self._agents[AgentType.ASSET_ORGANIZE] = AssetOrganizeAgent(self._db)
            self._graphs[AgentType.ASSET_ORGANIZE] = self._agents[
                AgentType.ASSET_ORGANIZE
            ].graph

            self._agents[AgentType.TRADE] = TradeAgent(self._db)
            self._graphs[AgentType.TRADE] = self._agents[AgentType.TRADE].graph

            # 注册各 AgentType 的调用处理器（注册表模式）。
            # 新增 Agent 需要：1) import, 2) 实例化并加入 _agents/_graphs,
            # 3) 编写 _invoke_xxx handler, 4) 在此注册。
            self._handlers = {
                AgentType.FILE_QUERY: self._invoke_file_query,
                AgentType.QA: self._invoke_qa,
                AgentType.REVIEW: self._invoke_review,
                AgentType.ASSET_ORGANIZE: self._invoke_asset_organize,
                AgentType.TRADE: self._invoke_trade,
                AgentType.CHAT: self._invoke_chat,
            }

            self._initialized = True
            logger.info("All sub-agents initialized successfully")
        except ImportError as e:
            logger.error(f"Failed to import subagent classes: {e}")
            raise

    async def invoke_subagent(
        self, agent_type: AgentType, input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._lazy_init()
        # Legacy routing - now handled by Tool Registry. Kept for compat.
        return {
            "error": "Legacy subagent routing is deprecated. Use Tool Registry.",
            "success": False,
        }

    def get_registered_agents(self) -> list[str]:
        self._lazy_init()
        return [agent_type.value for agent_type in self._graphs.keys()]


# =============================================================================
# MainAgent - Tool-Aware ReAct Agent
# =============================================================================
class MainAgent:
    def __init__(
        self, db: AsyncSession, llm_client=None, space_path: Optional[str] = None
    ):
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path
        self._subagents: Optional[SubAgents] = None
        self._tool_registry = None
        self.graph = self._build_graph()

    @property
    def subagents(self) -> SubAgents:
        if self._subagents is None:
            self._subagents = SubAgents(
                db=self._db, llm_client=self._llm_client, space_path=self._space_path
            )
        return self._subagents

    @subagents.setter
    def subagents(self, value):
        self._subagents = value

    def _get_tool_registry(
        self, user, space_id: Optional[str] = None
    ) -> "AgentToolRegistry":
        from app.agents.tools.registry import AgentToolRegistry

        return AgentToolRegistry(
            db=self._db,
            user=user,
            space_id=space_id,
            space_path=self._space_path,
        )

    def _get_skill_registry(self) -> "SkillRegistry":
        from app.agents.skills.registry import SkillRegistry

        return SkillRegistry(db=self._db)

    def _get_subagent_registry(self, user) -> "SubAgentRegistry":
        from app.agents.subagents.registry import SubAgentRegistry

        return SubAgentRegistry(
            db=self._db,
            user=user,
            llm_client=self._llm_client,
            space_path=self._space_path,
        )

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(MainAgentState)

        workflow.add_node("plan", self._plan_step)
        workflow.add_node("execute_tool", self._execute_tool)
        workflow.add_node("execute_skill", self._execute_skill)
        workflow.add_node("execute_subagent", self._execute_subagent)
        workflow.add_node("respond", self._respond_step)
        workflow.add_node("handle_error", self._handle_error)

        workflow.set_entry_point("plan")

        workflow.add_conditional_edges(
            "plan",
            self._plan_router,
            {
                "direct": "respond",
                "tool": "execute_tool",
                "skill": "execute_skill",
                "subagent": "execute_subagent",
                "error": "handle_error",
            },
        )

        workflow.add_conditional_edges(
            "execute_tool",
            self._tool_router,
            {"continue": "plan", "error": "handle_error", "done": "respond"},
        )

        workflow.add_conditional_edges(
            "execute_skill",
            self._post_execution_router,
            {"respond": "respond", "error": "handle_error"},
        )

        workflow.add_conditional_edges(
            "execute_subagent",
            self._post_execution_router,
            {"respond": "respond", "error": "handle_error"},
        )

        workflow.add_edge("respond", END)
        workflow.add_edge("handle_error", END)

        checkpointer = MemorySaver()
        return workflow.compile(checkpointer=checkpointer)

    def _plan_router(self, state: MainAgentState) -> str:
        if state.get("error"):
            return "error"
        if state.get("active_tool"):
            return "tool"
        if state.get("active_skill"):
            return "skill"
        if state.get("active_subagent_call"):
            return "subagent"
        return "direct"

    def _tool_router(self, state: MainAgentState) -> str:
        if state.get("error"):
            return "error"
        # If there are pending tool_calls not yet executed, continue planning
        tool_calls = state.get("tool_calls", [])
        tool_results = state.get("tool_results", [])
        if len(tool_results) < len(tool_calls):
            return "continue"
        return "done"

    def _post_execution_router(self, state: MainAgentState) -> str:
        if state.get("error"):
            return "error"
        return "respond"

    async def _plan_step(self, state: MainAgentState) -> MainAgentState:
        """读取 capability 列表，决定 direct/tool/skill/subagent。"""
        user_request = state.get("user_request", "")
        space_id = state.get("space_id")
        user_id = state.get("user_id")

        # Fetch user for tool registry
        user = None
        if user_id:
            from sqlalchemy import select
            from app.db.models import Users

            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            state["error"] = "User not found"
            return state

        registry = self._get_tool_registry(user, space_id)
        tool_schemas = registry.get_tool_schemas()
        skill_registry = self._get_skill_registry()
        skill_schemas = skill_registry.get_skill_schemas()
        subagent_registry = self._get_subagent_registry(user)
        subagent_schemas = subagent_registry.get_subagent_schemas()

        # Try to detect if this is a QA request for streaming passthrough
        intent = self._simple_intent_detection(user_request)
        state["intent"] = intent

        if not self._llm_client:
            state = await self._fallback_plan(state, registry, intent)
            return state

        try:
            system_prompt = CAPABILITY_ROUTING_SYSTEM_PROMPT.format(
                tool_schemas=json.dumps(tool_schemas, ensure_ascii=False, indent=2),
                skill_schemas=json.dumps(skill_schemas, ensure_ascii=False, indent=2),
                subagent_schemas=json.dumps(
                    subagent_schemas, ensure_ascii=False, indent=2
                ),
                user_id=user_id,
                space_id=space_id or "none",
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_request),
            ]
            response = await self._llm_client.ainvoke(messages)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )

            decision = self._extract_routing_decision(content)
            if decision:
                mode = decision.get("mode")
                state["decision_mode"] = mode

                if mode == "tool":
                    tool_call = {
                        "name": decision.get("name"),
                        "arguments": decision.get("arguments", {}),
                    }
                    state["active_tool"] = tool_call
                    tc = state.get("tool_calls", [])
                    tc.append(tool_call)
                    state["tool_calls"] = tc
                elif mode == "skill":
                    skill_call = {
                        "name": decision.get("name"),
                        "arguments": decision.get("arguments", {}),
                    }
                    state["active_skill"] = skill_call
                    sc = state.get("skill_calls", [])
                    sc.append(skill_call)
                    state["skill_calls"] = sc
                elif mode == "subagent":
                    subagent_call = {
                        "name": decision.get("name"),
                        "arguments": decision.get("arguments", {}),
                    }
                    state["active_subagent_call"] = subagent_call
                    sac = state.get("subagent_calls", [])
                    sac.append(subagent_call)
                    state["subagent_calls"] = sac
                else:
                    state["final_answer"] = decision.get("answer") or content.strip()
            else:
                state["final_answer"] = content.strip()
        except Exception as e:
            logger.warning(f"LLM plan failed, using fallback: {e}")
            state = await self._fallback_plan(state, registry, intent)

        return state

    async def _fallback_plan(
        self, state: MainAgentState, registry, intent: AgentType
    ) -> MainAgentState:
        """当 LLM 不可用时，基于简单意图进行 capability fallback。"""
        user_request = state.get("user_request", "")
        space_id = state.get("space_id")

        # QA and chat go direct
        if intent in (AgentType.QA, AgentType.CHAT):
            state["active_tool"] = None
            state["final_answer"] = None
            return state

        tool_map = {
            AgentType.FILE_QUERY: ("file_search", {"query": user_request}),
            AgentType.REVIEW: (
                "review_document",
                {"doc_id": "", "review_type": "standard"},
            ),
            AgentType.ASSET_ORGANIZE: ("asset_organize", {"asset_ids": []}),
            AgentType.TRADE: ("trade_goal", {"intent": "yield"}),
        }

        if intent in tool_map:
            name, args = tool_map[intent]
            tool_call = {"name": name, "arguments": args}
            state["active_tool"] = tool_call
            tc = state.get("tool_calls", [])
            tc.append(tool_call)
            state["tool_calls"] = tc
        else:
            state["active_tool"] = None

        return state

    def _extract_routing_decision(self, content: str) -> Optional[Dict[str, Any]]:
        """从 LLM 回复中提取 capability routing decision。"""
        try:
            if "```json" in content:
                json_block = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_block = content.split("```")[1].split("```")[0].strip()
            else:
                json_block = content.strip()

            data = json.loads(json_block)

            if "decision" in data:
                decision = data["decision"]
                if not isinstance(decision, dict):
                    return None
                mode = decision.get("mode")
                if mode == "direct":
                    return {"mode": "direct", "answer": decision.get("answer", "")}
                if mode in {"tool", "skill", "subagent"}:
                    return {
                        "mode": mode,
                        "name": decision.get("name"),
                        "arguments": decision.get("arguments", {}),
                    }

            if "tool_call" in data:
                return {
                    "mode": "tool",
                    "name": data["tool_call"].get("name"),
                    "arguments": data["tool_call"].get("arguments", {}),
                }
            if "name" in data and "arguments" in data:
                return {
                    "mode": "tool",
                    "name": data.get("name"),
                    "arguments": data.get("arguments", {}),
                }
        except Exception:
            pass
        return None

    def _simple_intent_detection(self, text: str) -> AgentType:
        text_lower = text.lower()

        if (
            any(kw in text_lower for kw in ["查看", "查找", "搜索", "目录"])
            or "文件" in text_lower
        ):
            return AgentType.FILE_QUERY
        elif any(kw in text_lower for kw in ["审查", "检查", "审核", "质量"]):
            return AgentType.REVIEW
        elif any(kw in text_lower for kw in ["问答", "回答", "问题", "查询", "检索"]):
            return AgentType.QA
        elif any(kw in text_lower for kw in ["整理", "分类", "聚类", "资产"]):
            return AgentType.ASSET_ORGANIZE
        elif any(
            kw in text_lower
            for kw in ["交易", "购买", "出售", "卖出", "买入", "上架", "卖", "买"]
        ):
            return AgentType.TRADE
        else:
            return AgentType.CHAT

    async def _execute_tool(self, state: MainAgentState) -> MainAgentState:
        """通过 registry 执行当前 active_tool。"""
        active_tool = state.get("active_tool")
        if not active_tool:
            return state

        user_id = state.get("user_id")
        user = None
        if user_id:
            from sqlalchemy import select
            from app.db.models import Users

            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            state["error"] = "User not found"
            return state

        registry = self._get_tool_registry(user, state.get("space_id"))
        tool_name = active_tool.get("name")
        arguments = active_tool.get("arguments", {})
        tool = registry.get_tool(tool_name)

        if not tool:
            state["error"] = f"Tool {tool_name} not found"
            return state

        try:
            result = await tool.ainvoke(arguments)
            tr = state.get("tool_results", [])
            tr.append({"tool": tool_name, "result": result})
            state["tool_results"] = tr
            state["active_tool"] = None
        except Exception as e:
            logger.exception(f"Tool execution failed: {e}")
            state["error"] = str(e)

        return state

    async def _execute_skill(self, state: MainAgentState) -> MainAgentState:
        active_skill = state.get("active_skill")
        if not active_skill:
            return state

        try:
            registry = self._get_skill_registry()
            result = await registry.execute(
                active_skill.get("name"),
                active_skill.get("arguments", {}),
            )
            sr = state.get("skill_results", [])
            sr.append(result)
            state["skill_results"] = sr
            state["active_skill"] = None
        except Exception as e:
            logger.exception(f"Skill execution failed: {e}")
            state["error"] = str(e)

        return state

    async def _execute_subagent(self, state: MainAgentState) -> MainAgentState:
        active_subagent = state.get("active_subagent_call")
        if not active_subagent:
            return state

        user_id = state.get("user_id")
        user = None
        if user_id:
            from sqlalchemy import select
            from app.db.models import Users

            result = await self._db.execute(select(Users).where(Users.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            state["error"] = "User not found"
            return state

        try:
            registry = self._get_subagent_registry(user)
            result = await registry.execute(
                active_subagent.get("name"),
                active_subagent.get("arguments", {}),
            )
            sr = state.get("subagent_results", [])
            sr.append(result)
            state["subagent_results"] = sr
            state["active_subagent_call"] = None
        except Exception as e:
            logger.exception(f"Subagent execution failed: {e}")
            state["error"] = str(e)

        return state

    async def _respond_step(self, state: MainAgentState) -> MainAgentState:
        """基于 capability 执行结果或直接回复生成最终中文回复。"""
        final_answer = state.get("final_answer")
        tool_results = state.get("tool_results", [])
        skill_results = state.get("skill_results", [])
        subagent_results = state.get("subagent_results", [])
        user_request = state.get("user_request", "")
        capability_results = {
            "tool_results": tool_results,
            "skill_results": skill_results,
            "subagent_results": subagent_results,
        }

        if final_answer:
            state["task_result"] = {"answer": final_answer, **capability_results}
            state["task_status"] = TaskStatus.COMPLETED
            return state

        if not any([tool_results, skill_results, subagent_results]):
            state["task_result"] = {
                "answer": "收到，请问有什么可以帮您的？",
                **capability_results,
            }
            state["task_status"] = TaskStatus.COMPLETED
            return state

        if not self._llm_client:
            summary_parts = []
            summary_parts.extend(
                f"【tool:{r['tool']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in tool_results
            )
            summary_parts.extend(
                f"【skill:{r['skill']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in skill_results
            )
            summary_parts.extend(
                f"【subagent:{r['subagent']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in subagent_results
            )
            state["task_result"] = {
                "answer": "\n\n".join(summary_parts),
                **capability_results,
            }
            state["task_status"] = TaskStatus.COMPLETED
            return state

        try:
            prompt = (
                "你是一个 helpful 的 AI 助手。根据用户的请求和能力执行结果，生成一段自然、简洁的中文回复。\n\n"
                f"用户请求：{user_request}\n\n"
                "能力执行结果：\n"
                f"{json.dumps(capability_results, ensure_ascii=False, indent=2)}\n\n"
                "请直接回复用户，不要暴露内部 capability 名称和 JSON 结构："
            )
            response = await self._llm_client.ainvoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            state["task_result"] = {"answer": content.strip(), **capability_results}
            state["task_status"] = TaskStatus.COMPLETED
        except Exception as e:
            logger.warning(f"Respond generation failed: {e}")
            summary_parts = []
            summary_parts.extend(
                f"【tool:{r['tool']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in tool_results
            )
            summary_parts.extend(
                f"【skill:{r['skill']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in skill_results
            )
            summary_parts.extend(
                f"【subagent:{r['subagent']}】执行结果：\n{json.dumps(r['result'], ensure_ascii=False, indent=2)}"
                for r in subagent_results
            )
            state["task_result"] = {
                "answer": "\n\n".join(summary_parts),
                **capability_results,
            }
            state["task_status"] = TaskStatus.COMPLETED

        return state

    async def _handle_error(self, state: MainAgentState) -> MainAgentState:
        retry_count = state.get("retry_count", 0)
        if retry_count < 1:
            state["retry_count"] = retry_count + 1
            state["task_status"] = TaskStatus.PENDING
            state["error"] = None
        else:
            state["task_status"] = TaskStatus.FAILED
            error_msg = state.get("error", "未知错误")
            state["task_result"] = {"answer": f"抱歉，处理过程中出现错误：{error_msg}"}
        return state

    # ==========================================================================
    # Streaming Chat (保持现有 SSE 事件协议兼容)
    # ==========================================================================
    async def stream_chat(
        self,
        message: str,
        space_id: str,
        user_id: Optional[int] = None,
        context: Optional[Dict] = None,
        top_k: int = 5,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
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
            "conversation_history": conversation_history or [],
            "context": context or {},
            "error": None,
            "retry_count": 0,
            "tool_calls": [],
            "tool_results": [],
            "active_tool": None,
            "skill_calls": [],
            "skill_results": [],
            "active_skill": None,
            "subagent_calls": [],
            "subagent_results": [],
            "active_subagent_call": None,
            "decision_mode": None,
            "final_answer": None,
        }

        # Detect intent for special paths
        yield {"type": "status", "data": "detecting_intent"}
        intent = self._simple_intent_detection(message)
        initial_state["intent"] = intent
        yield {"type": "intent", "data": intent.value}
        yield {"type": "agent_type", "data": intent.value}

        # QA 保持特殊透传路径（流式）
        if intent == AgentType.QA:
            yield {"type": "status", "data": "running"}
            async for event in self._stream_qa_agent(initial_state, top_k):
                yield event
            yield {"type": "status", "data": "completed"}
            return

        # Standard path: run LangGraph and stream progress
        yield {"type": "status", "data": "planning"}
        try:
            thread_id = initial_state.get("task_id", str(uuid.uuid4()))
            final_state = await self.graph.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
            task_result = final_state.get("task_result", {})
            answer = task_result.get("answer", "")

            if answer:
                # Stream answer as tokens for UI compatibility
                chunk_size = 8
                for i in range(0, len(answer), chunk_size):
                    yield {"type": "token", "data": answer[i : i + chunk_size]}

            yield {"type": "result", "data": task_result}
        except Exception as e:
            logger.exception(f"MainAgent graph execution failed: {e}")
            yield {"type": "error", "data": str(e)}

        yield {"type": "status", "data": "completed"}

    async def _stream_qa_agent(
        self,
        state: MainAgentState,
        top_k: int = 5,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        user = await _get_user(self._db, state.get("user_id"))

        if not user:
            yield {"type": "error", "data": "User not found"}
            return

        qa_agent = None
        try:
            self.subagents._lazy_init()
            qa_agent = self.subagents._agents.get(AgentType.QA)
        except Exception:
            pass

        if not qa_agent:
            yield {"type": "error", "data": "QA Agent not available"}
            return

        space_id = state.get("space_id", "")
        message = state.get("user_request", "")

        try:
            async for event in qa_agent.stream(
                query=message,
                space_public_id=space_id,
                user=user,
                top_k=top_k,
                conversation_history=state.get("conversation_history", []),
            ):
                if event["type"] == "token":
                    yield {"type": "token", "data": event["content"]}
                elif event["type"] == "status":
                    yield {"type": "status", "data": event["content"]}
                elif event["type"] == "sources":
                    yield {"type": "sources", "data": event.get("content", [])}
                elif event["type"] == "result":
                    result = event["content"]
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
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        intent = None
        agent_type = None
        result = None
        error = None
        answer = None

        async for chunk in self.stream_chat(
            message, space_id, user_id, context, top_k, conversation_history
        ):
            if chunk["type"] == "intent":
                intent = chunk["data"]
            elif chunk["type"] == "agent_type":
                agent_type = chunk["data"]
            elif chunk["type"] == "result":
                result = chunk["data"]
                if isinstance(result, dict):
                    answer = result.get("answer")
            elif chunk["type"] == "error":
                error = chunk["data"]

        response = {
            "success": error is None,
            "intent": intent,
            "agent_type": agent_type or intent or "unknown",
            "result": result or {},
            "error": error,
        }

        if answer:
            response["answer"] = answer
        if result and isinstance(result, dict):
            if "sources" in result:
                response["sources"] = result["sources"]
            if "retrieval_debug" in result:
                response["retrieval_debug"] = result["retrieval_debug"]

        return response
