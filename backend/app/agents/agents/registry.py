"""AgentRegistry - Agent 定义注册与执行。

替换原有的 SubAgentRegistry，支持：
1. 从 .md 文件加载 Agent 定义（增强版 frontmatter）
2. 基于 AgentDefinition 创建独立的 AgentSession
3. Agent 执行（独立会话、sidechain 日志、熔断保护）
4. 降级链（primary_agent 失败时尝试 fallback_agents）

与旧版 SubAgentRegistry 的兼容性：
- 保留 get_schemas() 接口用于 MainAgent prompt 注入
- 保留 execute() 接口但内部改为 AgentSession 模式
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.agents.agents.definition import AgentDefinition
from app.agents.agents.protocol import AgentRequest, AgentResult
from app.agents.agents.session import AgentSession
from app.agents.agents.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from app.agents.skills.parser import SkillMDParser

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册表。

    负责：
    1. 从 .md 文件发现和解析 Agent 定义
    2. 管理 AgentSession 的生命周期
    3. 维护每个 Agent 的熔断器状态
    4. 提供降级链执行
    """

    def __init__(self, parser: Optional[SkillMDParser] = None):
        self._parser = parser or SkillMDParser()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._agent_cache: Dict[str, AgentDefinition] = {}

    # --------------------------------------------------------------------------
    # 定义发现
    # --------------------------------------------------------------------------

    def _load_definition(self, agent_id: str) -> Optional[AgentDefinition]:
        """从 parser 加载 Agent 定义。"""
        if agent_id in self._agent_cache:
            return self._agent_cache[agent_id]

        from app.agents.skills.parser import SkillMDDocument

        doc = self._parser.get_document(agent_id)
        if not doc:
            return None

        definition = self._convert_to_definition(doc)
        self._agent_cache[agent_id] = definition
        return definition

    def _convert_to_definition(self, doc: "SkillMDDocument") -> AgentDefinition:
        """将 SkillMDDocument 转换为 AgentDefinition。"""
        from app.agents.agents.definition import AgentMemoryConfig

        frontmatter = doc.frontmatter or {}

        # 解析 memory 配置
        memory_config = AgentMemoryConfig.from_dict(frontmatter.get("memory"))
        if not memory_config.namespace and doc.capability_type in ("agent", "subagent"):
            memory_config.namespace = doc.skill_id

        return AgentDefinition(
            skill_id=doc.skill_id,
            name=doc.name,
            capability_type=doc.capability_type,
            description=doc.description,
            executor=doc.executor,
            input_schema=doc.input_schema,
            output_summary=doc.output_summary,
            model=doc.model,
            temperature=frontmatter.get("temperature", 0.2),
            color=doc.color,
            tools=doc.tools or [],
            skills=doc.skills or [],
            examples=doc.examples or [],
            system_prompt=doc.system_prompt,
            max_rounds=frontmatter.get("max_rounds", 10),
            permission_mode=frontmatter.get("permission_mode", "plan"),
            memory=memory_config,
            raw_markdown=doc.raw_markdown,
            frontmatter=frontmatter,
            suitable_scenarios=doc.suitable_scenarios,
            workflow_steps=doc.workflow_steps,
        )

    def get_definition(self, agent_id: str) -> Optional[AgentDefinition]:
        """获取 Agent 定义。"""
        return self._load_definition(agent_id)

    def get_schemas(
        self, capability_type: Optional[str] = None, level: str = "l2"
    ) -> List[Dict[str, Any]]:
        """获取 capability schemas（用于 MainAgent prompt 注入）。

        Args:
            capability_type: 按 capability_type 过滤。
            level: "l1" 返回轻量元数据 schema（用于路由决策），
                   "l2" 返回完整 schema（默认，向后兼容）。
        """
        if level == "l1":
            # L1: 直接从 parser 的 metadata-only 列表生成轻量 schema
            docs = self._parser.list_metadata(capability_type=capability_type)
            return [doc.to_capability_schema(level="l1") for doc in docs]

        docs = self._parser.list_documents(capability_type=capability_type)
        return [self._convert_to_definition(doc).to_capability_schema(level="l2") for doc in docs]

    def get_agent_schemas(self, level: str = "l2") -> List[Dict[str, Any]]:
        """获取 Agent schemas。"""
        return self.get_schemas(capability_type="agent", level=level)

    # Backward compatibility alias
    get_subagent_schemas = get_agent_schemas

    def get_skill_schemas(self, level: str = "l2") -> List[Dict[str, Any]]:
        """获取 Skill schemas。"""
        return self.get_schemas(capability_type="skill", level=level)

    def get_tool_schemas(self, level: str = "l2") -> List[Dict[str, Any]]:
        """获取 Tool schemas。"""
        return self.get_schemas(capability_type="tool", level=level)

    # --------------------------------------------------------------------------
    # 熔断器管理
    # --------------------------------------------------------------------------

    def _get_circuit_breaker(self, agent_id: str) -> CircuitBreaker:
        """获取 Agent 的熔断器。"""
        if agent_id not in self._circuit_breakers:
            self._circuit_breakers[agent_id] = CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=60.0,
            )
        return self._circuit_breakers[agent_id]

    # --------------------------------------------------------------------------
    # Agent 执行
    # --------------------------------------------------------------------------

    async def execute_agent(
        self,
        request: AgentRequest,
        db=None,
        llm_client=None,
    ) -> AgentResult:
        """
        执行 Agent 任务（核心入口）。

        1. 读取 Agent 定义
        2. 检查熔断器
        3. 创建 AgentSession（独立上下文）
        4. 执行并返回结果
        """
        agent_id = request.agent_id
        definition = self.get_definition(agent_id)

        if not definition:
            return AgentResult(
                success=False,
                summary=f"Agent '{agent_id}' 未定义。",
                error=f"agent_not_found: {agent_id}",
                agent_id=agent_id,
                correlation_id=request.correlation_id,
            )

        # 检查熔断器
        breaker = self._get_circuit_breaker(agent_id)
        try:
            # 创建独立 AgentSession
            session = AgentSession(
                agent_definition=definition,
                parent_session_id=request.parent_session_id,
                user_id=request.user_id or 0,
                space_public_id=request.space_id,
                db=db,
                llm_client=llm_client,
            )

            # 通过熔断器执行
            result = await breaker.call(session.execute(request))
            return result

        except CircuitBreakerOpen:
            return AgentResult(
                success=False,
                summary=f"Agent '{agent_id}' 当前不可用（熔断器打开），请稍后重试。",
                error="circuit_breaker_open",
                agent_id=agent_id,
                correlation_id=request.correlation_id,
            )

        except Exception as e:
            logger.exception(f"Agent {agent_id} execution failed: {e}")
            return AgentResult(
                success=False,
                summary=f"Agent '{agent_id}' 执行异常: {str(e)}",
                error=str(e),
                agent_id=agent_id,
                correlation_id=request.correlation_id,
            )

    async def execute_with_fallback(
        self,
        request: AgentRequest,
        fallback_agents: Optional[List[str]] = None,
        db=None,
        llm_client=None,
    ) -> AgentResult:
        """
        带降级链的 Agent 执行。

        1. 先尝试 primary_agent（request.agent_id）
        2. 失败则尝试 fallback_agents（按优先级）
        3. 全部失败则返回错误摘要
        """
        agents_to_try = [request.agent_id] + (fallback_agents or [])

        last_error = None
        for agent_id in agents_to_try:
            req = AgentRequest(
                agent_id=agent_id,
                task_description=request.task_description,
                arguments=request.arguments,
                parent_session_id=request.parent_session_id,
                context_summary=request.context_summary,
                allowed_tools=request.allowed_tools,
                max_rounds=request.max_rounds,
                timeout_seconds=request.timeout_seconds,
                correlation_id=request.correlation_id,
                user_id=request.user_id,
                space_id=request.space_id,
            )

            try:
                result = await self.execute_agent(req, db=db, llm_client=llm_client)
                if result.success:
                    return result
                # 失败但返回了结果，记录原因继续尝试下一个
                logger.warning(f"Agent {agent_id} returned failure: {result.error}")
                last_error = result.error

            except asyncio.TimeoutError:
                logger.warning(f"Agent {agent_id} timed out")
                last_error = f"timeout: {agent_id}"

            except Exception as e:
                logger.exception(f"Agent {agent_id} crashed: {e}")
                last_error = str(e)

        # 全部失败
        return AgentResult(
            success=False,
            summary=f"所有可用 Agent 均执行失败（最后错误: {last_error}），请稍后重试或联系管理员。",
            error=f"all_agents_failed: {last_error}",
            correlation_id=request.correlation_id,
        )

    # --------------------------------------------------------------------------
    # 兼容旧接口
    # --------------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        user=None,
        db=None,
        llm_client=None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """兼容旧的 SubAgentRegistry.execute 接口。

        内部转换为 AgentRequest / AgentResult 模式。
        """
        request = AgentRequest(
            agent_id=name,
            task_description=arguments.get("user_request", f"Execute {name}"),
            arguments=arguments,
            parent_session_id=session_id or arguments.get("session_id", ""),
            user_id=getattr(user, "id", None) if user else arguments.get("user_id"),
            space_id=arguments.get("space_public_id") or arguments.get("space_id"),
        )

        result = await self.execute_agent(request, db=db, llm_client=llm_client)

        # 转换为旧格式
        return {
            "agent": name,
            "success": result.success,
            "result": {
                "summary": result.summary,
                "artifacts": result.artifacts,
                "error": result.error,
                "sidechain_id": result.sidechain_id,
            },
            "error": result.error,
        }
