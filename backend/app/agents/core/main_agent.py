# 主控智能体负责能力路由

import json
import logging
import uuid
from typing import TYPE_CHECKING, AsyncGenerator, Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .state import MainAgentState, AgentType, TaskStatus
from .prompts import CAPABILITY_ROUTING_SYSTEM_PROMPT
from app.agents.agents.protocol import AgentRequest

if TYPE_CHECKING:
    from app.db.models import Users
    from app.services.memory.unified_memory import UnifiedMemoryService
    from app.agents.tools.registry import AgentToolRegistry
    from app.agents.skills.registry import SkillRegistry
    from app.agents.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)


# 按用户标识查询用户对象，找不到时返回空值
async def _get_user(db: AsyncSession, user_id: Optional[int]) -> Optional["Users"]:
    if not user_id:
        return None
    from app.db.models import Users

    result = await db.execute(select(Users).where(Users.id == user_id))
    return result.scalar_one_or_none()


class SubAgents:
    # 兼容占位类：旧版子智能体封装已下线，保留最小接口避免迁移期间直接失效。
    def __init__(
        self, db: AsyncSession, llm_client=None, space_path: Optional[str] = None
    ):
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path

    async def invoke_subagent(
        self, agent_type: AgentType, input_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "subagent": agent_type.value,
            "error": "SubAgents compatibility shim is deprecated. Use AgentRegistry or Tool Registry.",
            "success": False,
        }

    def get_registered_agents(self) -> list[str]:
        return []


# =============================================================================
# 主控智能体：具备工具感知能力的推理-行动执行器
# =============================================================================
class MainAgent:
    def __init__(
        self,
        db: AsyncSession,
        llm_client=None,
        space_path: Optional[str] = None,
        memory_service: Optional["UnifiedMemoryService"] = None,
    ):
        self._db = db
        self._llm_client = llm_client
        self._space_path = space_path
        self._memory = memory_service
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

    def _get_agent_registry(self) -> "AgentRegistry":
        from app.agents.agents.registry import AgentRegistry

        return AgentRegistry()

    def _format_capability_payload(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except TypeError:
            return str(payload)

    def _build_capability_summary_parts(
        self,
        tool_results: List[Dict[str, Any]],
        skill_results: List[Dict[str, Any]],
        subagent_results: List[Dict[str, Any]],
    ) -> List[str]:
        parts = []
        parts.extend(
            f"【tool:{r.get('tool', 'unknown')}】执行结果：\n{self._format_capability_payload(r.get('result'))}"
            for r in tool_results
        )
        parts.extend(
            f"【skill:{r.get('skill', 'unknown')}】执行结果：\n{self._format_capability_payload(r.get('result'))}"
            for r in skill_results
        )
        parts.extend(
            f"【subagent:{r.get('subagent', 'unknown')}】"
            f"{'✓' if r.get('success') else '✗'} {r.get('summary') or r.get('error', '')}"
            for r in subagent_results
        )
        return parts

    def _build_capability_prompt_lines(
        self,
        tool_results: List[Dict[str, Any]],
        skill_results: List[Dict[str, Any]],
        subagent_results: List[Dict[str, Any]],
    ) -> List[str]:
        lines = []
        lines.extend(
            f"工具 {r.get('tool', 'unknown')} 执行结果: {self._format_capability_payload(r.get('result'))}"
            for r in tool_results
        )
        lines.extend(
            f"技能 {r.get('skill', 'unknown')} 执行结果: {self._format_capability_payload(r.get('result'))}"
            for r in skill_results
        )
        for r in subagent_results:
            subagent_name = r.get("subagent", "unknown")
            if r.get("success"):
                lines.append(f"SubAgent {subagent_name} 执行成功: {r.get('summary', '')}")
            else:
                lines.append(f"SubAgent {subagent_name} 执行失败: {r.get('error', '未知错误')}")
        return lines

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
        workflow.add_conditional_edges(
            "handle_error",
            self._error_router,
            {"retry": "plan", "end": END},
        )

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
        tool_calls = state.get("tool_calls", [])
        tool_results = state.get("tool_results", [])
        if len(tool_results) < len(tool_calls):
            return "continue"
        return "done"

    def _post_execution_router(self, state: MainAgentState) -> str:
        if state.get("error"):
            return "error"
        return "respond"

    def _error_router(self, state: MainAgentState) -> str:
        if (
            state.get("task_status") == TaskStatus.PENDING
            and state.get("retry_count", 0) > 0
            and not state.get("error")
        ):
            return "retry"
        return "end"

    # 读取能力列表，决策路由
    async def _plan_step(self, state: MainAgentState) -> MainAgentState:
        user_request = state.get("user_request", "")
        space_id = state.get("space_id")
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

        registry = self._get_tool_registry(user, space_id)
        tool_schemas = registry.get_tool_schemas(level="l1")
        skill_registry = self._get_skill_registry()
        skill_schemas = skill_registry.get_skill_schemas(level="l1")
        agent_registry = self._get_agent_registry()
        agent_schemas = agent_registry.get_agent_schemas(level="l1")

        intent = self._simple_intent_detection(user_request)
        state["intent"] = intent

        if not self._llm_client:
            state = await self._fallback_plan(state, registry, intent)
            return state

        try:
            system_prompt = CAPABILITY_ROUTING_SYSTEM_PROMPT.format(
                tool_schemas=json.dumps(tool_schemas, ensure_ascii=False, indent=2),
                skill_schemas=json.dumps(skill_schemas, ensure_ascii=False, indent=2),
                agent_schemas=json.dumps(
                    agent_schemas, ensure_ascii=False, indent=2
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
                    subagent_calls = state.get("subagent_calls", [])
                    subagent_calls.append(subagent_call)
                    state["subagent_calls"] = subagent_calls
                else:
                    state["final_answer"] = decision.get("answer") or content.strip()
            else:
                state["final_answer"] = content.strip()
        except Exception as e:
            logger.warning(f"LLM plan failed, using fallback: {e}")
            state = await self._fallback_plan(state, registry, intent)

        return state

    # 当模型不可用时，基于简单意图执行降级路由
    async def _fallback_plan(
        self, state: MainAgentState, registry, intent: AgentType
    ) -> MainAgentState:
        user_request = state.get("user_request", "")
        space_id = state.get("space_id")

        if intent in (AgentType.QA, AgentType.CHAT):
            state["active_tool"] = None
            state["final_answer"] = None
            return state

        subagent_map = {
            AgentType.REVIEW: (
                "review_workflow",
                {"doc_id": "", "review_type": "standard"},
            ),
            AgentType.ASSET_ORGANIZE: (
                "asset_organize_workflow",
                {"asset_ids": [], "space_id": space_id or ""},
            ),
            AgentType.TRADE: (
                "trade_workflow",
                {"action": "purchase", "space_id": space_id or "", "payload": {}},
            ),
        }

        if intent in subagent_map:
            name, args = subagent_map[intent]
            subagent_call = {"name": name, "arguments": args}
            state["active_subagent_call"] = subagent_call
            sac = state.get("subagent_calls", [])
            sac.append(subagent_call)
            state["subagent_calls"] = sac
        else:
            state["active_tool"] = None

        return state

    def _extract_routing_decision(self, content: str) -> Optional[Dict[str, Any]]:
        # 从模型回复中提取能力路由决策。
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
        text_lower = text.lower().strip()

        if (
            any(kw in text_lower for kw in ["查看", "查找", "搜索", "目录"])
            or "文件" in text_lower
        ):
            return AgentType.FILE_QUERY
        elif any(kw in text_lower for kw in ["审查", "检查", "审核", "质量"]):
            return AgentType.REVIEW
        elif any(kw in text_lower for kw in ["整理", "分类", "聚类", "资产"]):
            return AgentType.ASSET_ORGANIZE
        elif any(
            kw in text_lower
            for kw in ["交易", "购买", "出售", "卖出", "买入", "上架", "卖", "买"]
        ):
            return AgentType.TRADE

        qa_keywords = [
            "问答", "回答", "问题", "查询", "检索",
            "什么", "解释", "区别", "对比", "比较", "差异",
            "如何", "怎么", "为什么", "谁", "哪里", "哪些",
            "怎样", "是什么意思", "是什么", "如何理解",
            "what", "explain", "difference", "differences", "compare",
            "how", "why", "who", "where", "which", "vs", "versus",
            "meaning of", "what is", "what are",
        ]
        if any(kw in text_lower for kw in qa_keywords):
            return AgentType.QA

        chat_keywords = [
            "你好", "hello", "hi", "在吗", "谢谢", "再见", "help",
            "帮我", "写", "总结", "生成", "翻译",
        ]
        if len(text_lower) <= 8 or any(kw in text_lower for kw in chat_keywords):
            return AgentType.CHAT

        return AgentType.CHAT

    async def _execute_tool(self, state: MainAgentState) -> MainAgentState:
        # 通过工具注册表执行当前待执行工具。
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

    # 通过智能体注册表执行任务（独立会话模式）
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
            registry = self._get_agent_registry()

            # 构建上下文摘要（不传递完整历史）
            context_summary = await self._build_context_summary(state)

            # 创建智能体请求
            request = AgentRequest(
                agent_id=active_subagent.get("name"),
                task_description=state.get("user_request", ""),
                arguments=active_subagent.get("arguments", {}),
                parent_session_id=state.get("session_id", ""),
                context_summary=context_summary,
                user_id=user_id,
                space_id=state.get("space_id"),
            )

            # 通过智能体注册表执行（独立会话）
            result = await registry.execute_agent(
                request,
                db=self._db,
                llm_client=self._llm_client,
            )

            # 记录结果
            subagent_results = state.get("subagent_results", [])
            subagent_results.append({
                "subagent": active_subagent.get("name"),
                "success": result.success,
                "summary": result.summary,
                "artifacts": result.artifacts,
                "error": result.error,
                "sidechain_id": result.sidechain_id,
            })
            state["subagent_results"] = subagent_results
            state["active_subagent_call"] = None

            # 将摘要存入最终答案
            if result.success:
                state["final_answer"] = result.summary

            # 记录到记忆层
            if self._memory:
                await self._memory.log_event(
                    event_type="agent_invoked",
                    payload={
                        "agent_id": active_subagent.get("name"),
                        "success": result.success,
                        "summary": result.summary[:200],
                    },
                    session_id=state.get("session_id"),
                    agent_type="main",
                )

        except Exception as e:
            logger.exception(f"Subagent execution failed: {e}")
            state["error"] = str(e)

        return state

    async def _build_context_summary(self, state: MainAgentState) -> str:
        # 构建传递给智能体的上下文摘要。
        # 原则：
        # - 只包含智能体完成任务所需的关键信息
        # - 不包含完整的对话历史
        # - 不包含与当前任务无关的记忆
        # - 长度控制在约 1000-2000 个模型令牌以内
        parts = []

        # 1. 当前用户请求
        parts.append(f"用户请求: {state.get('user_request', '')}")

        # 2. 用户意图（如果已识别）
        if state.get("intent"):
            parts.append(f"识别意图: {state['intent'].value}")

        # 3. 相关记忆（从长期记忆层检索）
        if self._memory:
            try:
                relevant_memories = await self._memory.longterm.search_memories(
                    user_id=state.get("user_id", 0),
                    query=state.get("user_request", ""),
                    limit=3,
                )
                if relevant_memories:
                    parts.append("相关历史:\n" + "\n".join(
                        m.get("content", "") for m in relevant_memories
                    ))
            except Exception:
                pass

        # 4. 最近 2-3 轮对话（非完整历史）
        recent_messages = state.get("conversation_history", [])[-6:]
        if recent_messages:
            parts.append("最近对话:\n" + "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:100]}"
                for m in recent_messages
            ))

        return "\n\n".join(parts)

    async def _respond_step(self, state: MainAgentState) -> MainAgentState:
        # 基于能力执行结果或直接回复生成最终中文回复。
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
            summary_parts = self._build_capability_summary_parts(
                tool_results, skill_results, subagent_results
            )
            state["task_result"] = {
                "answer": "\n\n".join(summary_parts),
                **capability_results,
            }
            state["task_status"] = TaskStatus.COMPLETED
            return state

        try:
            capability_summaries = self._build_capability_prompt_lines(
                tool_results, skill_results, subagent_results
            )

            prompt = (
                "你是一个 helpful 的 AI 助手。根据用户的请求和能力执行结果，生成一段自然、简洁的中文回复。\n\n"
                f"用户请求：{user_request}\n\n"
                "执行结果摘要：\n"
                + "\n".join(capability_summaries)
                + "\n\n请直接回复用户，不要暴露内部 capability 名称和 JSON 结构："
            )
            response = await self._llm_client.ainvoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            state["task_result"] = {"answer": content.strip(), **capability_results}
            state["task_status"] = TaskStatus.COMPLETED
        except Exception as e:
            logger.warning(f"Respond generation failed: {e}")
            summary_parts = self._build_capability_summary_parts(
                tool_results, skill_results, subagent_results
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
    # 流式对话（保持现有服务端事件流协议兼容）
    # ==========================================================================
    async def stream_chat(
        self,
        message: str,
        space_id: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict] = None,
        top_k: int = 5,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # 1. 如果传入会话标识且记忆服务可用，则召回历史上下文
        conversation_history: List[Dict[str, str]] = []
        if session_id and self._memory:
            recalled = await self._memory.recall_chat_context(
                session_id=session_id,
                agent_type="main",
                max_messages=20,
            )
            conversation_history = recalled

        initial_state: MainAgentState = {
            "user_request": message,
            "space_id": space_id,
            "user_id": user_id,
            "session_id": session_id,
            "intent": None,
            "active_subagent": None,
            "subagent_result": None,
            "task_id": str(uuid.uuid4()),
            "task_status": TaskStatus.PENDING,
            "task_result": None,
            "conversation_history": conversation_history,
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

        yield {"type": "status", "data": "detecting_intent"}
        intent = self._simple_intent_detection(message)
        initial_state["intent"] = intent
        yield {"type": "intent", "data": intent.value}
        yield {"type": "agent_type", "data": intent.value}

        yield {"type": "status", "data": "planning"}
        has_error = False
        try:
            thread_id = initial_state.get("task_id", str(uuid.uuid4()))
            final_state = await self.graph.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
            task_result = final_state.get("task_result", {})
            answer = task_result.get("answer", "")

            if answer:
                chunk_size = 8
                for i in range(0, len(answer), chunk_size):
                    yield {"type": "token", "data": answer[i : i + chunk_size]}

            yield {"type": "result", "data": task_result}
        except Exception as e:
            logger.exception(f"MainAgent graph execution failed: {e}")
            has_error = True
            yield {"type": "error", "data": str(e)}

        if not has_error:
            yield {"type": "status", "data": "completed"}

    async def chat(
        self,
        message: str,
        space_id: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        intent = None
        agent_type = None
        result = None
        error = None
        answer = None

        async for chunk in self.stream_chat(
            message, space_id, user_id, session_id, context, top_k
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
