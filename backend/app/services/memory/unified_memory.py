"""
统一记忆服务 (Unified Memory Service)

整合 L3/L4/L5 记忆层，提供统一的记忆管理接口。
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

    整合 L3 会话工作记忆、L4 情节记忆、L5 长期记忆，提供：
    - 分层记忆存储和检索
    - 智能记忆合并
    - 上下文组装
    - 记忆持久化协调
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        space_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_memory: Optional[SessionMemory] = None,
    ):
        self.db = db
        self.user_id = user_id
        self.space_id = space_id
        self.session_id = session_id
        self.session_memory = session_memory or get_session_memory(
            user_id=user_id, space_id=space_id, agent_type="main"
        )
        self.episodic = EpisodicMemory(db)
        self.longterm = LongTermMemory(db)

    # ========================================================================
    # 跨层聊天记忆接口
    # ========================================================================

    async def remember_chat_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_type: str = "main",
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        记录一轮对话到 L3 Redis + L4 PostgreSQL
        """
        # L3: Redis
        if self.session_memory.agent_type != agent_type:
            self.session_memory = SessionMemory(
                user_id=self.user_id,
                space_id=self.space_id,
                agent_type=agent_type,
            )

        short_term = await self.session_memory.add_message(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )

        # L4: PostgreSQL
        episodic_msg = await self.episodic.add_message(
            session_id=session_id,
            role=role,
            content=content,
            user_id=self.user_id,
            metadata={**(metadata or {}), "agent_type": agent_type},
            generate_embedding=True,
        )

        return {
            "short_term": short_term,
            "episodic": {
                "message_id": episodic_msg.message_id,
                "has_embedding": episodic_msg.embedding is not None,
            },
        }

    async def recall_chat_context(
        self,
        session_id: str,
        query: Optional[str] = None,
        agent_type: str = "main",
        max_messages: int = 20,
    ) -> list[dict[str, Any]]:
        """
        召回聊天上下文：优先读 L3 Redis，缺失时从 L4 回填
        """
        if self.session_memory.agent_type != agent_type:
            self.session_memory = SessionMemory(
                user_id=self.user_id,
                space_id=self.space_id,
                agent_type=agent_type,
            )

        # 优先读 L3
        l3_messages = await self.session_memory.get_recent_messages(
            session_id, limit=max_messages
        )

        if l3_messages:
            return [
                {"role": m["role"], "content": m["content"]}
                for m in l3_messages
            ]

        # L3 缺失，从 L4 回填
        l4_messages = await self.episodic.get_messages(
            session_id=session_id, limit=max_messages
        )
        if l4_messages:
            # 同步回 L3
            for msg in l4_messages:
                await self.session_memory.add_message(
                    session_id=session_id,
                    role=msg.role,
                    content=msg.content,
                    metadata=msg.metadata,
                )

        return [
            {"role": msg.role, "content": msg.content}
            for msg in l4_messages
        ]

    # ========================================================================
    # L3 工作记忆接口
    # ========================================================================

    async def set_working_memory(
        self,
        key: str,
        value: Any,
        session_id: Optional[str] = None,
        agent_type: str = "main",
    ) -> None:
        """操作 L3 工作记忆"""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("session_id is required for working memory")

        if self.session_memory.agent_type != agent_type:
            self.session_memory = SessionMemory(
                user_id=self.user_id,
                space_id=self.space_id,
                agent_type=agent_type,
            )

        await self.session_memory.set_working_memory(sid, key, value)

    async def get_working_memory(
        self,
        key: str,
        session_id: Optional[str] = None,
        agent_type: str = "main",
    ) -> Any:
        """读取 L3 工作记忆"""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("session_id is required for working memory")

        if self.session_memory.agent_type != agent_type:
            self.session_memory = SessionMemory(
                user_id=self.user_id,
                space_id=self.space_id,
                agent_type=agent_type,
            )

        return await self.session_memory.get_working_memory(sid, key)

    # ========================================================================
    # L4 事件投影接口
    # ========================================================================

    async def log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: Optional[str] = None,
        agent_type: str = "main",
    ) -> Any:
        """
        写入 L4 事件（以 ConversationMessages role="system" + metadata 标记 event_type）
        """
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("session_id is required for logging event")

        content = payload.get("message") or payload.get("summary") or json.dumps(payload, ensure_ascii=False)
        metadata = {
            "event_type": event_type,
            **payload,
        }

        return await self.episodic.add_event(
            session_id=sid,
            event_type=event_type,
            payload=payload,
            user_id=self.user_id,
            agent_type=agent_type,
        )

    async def get_session_events(
        self,
        session_id: Optional[str] = None,
        event_types: Optional[list[str]] = None,
        agent_type: str = "main",
    ) -> list[dict[str, Any]]:
        """读取 L4 事件投影"""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("session_id is required for getting events")

        return await self.episodic.get_events(
            session_id=sid,
            event_types=event_types,
            agent_type=agent_type,
        )

    # ========================================================================
    #  legacy 多层接口（保留兼容）
    # ========================================================================

    async def remember(
        self,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        persist_to_episodic: bool = True,
    ) -> dict[str, Any]:
        """记录记忆（多层存储）- 兼容旧接口"""
        return await self.remember_chat_turn(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
        )

    async def recall(
        self,
        session_id: str,
        user_id: int,
        query: Optional[str] = None,
        max_tokens: int = 4000,
        include_history: bool = True,
        include_personal: bool = True,
    ) -> dict[str, Any]:
        """回忆记忆（多层检索）- 兼容旧接口"""
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "layers": {},
        }

        short_term = await self.session_memory.get_session_context(
            session_id, max_tokens=max_tokens
        )
        context["layers"]["short_term"] = short_term

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

        if include_personal:
            if query:
                personal_memories = await self.longterm.search_memories(
                    user_id=user_id,
                    query=query,
                    limit=5,
                )
            else:
                personal_memories = []

            preferences = await self.longterm.get_preferences_by_type(
                user_id=user_id,
                pref_type="chat",
                min_confidence=0.6,
            )

            context["layers"]["long_term"] = {
                "memories": personal_memories,
                "preferences": preferences,
            }

        context["messages"] = self._assemble_messages(context["layers"])
        return context

    def _assemble_messages(
        self,
        layers: dict[str, Any],
        max_messages: int = 20,
    ) -> list[dict[str, Any]]:
        messages = []

        long_term = layers.get("long_term", {})
        preferences = long_term.get("preferences", {})

        if preferences:
            pref_text = self._format_preferences(preferences)
            messages.append({
                "role": "system",
                "content": f"[用户偏好] {pref_text}",
                "source": "long_term_memory",
            })

        memories = long_term.get("memories", [])
        if memories:
            memory_text = "; ".join([m["content"] for m in memories[:3]])
            messages.append({
                "role": "system",
                "content": f"[相关记忆] {memory_text}",
                "source": "long_term_memory",
            })

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
        parts = []
        for key, value in preferences.items():
            parts.append(f"{key}={value}")
        return ", ".join(parts)

    async def create_session(
        self,
        user_id: int,
        title: Optional[str] = None,
    ) -> str:
        """创建新会话（跨层初始化）"""
        session = await self.episodic.create_session(
            user_id=user_id,
            title=title,
        )

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
        """关闭会话（跨层清理）"""
        if generate_summary:
            messages = await self.episodic.get_messages(session_id, limit=1000)
            # TODO: 使用 LLM 生成摘要

        await self.episodic.archive_session(session_id)
        await self.session_memory.clear_session(session_id)
        logger.info(f"Closed session {session_id}")

    async def extract_and_store_memory(
        self,
        user_id: int,
        content: str,
        extraction_type: str = "auto",
    ) -> Optional[dict[str, Any]]:
        """从内容中提取并存储长期记忆"""
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

        memory = await self.longterm.add_memory(
            user_id=user_id,
            content=content[:500],
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
        """获取用户记忆统计（跨层）"""
        active_sessions = await self.session_memory.get_active_sessions()
        session_stats = await self.episodic.get_session_stats(user_id)
        memory_summary = await self.longterm.get_memory_summary(user_id)

        return {
            "short_term": {
                "active_sessions": len(active_sessions),
            },
            "episodic": session_stats,
            "long_term": memory_summary,
        }


import json  # noqa: E402


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
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        context = await self.memory.recall(
            session_id=session_id,
            user_id=user_id,
            query=current_message,
        )

        for msg in context["messages"]:
            if msg.get("source") == "long_term_memory":
                messages.append({
                    "role": "system",
                    "content": msg["content"],
                })

        for msg in context["messages"]:
            if msg.get("source") == "short_term_memory":
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        messages.append({"role": "user", "content": current_message})

        return messages
