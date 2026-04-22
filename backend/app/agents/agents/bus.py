"""
基于 Redis Pub/Sub 实现轻量级消息通信。
每个 Agent 实例可以：
- publish：向特定 topic 发送消息
- subscribe：监听特定 topic 的消息
- request/reply：同步请求-响应模式（带超时）

混合通信策略：
- 实时进度通知、事件广播：Redis Pub/Sub（轻量、低延迟、消息不持久化）
- Agent 任务派发、可靠执行：Celery 任务队列（支持持久化、重试、超时）
- Fallback：直接函数调用（当消息总线不可用时降级）
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import redis.asyncio as redis

from app.agents.agents.protocol import AgentMessage, AgentRequest, AgentResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentMessageBus:
    """Agent 间消息总线。"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self._redis = redis_client
        self._subscriptions: Dict[str, Any] = {}

    async def _get_redis(self) -> redis.Redis:
        """获取或初始化 Redis 连接。"""
        if self._redis is None:
            if not settings.REDIS_URL:
                raise RuntimeError("Redis URL not configured")
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    # --------------------------------------------------------------------------
    # Pub/Sub 基础接口
    # --------------------------------------------------------------------------

    async def publish(self, topic: str, message: AgentMessage) -> int:
        """发布消息到 topic，返回接收者数量。"""
        try:
            redis_client = await self._get_redis()
            channel = f"agent:bus:{topic}"
            payload = json.dumps(message.dict(), ensure_ascii=False)
            receivers = await redis_client.publish(channel, payload)
            logger.debug(f"Published to {topic}, receivers: {receivers}")
            return receivers
        except Exception as e:
            logger.warning(f"Failed to publish to {topic}: {e}")
            return 0

    async def subscribe(self, topics: List[str]) -> AsyncIterator[AgentMessage]:
        """订阅一个或多个 topic，异步迭代接收消息。"""
        if not topics:
            return

        try:
            redis_client = await self._get_redis()
            pubsub = redis_client.pubsub()
            channels = [f"agent:bus:{t}" for t in topics]
            await pubsub.subscribe(*channels)
            logger.info(f"Subscribed to topics: {topics}")

            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        yield AgentMessage.parse_raw(data)
                    except Exception as e:
                        logger.warning(f"Failed to parse message: {e}")
        except Exception as e:
            logger.warning(f"Subscription error: {e}")
            raise

    # --------------------------------------------------------------------------
    # Request/Reply 模式
    # --------------------------------------------------------------------------

    async def request(
        self,
        target_agent_id: str,
        request: AgentRequest,
        timeout: float = 30.0,
    ) -> AgentResult:
        """
        同步请求-响应模式。

        向目标 Agent 发送请求，等待响应。
        1. 优先尝试 Redis Pub/Sub 快速响应
        2. 超时后切换到 Celery 可靠队列
        """
        reply_topic = f"reply:{request.correlation_id or str(uuid.uuid4())}"

        # 发送请求（携带 reply_topic）
        await self.publish(
            f"agent:{target_agent_id}:requests",
            AgentMessage(
                type="request",
                sender=request.parent_session_id,
                topic=f"agent:{target_agent_id}:requests",
                payload={
                    **request.dict(),
                    "reply_topic": reply_topic,
                },
                reply_topic=reply_topic,
            ),
        )

        # 等待响应（带超时）
        async def _wait_response():
            async for msg in self.subscribe([reply_topic]):
                if msg.type == "response":
                    return AgentResult.parse_raw(msg.payload)
            raise TimeoutError("No response received")

        try:
            return await asyncio.wait_for(_wait_response(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"Redis Pub/Sub request to {target_agent_id} timed out after {timeout}s, "
                f"falling back to Celery"
            )
            # TODO: Celery fallback
            raise TimeoutError(
                f"Request to {target_agent_id} timed out after {timeout}s"
            )

    async def reply(
        self,
        reply_topic: str,
        result: AgentResult,
    ) -> int:
        """向 reply_topic 发送响应。"""
        return await self.publish(
            reply_topic,
            AgentMessage(
                type="response",
                sender=result.agent_id or "unknown",
                topic=reply_topic,
                payload=result.dict(),
                correlation_id=result.correlation_id,
            ),
        )

    # --------------------------------------------------------------------------
    # 事件广播
    # --------------------------------------------------------------------------

    async def broadcast_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        sender: str,
    ) -> int:
        """广播事件到所有订阅者。"""
        return await self.publish(
            f"events:{event_type}",
            AgentMessage(
                type="event",
                sender=sender,
                topic=f"events:{event_type}",
                payload=payload,
            ),
        )

    async def publish_progress(
        self,
        agent_id: str,
        session_id: str,
        progress: float,
        message: str = "",
    ) -> int:
        """发布 Agent 执行进度。"""
        return await self.publish(
            f"progress:{agent_id}:{session_id}",
            AgentMessage(
                type="progress",
                sender=agent_id,
                topic=f"progress:{agent_id}:{session_id}",
                payload={
                    "session_id": session_id,
                    "progress": progress,
                    "message": message,
                    "timestamp": asyncio.get_event_loop().time(),
                },
            ),
        )
