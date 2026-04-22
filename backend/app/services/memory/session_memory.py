"""
L3 会话工作记忆 (Session Memory) - Redis 实现

基于 Redis 的短期对话缓存，用于存储活跃的会话上下文。
适用于快速访问最近对话历史，自动过期机制防止内存膨胀。
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
import weakref
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as redis
from app.core.config import settings

logger = logging.getLogger(__name__)


class SessionMemory:
    """
    短期记忆管理器

    使用 Redis 存储活跃的对话上下文，支持：
    - 最近消息缓存 (默认保留 20 条)
    - 会话状态管理
    - 自动过期 (默认 1 小时)
    - 工作记忆提取

    使用方式:
        session_memory = SessionMemory(user_id=1, space_id="space_xxx")
        await session_memory.add_message(session_id, role, content)
        recent_messages = await session_memory.get_recent_messages(session_id, limit=10)
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        user_id: Optional[int] = None,
        space_id: Optional[str] = None,
        agent_type: str = "main",
        max_messages: int = 20,
        ttl_seconds: int = 3600,
    ):
        self._redis = redis_client
        self.user_id = user_id
        self.space_id = space_id
        self.agent_type = agent_type
        self.max_messages = max_messages
        self.ttl_seconds = ttl_seconds
        self._initialized = False
        self._session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._locks_lock = asyncio.Lock()

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """获取会话级别的互斥锁"""
        lock = self._session_locks.get(session_id)
        if lock is not None:
            return lock

        async with self._locks_lock:
            lock = self._session_locks.get(session_id)
            if lock is not None:
                return lock
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
            return lock

    async def _get_redis(self) -> redis.Redis:
        """获取或初始化 Redis 连接"""
        if self._redis is None:
            if not settings.REDIS_URL:
                raise RuntimeError("Redis URL not configured")
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            self._initialized = True
        return self._redis

    def _make_session_key(self, session_id: str) -> str:
        """生成会话 Redis 键"""
        return f"agent:{self.user_id}:{self.space_id}:{session_id}:{self.agent_type}:messages"

    def _make_state_key(self, session_id: str) -> str:
        """生成会话状态 Redis 键"""
        return f"agent:{self.user_id}:{self.space_id}:{session_id}:{self.agent_type}:state"

    def _make_working_memory_key(self, session_id: str) -> str:
        """生成工作记忆 Redis 键"""
        return f"agent:{self.user_id}:{self.space_id}:{session_id}:{self.agent_type}:working_memory"

    # --------------------------------------------------------------------------
    # 旧键兼容方法（过渡使用）
    # --------------------------------------------------------------------------
    def _make_legacy_session_key(self, session_id: str) -> str:
        """[DEPRECATED] 旧版会话 Redis 键"""
        return f"session:{session_id}:messages"

    def _make_legacy_state_key(self, session_id: str) -> str:
        """[DEPRECATED] 旧版会话状态 Redis 键"""
        return f"session:{session_id}:state"

    def _make_legacy_working_memory_key(self, session_id: str) -> str:
        """[DEPRECATED] 旧版工作记忆 Redis 键"""
        return f"session:{session_id}:working_memory"

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        添加消息到短期记忆
        """
        redis_client = await self._get_redis()
        key = self._make_session_key(session_id)

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        await redis_client.lpush(key, json.dumps(message, ensure_ascii=False))
        await redis_client.ltrim(key, 0, self.max_messages - 1)
        await redis_client.expire(key, self.ttl_seconds)

        logger.debug(f"Added message to session {session_id}, role={role}")
        return message

    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        获取最近的消息历史
        """
        redis_client = await self._get_redis()
        key = self._make_session_key(session_id)

        raw_messages = await redis_client.lrange(key, 0, limit - 1)
        messages = [json.loads(msg) for msg in raw_messages]
        messages.reverse()

        return messages

    async def get_session_context(
        self,
        session_id: str,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """
        获取完整的会话上下文（用于 LLM 调用）
        """
        messages = await self.get_recent_messages(session_id, limit=self.max_messages)

        total_chars = sum(len(m["content"]) for m in messages)
        estimated_tokens = total_chars // 2

        context = {
            "session_id": session_id,
            "messages": messages,
            "message_count": len(messages),
            "estimated_tokens": estimated_tokens,
            "has_more": estimated_tokens > max_tokens,
        }

        return context

    async def set_session_state(
        self,
        session_id: str,
        state: dict[str, Any],
    ) -> None:
        """设置会话状态"""
        redis_client = await self._get_redis()
        key = self._make_state_key(session_id)

        await redis_client.setex(
            key,
            self.ttl_seconds,
            json.dumps(state, ensure_ascii=False),
        )

    async def get_session_state(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]:
        """获取会话状态"""
        redis_client = await self._get_redis()
        key = self._make_state_key(session_id)

        data = await redis_client.get(key)
        if data:
            return json.loads(data)
        return None

    async def update_session_state(
        self,
        session_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """更新会话状态 - 使用互斥锁防止竞态条件"""
        async with await self._get_session_lock(session_id):
            current = await self.get_session_state(session_id) or {}
            current.update(updates)
            await self.set_session_state(session_id, current)
            return current

    async def set_working_memory(
        self,
        session_id: str,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """设置工作记忆 - 使用 Redis Hash 避免完整对象读写"""
        redis_client = await self._get_redis()
        wm_key = self._make_working_memory_key(session_id)

        entry = {
            "value": pickle.dumps(value),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        await redis_client.hset(wm_key, key, pickle.dumps(entry))
        await redis_client.expire(wm_key, ttl or self.ttl_seconds)

    async def get_working_memory(
        self,
        session_id: str,
        key: Optional[str] = None,
    ) -> Any:
        """获取工作记忆 - 使用 Redis Hash 支持字段级访问"""
        redis_client = await self._get_redis()
        wm_key = self._make_working_memory_key(session_id)

        if key:
            data = await redis_client.hget(wm_key, key)
            if not data:
                return None
            entry = pickle.loads(data)
            return pickle.loads(entry["value"])
        else:
            all_data = await redis_client.hgetall(wm_key)
            if not all_data:
                return None

            result = {}
            for k, v in all_data.items():
                entry = pickle.loads(v)
                field_key = k.decode() if isinstance(k, bytes) else k
                result[field_key] = pickle.loads(entry["value"])
            return result

    async def clear_session(self, session_id: str) -> None:
        """清除会话的所有短期记忆"""
        redis_client = await self._get_redis()

        keys = [
            self._make_session_key(session_id),
            self._make_state_key(session_id),
            self._make_working_memory_key(session_id),
        ]

        await redis_client.delete(*keys)
        logger.info(f"Cleared session memory for {session_id}")

    async def get_active_sessions(
        self,
        pattern: Optional[str] = None,
    ) -> list[str]:
        """
        获取活跃的会话列表
        """
        redis_client = await self._get_redis()
        pattern = pattern or f"agent:{self.user_id}:{self.space_id}:*:{self.agent_type}:messages"
        keys = await redis_client.keys(pattern)

        session_ids = []
        for key in keys:
            parts = key.split(":")
            if len(parts) >= 4:
                session_ids.append(parts[3])

        return list(set(session_ids))

    async def extend_ttl(self, session_id: str, additional_seconds: int) -> bool:
        """延长会话过期时间"""
        redis_client = await self._get_redis()

        keys = [
            self._make_session_key(session_id),
            self._make_state_key(session_id),
            self._make_working_memory_key(session_id),
        ]

        success = True
        for key in keys:
            current_ttl = await redis_client.ttl(key)
            if current_ttl > 0:
                new_ttl = current_ttl + additional_seconds
                await redis_client.expire(key, new_ttl)
            else:
                success = False

        return success

    # --------------------------------------------------------------------------
    # 兼容旧 API 的方法（@deprecated）
    # --------------------------------------------------------------------------
    async def add_message_legacy(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """[DEPRECATED] 使用旧键格式添加消息"""
        redis_client = await self._get_redis()
        key = self._make_legacy_session_key(session_id)
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        await redis_client.lpush(key, json.dumps(message, ensure_ascii=False))
        await redis_client.ltrim(key, 0, self.max_messages - 1)
        await redis_client.expire(key, self.ttl_seconds)
        return message

    async def get_recent_messages_legacy(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """[DEPRECATED] 使用旧键格式获取最近消息"""
        redis_client = await self._get_redis()
        key = self._make_legacy_session_key(session_id)
        raw_messages = await redis_client.lrange(key, 0, limit - 1)
        messages = [json.loads(msg) for msg in raw_messages]
        messages.reverse()
        return messages

    async def clear_session_legacy(self, session_id: str) -> None:
        """[DEPRECATED] 使用旧键格式清除会话"""
        redis_client = await self._get_redis()
        keys = [
            self._make_legacy_session_key(session_id),
            self._make_legacy_state_key(session_id),
            self._make_legacy_working_memory_key(session_id),
        ]
        await redis_client.delete(*keys)

    async def get_active_sessions_legacy(
        self,
        pattern: str = "session:*:messages",
    ) -> list[str]:
        """[DEPRECATED] 使用旧键模式获取活跃会话"""
        redis_client = await self._get_redis()
        keys = await redis_client.keys(pattern)
        session_ids = []
        for key in keys:
            parts = key.split(":")
            if len(parts) >= 2:
                session_ids.append(parts[1])
        return list(set(session_ids))


# 全局短期记忆实例
_session_memory: Optional[SessionMemory] = None


def get_session_memory(
    user_id: Optional[int] = None,
    space_id: Optional[str] = None,
    agent_type: str = "main",
) -> SessionMemory:
    """获取全局 SessionMemory 实例"""
    global _session_memory
    if _session_memory is None:
        _session_memory = SessionMemory(
            user_id=user_id,
            space_id=space_id,
            agent_type=agent_type,
        )
    return _session_memory
