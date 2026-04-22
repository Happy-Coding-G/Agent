"""AgentSession - Agent 独立会话管理。

每个 Agent 实例是一个完整的执行上下文：
- 独立的 LLM 客户端（可配置 model/temperature）
- 独立的工具注册表（只加载声明的工具）
- 独立的数据库 session（不共享 parent 的 transaction）
- 独立的 L3 Memory namespace
- 独立的 Sidechain 日志

与当前直接函数调用的关键区别：
1. Agent 内部自主循环（ReAct 模式），parent 不可见中间步骤
2. 只返回最终摘要，完整过程写入 sidechain
3. 异常由 Agent 自己捕获并转化为结果摘要
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agents.definition import AgentDefinition, AgentMemoryConfig
from app.agents.agents.protocol import AgentRequest, AgentResult
from app.agents.agents.sidechain import SidechainLogger
from app.agents.agents.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class AgentMaxRoundsError(Exception):
    """Agent 达到最大执行轮数。"""

    pass


class TransientError(Exception):
    """可重试的临时错误。"""

    pass


class AgentSession:
    """
    Agent 独立会话。

    每个 Agent 实例是一个完整的执行上下文，不依赖 parent 的任何资源。
    """

    def __init__(
        self,
        agent_definition: AgentDefinition,
        parent_session_id: str,
        user_id: int,
        space_public_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        llm_client=None,
    ):
        self.agent_id = agent_definition.skill_id
        self.definition = agent_definition
        self.parent_session_id = parent_session_id
        self.user_id = user_id
        self.space_public_id = space_public_id

        # 独立的数据库 session（若未传入则延迟创建）
        self._db = db
        self._db_owned = db is None

        # 独立的 LLM 客户端（若未传入则延迟创建）
        self._llm_client = llm_client
        self._llm_owned = llm_client is None

        # 独立的工具注册表（只加载声明的工具）
        self.tool_registry: Optional[Any] = None

        # Skill 加载器（用于加载引用的 Skills）
        self._skill_loader: Optional[Any] = None

        # 独立的记忆服务（namespace 隔离）
        self.memory: Optional[Any] = None

        # Sidechain 日志
        self.sidechain = SidechainLogger(
            session_id=f"{parent_session_id}:{self.agent_id}",
            parent_session_id=parent_session_id,
            agent_id=self.agent_id,
            max_entries=agent_definition.memory.max_sidechain_entries,
        )

        # Agent 内部状态
        self.round_count = 0
        self.max_rounds = agent_definition.max_rounds
        self.tool_calls: List[Dict] = []
        self.thoughts: List[str] = []
        self._history: List[Dict[str, str]] = []
        self._initialized = False

    # --------------------------------------------------------------------------
    # 延迟初始化（避免在构造函数中触发重型依赖）
    # --------------------------------------------------------------------------

    async def _ensure_initialized(self):
        """延迟初始化重型依赖。"""
        if self._initialized:
            return

        from app.db.session import AsyncSessionLocal
        from app.services.memory.unified_memory import UnifiedMemoryService
        from app.agents.tools.registry import AgentToolRegistry
        from app.services.base import get_llm_client
        from sqlalchemy import select
        from app.db.models import Users

        # 1. 独立数据库 session
        if self._db is None:
            self._db = AsyncSessionLocal()

        # 2. 独立 LLM 客户端
        if self._llm_client is None:
            self._llm_client = get_llm_client(
                temperature=self.definition.temperature,
            )

        # 3. 查询用户对象（用于工具注册表）
        user = None
        if self.user_id:
            result = await self._db.execute(select(Users).where(Users.id == self.user_id))
            user = result.scalar_one_or_none()

        # 4. 独立的工具注册表（只加载声明的白名单）
        self.tool_registry = self._build_tool_registry(self.definition.tools, user)

        # 5. 独立的记忆服务
        self.memory = UnifiedMemoryService(
            db=self._db,
            user_id=self.user_id,
            space_id=self.space_public_id,
            session_id=self.parent_session_id,
        )
        # 设置 agent_type namespace
        if self.memory.session_memory:
            self.memory.session_memory.agent_type = self.agent_id

        self._initialized = True

    def _build_tool_registry(self, allowed_tools: List[str], user=None) -> Any:
        """构建只包含白名单工具的注册表。"""
        from app.agents.tools.registry import AgentToolRegistry

        # 创建完整注册表，但只暴露白名单工具
        registry = AgentToolRegistry(
            db=self._db,
            user=user,
            space_id=self.space_public_id,
        )

        # 过滤工具（在初始化后过滤）
        if allowed_tools:
            registry._lazy_init()
            filtered = {}
            for name, tool in registry._tools.items():
                if name in allowed_tools:
                    filtered[name] = tool
            registry._tools = filtered

        return registry

    @property
    def db(self) -> AsyncSession:
        return self._db

    @property
    def llm_client(self):
        return self._llm_client

    # --------------------------------------------------------------------------
    # 核心执行入口
    # --------------------------------------------------------------------------

    async def execute(self, request: AgentRequest) -> AgentResult:
        """执行 Agent 任务（ReAct 自主循环模式）。"""
        await self._ensure_initialized()

        try:
            # 1. 写入 sidechain：任务开始
            await self.sidechain.log("task_start", {
                "request": request.dict(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # 2. ReAct 自主循环模式
            context = await self._build_context(request)
            raw_result = await self._react_loop(context, request)
            summary = await self._summarize_result(raw_result)

            # 4. 持久化 sidechain
            await self.sidechain.log("task_complete", {
                "summary": summary,
                "rounds": self.round_count,
                "tool_calls": len(self.tool_calls),
            })

            # 6. 同步到 L4 记忆
            if self.memory:
                await self.memory.log_event(
                    event_type="agent_task_complete",
                    payload={
                        "agent_id": self.agent_id,
                        "success": True,
                        "summary": summary,
                        "rounds": self.round_count,
                    },
                    session_id=self.parent_session_id,
                    agent_type=self.agent_id,
                )

            return AgentResult(
                success=True,
                summary=summary,
                artifacts=raw_result.get("artifacts", []),
                sidechain_id=self.sidechain.session_id,
                token_usage=getattr(self._llm_client, "total_tokens", None),
                correlation_id=request.correlation_id,
                agent_id=self.agent_id,
                rounds_used=self.round_count,
                tool_calls_count=len(self.tool_calls),
            )

        except AgentMaxRoundsError:
            summary = f"Agent {self.agent_id} 达到最大执行轮数限制 ({self.max_rounds})，任务未完成。"
            await self.sidechain.log("task_timeout", {"max_rounds": self.max_rounds})
            return AgentResult(
                success=False,
                summary=summary,
                error="max_rounds_exceeded",
                sidechain_id=self.sidechain.session_id,
                correlation_id=request.correlation_id,
                agent_id=self.agent_id,
                rounds_used=self.round_count,
            )

        except Exception as e:
            logger.exception(f"Agent {self.agent_id} failed: {e}")
            summary = f"Agent {self.agent_id} 执行异常: {str(e)}"
            await self.sidechain.log("task_error", {"error": str(e)})
            return AgentResult(
                success=False,
                summary=summary,
                error=str(e),
                sidechain_id=self.sidechain.session_id,
                correlation_id=request.correlation_id,
                agent_id=self.agent_id,
                rounds_used=self.round_count,
            )

        finally:
            await self.sidechain.finalize()
            if self._db_owned and self._db:
                await self._db.close()

    # --------------------------------------------------------------------------
    # ReAct 循环（使用 LLM Function Calling）
    # --------------------------------------------------------------------------

    def _get_raw_llm(self):
        """获取原始 LangChain LLM 客户端（支持 bind_tools）。"""
        from unittest.mock import MagicMock, AsyncMock
        # Mock 对象直接返回（测试场景）
        if isinstance(self._llm_client, (MagicMock, AsyncMock)):
            return self._llm_client
        # TrackedLLMClient 包装了真正的 LLM
        if hasattr(self._llm_client, "_client"):
            return self._llm_client._client
        return self._llm_client

    def _get_skill_loader(self):
        """获取 Skill 加载器（延迟初始化）。"""
        if self._skill_loader is None:
            from app.agents.skills.loader import SkillLoader
            self._skill_loader = SkillLoader()
        return self._skill_loader

    async def _react_loop(self, context: str, request: AgentRequest) -> Dict:
        """ReAct 循环：使用 LLM Function Calling 的自主决策循环。

        核心流程：
        1. 构建系统提示（Agent 角色 + 引用的 Skills）
        2. 绑定可用工具到 LLM
        3. 循环：LLM 决定调用工具或直接回答 → 执行工具 → 返回结果 → 重复
        4. 直到 Agent 决定直接回答或达到最大轮数
        """
        raw_llm = self._get_raw_llm()

        # 获取白名单工具（LangChain StructuredTool 实例）
        available_tools = self.tool_registry.get_tools() if self.tool_registry else []
        if self.definition.tools:
            available_tools = [
                t for t in available_tools
                if t.name in self.definition.tools
            ]

        # 绑定工具到 LLM
        llm_with_tools = raw_llm.bind_tools(available_tools)

        # 初始化消息列表
        messages = [
            SystemMessage(content=context),
            HumanMessage(content=request.task_description),
        ]

        while self.round_count < self.max_rounds:
            self.round_count += 1

            # 调用 LLM（会自动决定是否调用工具）
            response = await self._execute_with_retry(
                llm_with_tools.ainvoke(messages),
                max_retries=3,
            )

            content = response.content if hasattr(response, "content") else ""
            tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []

            # 记录 thought（LLM 的 reasoning）
            await self.sidechain.log("thought", {
                "round": self.round_count,
                "content": content,
                "tool_calls": [
                    {"name": tc.get("name"), "args": tc.get("args")}
                    for tc in tool_calls
                ] if tool_calls else [],
            })

            # 如果没有 tool_calls，Agent 决定直接回答，结束循环
            if not tool_calls:
                return {
                    "answer": content,
                    "artifacts": [],
                    "mode": "direct_answer",
                }

            # 执行所有 tool_calls
            tool_messages = []
            for tc in tool_calls:
                tool_name = tc.get("name")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", f"call_{self.round_count}")

                observation = await self._execute_single_tool(tool_name, tool_args)

                tool_messages.append(
                    ToolMessage(
                        content=str(observation)[:2000],  # 截断避免超出 token 限制
                        tool_call_id=tool_call_id,
                    )
                )

                self._add_to_history(
                    f"调用工具: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})",
                    str(observation)[:500],
                )

            # 将 LLM 的回复和工具结果加入消息历史
            messages.append(
                AIMessage(content=content, tool_calls=tool_calls)
            )
            for tm in tool_messages:
                messages.append(tm)

        raise AgentMaxRoundsError()

    async def _execute_single_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """执行单个工具调用。"""
        if not tool_name:
            return "错误: 工具名称未指定。"

        # 权限检查
        if self.definition.tools and tool_name not in self.definition.tools:
            return f"错误: 工具 '{tool_name}' 不在 Agent 的允许列表中。"

        try:
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                return f"错误: 工具 '{tool_name}' 未找到。"

            result = await tool.ainvoke(tool_args)
            self.tool_calls.append({
                "tool": tool_name,
                "args": tool_args,
                "result": result,
            })

            await self.sidechain.log("tool_call", {
                "round": self.round_count,
                "tool": tool_name,
                "args": tool_args,
                "result": str(result)[:500],
            })

            return str(result)

        except Exception as e:
            error_msg = f"工具 '{tool_name}' 执行失败: {str(e)}"
            logger.warning(error_msg)
            await self.sidechain.log("tool_failure", {
                "tool": tool_name,
                "error": str(e),
            })
            return f"工具 {tool_name} 失败: {str(e)}。请尝试替代方案或直接向用户报告。"

    async def _execute_delegate_action(self, action: Dict[str, Any]) -> str:
        """执行委派 Action（Agent Teams 模式）。"""
        sub_agent_id = action.get("agent_id")
        if not sub_agent_id:
            return "错误: 未指定目标 Agent ID。"

        sub_request = AgentRequest(
            agent_id=sub_agent_id,
            task_description=action.get("task_description", ""),
            arguments=action.get("arguments", {}),
            parent_session_id=self.parent_session_id,
            context_summary=f"由 {self.agent_id} 委派: {action.get('task_description', '')}",
        )

        from app.agents.agents.registry import AgentRegistry
        registry = AgentRegistry()
        result = await registry.execute_agent(sub_request)
        return result.summary

    def _add_to_history(self, thought: str, observation: str) -> None:
        """将 thought 和 observation 加入历史。"""
        self._history.append({
            "thought": thought,
            "observation": observation,
            "round": self.round_count,
        })

    # --------------------------------------------------------------------------
    # 上下文构建
    # --------------------------------------------------------------------------

    async def _build_context(self, request: AgentRequest) -> str:
        """构建 Agent 的独立上下文（包含 Skill 引用加载）。"""
        parts = []

        # 1. Agent 基础角色定义（来自 AGENT.md 的 body）
        system_prompt = self.definition.system_prompt or self._default_system_prompt()
        parts.append(system_prompt)

        # 2. 加载引用的 Skills（Claude Code 风格：Skill body 注入上下文）
        if self.definition.skills:
            skill_loader = self._get_skill_loader()
            skill_prompts = []
            for skill_name in self.definition.skills:
                skill_prompt = skill_loader.get_skill_prompt(skill_name)
                if skill_prompt:
                    skill_prompts.append(skill_prompt)
            if skill_prompts:
                parts.append("\n\n# 引用的 Skills\n")
                parts.extend(skill_prompts)

        # 3. Agent 配置信息
        parts.append(f"\n\n# Agent 配置")
        parts.append(f"Agent ID: {self.agent_id}")
        parts.append(f"可用工具: {', '.join(self.definition.tools) if self.definition.tools else '无限制'}")
        parts.append(f"最大轮数: {self.max_rounds}")
        parts.append(f"权限模式: {self.definition.permission_mode}")

        # 4. 任务描述
        parts.append(f"\n# 当前任务\n{request.task_description}")

        # 5. 上下文摘要
        if request.context_summary:
            parts.append(f"\n# 上下文摘要\n{request.context_summary}")

        # 6. Function Calling 指引（简要说明，实际格式由 bind_tools 处理）
        parts.append("""

# 执行指引

你可以根据当前任务自主决定调用哪些工具来收集信息或执行操作。
分析工具返回的结果，决定下一步行动。
当任务完成时，直接给出回答即可。
""")

        return "\n".join(parts)

    def _default_system_prompt(self) -> str:
        """默认系统提示。"""
        return f"""你是 {self.definition.name} Agent。

{self.definition.description}

核心约束：
1. 你只能使用声明的工具，不能访问文件系统或外部网络
2. 每笔交易超过 1 万 credits 需要等待用户审批
3. 如果评估不确定，调用相应工具获取建议
4. 执行完成后记录关键事件
"""

    async def _summarize_result(self, raw_result: Dict[str, Any]) -> str:
        """生成结果摘要。"""
        answer = raw_result.get("answer", "")
        if answer:
            return answer

        artifacts = raw_result.get("artifacts", [])
        if artifacts:
            return f"任务完成，产出 {len(artifacts)} 个结果。"

        return f"Agent {self.agent_id} 执行完成（{self.round_count} 轮，{len(self.tool_calls)} 次工具调用）。"

    # --------------------------------------------------------------------------
    # 重试与容错
    # --------------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        coro,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ) -> Any:
        """指数退避重试。"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await coro
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise last_error

        raise last_error if last_error else RuntimeError("All retries failed")
