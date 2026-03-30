"""
统一记忆服务 (Unified Memory Service)

整合 L1/L2/L3 记忆层，提供统一的记忆管理接口。
自动处理记忆层级之间的数据流转和检索策略。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.memory.episodic_memory import EpisodicMemory
from app.services.memory.longterm_memory import LongTermMemory
from app.services.memory.session_memory import SessionMemory, get_session_memory

logger = logging.getLogger(__name__)


class UnifiedMemoryService:
    """
    统一记忆服务

    整合短期、中期、长期记忆，提供：
    - 分层记忆存储和检索
    - 智能记忆合并
    - 上下文组装
    - 记忆持久化协调

    使用方式:
        memory = UnifiedMemoryService(db_session)
        await memory.remember(session_id, user_id, role, content)
        context = await memory.recall(session_id, user_id, query="相关主题")
    """

    def __init__(
        self,
        db: AsyncSession,
        session_memory: Optional[SessionMemory] = None,
    ):
        self.db = db
        self.session_memory = session_memory or get_session_memory()
        self.episodic = EpisodicMemory(db)
        self.longterm = LongTermMemory(db)

    async def remember(
        self,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        persist_to_episodic: bool = True,
    ) -> dict[str, Any]:
        """
        记录记忆（多层存储）

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            role: 角色
            content: 内容
            metadata: 元数据
            persist_to_episodic: 是否持久化到中期记忆

        Returns:
            存储结果
        """
        # L1: 短期记忆（Redis）
        short_term = await self.session_memory.add_message(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )

        result = {
            "short_term": short_term,
            "episodic": None,
        }

        # L2: 中期记忆（PostgreSQL）
        if persist_to_episodic:
            episodic_msg = await self.episodic.add_message(
                session_id=session_id,
                role=role,
                content=content,
                metadata=metadata,
                generate_embedding=True,
            )
            result["episodic"] = {
                "message_id": episodic_msg.message_id,
                "has_embedding": episodic_msg.embedding is not None,
            }

        return result

    async def recall(
        self,
        session_id: str,
        user_id: int,
        query: Optional[str] = None,
        max_tokens: int = 4000,
        include_history: bool = True,
        include_personal: bool = True,
    ) -> dict[str, Any]:
        """
        回忆记忆（多层检索）

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            query: 可选的查询文本（用于语义检索）
            max_tokens: 最大 token 限制
            include_history: 是否包含历史消息
            include_personal: 是否包含个人记忆

        Returns:
            组装好的上下文
        """
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "layers": {},
        }

        # L1: 短期记忆
        short_term = await self.session_memory.get_session_context(
            session_id, max_tokens=max_tokens
        )
        context["layers"]["short_term"] = short_term

        # L2: 中期记忆（语义检索）
        if query:
            similar_messages = await self.episodic.search_similar(
                query=query,
                user_id=user_id,
                limit=5,
                similarity_threshold=0.75,
            )
            context["layers"]["episodic"] = {
                "similar_messages": similar_messages,
                "query": query,
            }

        # L3: 长期记忆
        if include_personal:
            # 获取相关个人记忆
            if query:
                personal_memories = await self.longterm.search_memories(
                    user_id=user_id,
                    query=query,
                    limit=5,
                )
            else:
                personal_memories = []

            # 获取用户偏好
            preferences = await self.longterm.get_preferences_by_type(
                user_id=user_id,
                pref_type="chat",
                min_confidence=0.6,
            )

            context["layers"]["long_term"] = {
                "memories": personal_memories,
                "preferences": preferences,
            }

        # 组装最终消息列表
        context["messages"] = self._assemble_messages(context["layers"])

        return context

    def _assemble_messages(
        self,
        layers: dict[str, Any],
        max_messages: int = 20,
    ) -> list[dict[str, Any]]:
        """
        组装最终的消息列表

        策略：
        1. 系统消息（个人偏好）
        2. 相关历史记忆（来自中期记忆）
        3. 近期对话（来自短期记忆）
        """
        messages = []

        # 添加系统提示（基于个人偏好）
        long_term = layers.get("long_term", {})
        preferences = long_term.get("preferences", {})

        if preferences:
            pref_text = self._format_preferences(preferences)
            messages.append({
                "role": "system",
                "content": f"[用户偏好] {pref_text}",
                "source": "long_term_memory",
            })

        # 添加相关记忆
        memories = long_term.get("memories", [])
        if memories:
            memory_text = "; ".join([m["content"] for m in memories[:3]])
            messages.append({
                "role": "system",
                "content": f"[相关记忆] {memory_text}",
                "source": "long_term_memory",
            })

        # 添加相似历史消息（来自其他会话）
        episodic = layers.get("episodic", {})
        similar = episodic.get("similar_messages", [])
        if similar:
            messages.append({
                "role": "system",
                "content": "[相关历史对话]",
                "source": "episodic_memory",
            })
            for msg in similar[:2]:
                messages.append({
                    "role": "system",
                    "content": f"  - {msg['role']}: {msg['content'][:100]}...",
                    "similarity": msg.get("similarity"),
                })

        # 添加近期对话
        short_term = layers.get("short_term", {})
        recent = short_term.get("messages", [])

        for msg in recent[-max_messages:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
                "source": "short_term_memory",
            })

        return messages

    def _format_preferences(self, preferences: dict[str, Any]) -> str:
        """格式化用户偏好为文本"""
        parts = []
        for key, value in preferences.items():
            parts.append(f"{key}={value}")
        return ", ".join(parts)

    async def create_session(
        self,
        user_id: int,
        title: Optional[str] = None,
    ) -> str:
        """
        创建新会话（跨层初始化）

        Args:
            user_id: 用户 ID
            title: 会话标题

        Returns:
            会话 ID
        """
        # 创建中期记忆会话
        session = await self.episodic.create_session(
            user_id=user_id,
            title=title,
        )

        # 初始化短期记忆状态
        await self.session_memory.set_session_state(
            session_id=session.session_id,
            state={
                "user_id": user_id,
                "created_at": datetime.utcnow().isoformat(),
                "status": "active",
            },
        )

        logger.info(f"Created unified session {session.session_id} for user {user_id}")
        return session.session_id

    async def close_session(
        self,
        session_id: str,
        generate_summary: bool = False,
    ) -> None:
        """
        关闭会话（跨层清理）

        Args:
            session_id: 会话 ID
            generate_summary: 是否生成摘要
        """
        if generate_summary:
            # 生成会话摘要（可存入长期记忆）
            messages = await self.episodic.get_messages(session_id, limit=1000)
            # TODO: 使用 LLM 生成摘要

        # 归档中期记忆
        await self.episodic.archive_session(session_id)

        # 清理短期记忆
        await self.session_memory.clear_session(session_id)

        logger.info(f"Closed session {session_id}")

    async def extract_and_store_memory(
        self,
        user_id: int,
        content: str,
        extraction_type: str = "auto",
    ) -> Optional[dict[str, Any]]:
        """
        从内容中提取并存储长期记忆

        Args:
            user_id: 用户 ID
            content: 内容文本
            extraction_type: 提取类型

        Returns:
            存储的记忆信息
        """
        # 简单的关键词提取（实际项目中可使用 LLM）
        memory_types = {
            "喜欢": "preference",
            "偏好": "preference",
            "需要": "goal",
            "目标": "goal",
            "是": "fact",
            "在": "fact",
        }

        memory_type = "fact"
        for keyword, mtype in memory_types.items():
            if keyword in content:
                memory_type = mtype
                break

        # 存储到长期记忆
        memory = await self.longterm.add_memory(
            user_id=user_id,
            content=content[:500],  # 限制长度
            memory_type=memory_type,
            importance=5,
            source="extraction",
        )

        return {
            "memory_id": memory.memory_id,
            "type": memory_type,
            "content": memory.content,
        }

    async def get_user_memory_stats(self, user_id: int) -> dict[str, Any]:
        """
        获取用户记忆统计（跨层）

        Args:
            user_id: 用户 ID

        Returns:
            记忆统计信息
        """
        # 短期记忆统计（从 Redis）
        active_sessions = await self.session_memory.get_active_sessions()

        # 中期记忆统计
        session_stats = await self.episodic.get_session_stats(user_id)

        # 长期记忆统计
        memory_summary = await self.longterm.get_memory_summary(user_id)

        return {
            "short_term": {
                "active_sessions": len(active_sessions),
            },
            "episodic": session_stats,
            "long_term": memory_summary,
        }


class MemoryAugmentedContext:
    """
    记忆增强上下文

    为 LLM 调用提供增强的上下文信息。
    """

    def __init__(self, memory_service: UnifiedMemoryService):
        self.memory = memory_service

    async def build_prompt_context(
        self,
        session_id: str,
        user_id: int,
        current_message: str,
        system_prompt: Optional[str] = None,
    ) -> list[dict[str, str]]:
        """
        构建带记忆的 Prompt 上下文

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            current_message: 当前用户消息
            system_prompt: 基础系统提示

        Returns:
            消息列表，可直接用于 LLM
        """
        messages = []

        # 基础系统提示
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 检索相关记忆
        context = await self.memory.recall(
            session_id=session_id,
            user_id=user_id,
            query=current_message,
        )

        # 添加记忆上下文
        for msg in context["messages"]:
            if msg.get("source") == "long_term_memory":
                # 长期记忆作为系统提示的一部分
                messages.append({
                    "role": "system",
                    "content": msg["content"],
                })

        # 添加对话历史
        for msg in context["messages"]:
            if msg.get("source") == "short_term_memory":
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        # 添加当前消息
        messages.append({"role": "user", "content": current_message})

        return messages
