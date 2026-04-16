"""
L4 中期记忆 (Episodic Memory) - PostgreSQL 实现

基于 PostgreSQL 的持久化对话历史存储，支持向量检索。
适用于：
- 跨会话的历史消息检索
- 基于语义相似度的记忆召回
- 对话摘要和长期存储
- 统一事件流投影
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_client import embed_documents_with_fallback, embed_query_with_fallback
from app.db.models import ConversationMessages, ConversationSessions
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    中期记忆管理器

    使用 PostgreSQL 存储对话历史，支持向量检索：
    - 会话管理（创建、更新、归档）
    - 消息存储（支持向量嵌入）
    - 语义检索（基于 pgvector）
    - 统一事件流投影
    - 会话摘要生成
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        user_id: int,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConversationSessions:
        """创建新会话"""
        session_id = snowflake_id()
        session = ConversationSessions(
            id=session_id,
            session_id=f"sess_{session_id}",
            user_id=user_id,
            title=title or "新会话",
            status="active",
            metadata=metadata or {},
        )

        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)

        logger.info(f"Created session {session.session_id} for user {user_id}")
        return session

    async def get_session(
        self,
        session_id: str,
        user_id: Optional[int] = None,
    ) -> Optional[ConversationSessions]:
        """获取会话信息"""
        query = select(ConversationSessions).where(
            ConversationSessions.session_id == session_id
        )

        if user_id:
            query = query.where(ConversationSessions.user_id == user_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        generate_embedding: bool = True,
    ) -> ConversationMessages:
        """添加消息到会话"""
        message_id = snowflake_id()
        message = ConversationMessages(
            id=message_id,
            message_id=f"msg_{message_id}",
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )

        if generate_embedding and content:
            try:
                vector, model = await embed_query_with_fallback(content)
                message.embedding = vector
                message.metadata["embedding_model"] = model
            except Exception as exc:
                logger.warning(f"Failed to generate embedding: {exc}")

        self.db.add(message)

        session = await self.get_session(session_id)
        if session:
            session.message_count = (session.message_count or 0) + 1
            session.last_message_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(message)

        logger.debug(f"Added message {message.message_id} to session {session_id}")
        return message

    # ========================================================================
    # 统一事件流投影
    # ========================================================================

    async def add_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        agent_type: str = "main",
        generate_embedding: bool = False,
    ) -> ConversationMessages:
        """
        添加事件到统一事件流

        通过 ConversationMessages role="system" + metadata["event_type"] 区分事件类型。
        支持的事件类型：
        - chat_turn, tool_call, subagent_invoke
        - trade_offer, trade_accept, trade_reject
        - qa_citation, approval_required, risk_evaluated
        """
        content = payload.get("message") or payload.get("summary") or str(payload)
        metadata = {
            "event_type": event_type,
            "agent_type": agent_type,
            **payload,
        }
        return await self.add_message(
            session_id=session_id,
            role="system",
            content=content,
            metadata=metadata,
            generate_embedding=generate_embedding,
        )

    async def get_events(
        self,
        session_id: str,
        event_types: Optional[list[str]] = None,
        agent_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """读取统一事件流投影"""
        query = (
            select(ConversationMessages)
            .where(ConversationMessages.session_id == session_id)
            .where(ConversationMessages.role == "system")
            .order_by(ConversationMessages.created_at)
            .limit(limit)
        )

        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        events = []
        for msg in messages:
            evt_type = msg.metadata.get("event_type") if msg.metadata else None
            if event_types and evt_type not in event_types:
                continue
            if agent_type and msg.metadata.get("agent_type") != agent_type:
                continue
            events.append({
                "message_id": msg.message_id,
                "session_id": msg.session_id,
                "event_type": evt_type,
                "agent_type": msg.metadata.get("agent_type") if msg.metadata else None,
                "content": msg.content,
                "metadata": msg.metadata,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })

        return events

    async def get_trajectory(
        self,
        session_id: str,
        agent_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        获取会话完整轨迹（所有消息 + 事件，按时间排序）
        """
        query = (
            select(ConversationMessages)
            .where(ConversationMessages.session_id == session_id)
            .order_by(ConversationMessages.created_at)
        )

        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        trajectory = []
        for msg in messages:
            if agent_type and msg.metadata and msg.metadata.get("agent_type") != agent_type:
                continue
            trajectory.append({
                "message_id": msg.message_id,
                "role": msg.role,
                "content": msg.content,
                "metadata": msg.metadata,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })

        return trajectory

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        include_embeddings: bool = False,
    ) -> list[ConversationMessages]:
        """获取会话的消息列表"""
        query = (
            select(ConversationMessages)
            .where(ConversationMessages.session_id == session_id)
            .order_by(ConversationMessages.created_at)
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        if not include_embeddings:
            for msg in messages:
                msg.embedding = None

        return messages

    async def search_similar(
        self,
        query: str,
        user_id: Optional[int] = None,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """基于语义相似度搜索历史消息"""
        query_vector, _ = await embed_query_with_fallback(query)

        base_query = select(
            ConversationMessages,
            (1 - ConversationMessages.embedding.cosine_distance(query_vector)).label("similarity"),
        ).where(
            ConversationMessages.embedding.isnot(None)
        )

        base_query = base_query.where(
            (1 - ConversationMessages.embedding.cosine_distance(query_vector)) >= similarity_threshold
        )

        if session_id:
            base_query = base_query.where(
                ConversationMessages.session_id == session_id
            )

        if user_id:
            base_query = base_query.join(
                ConversationSessions,
                ConversationMessages.session_id == ConversationSessions.session_id,
            ).where(ConversationSessions.user_id == user_id)

        base_query = base_query.order_by(desc("similarity")).limit(limit)

        result = await self.db.execute(base_query)

        results = []
        for msg, similarity in result.all():
            results.append({
                "message_id": msg.message_id,
                "session_id": msg.session_id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "similarity": round(float(similarity), 4),
            })

        return results

    async def get_user_sessions(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ConversationSessions]:
        """获取用户的会话列表"""
        query = select(ConversationSessions).where(
            ConversationSessions.user_id == user_id
        )

        if status:
            query = query.where(ConversationSessions.status == status)

        query = query.order_by(desc(ConversationSessions.last_message_at)).limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_session_summary(
        self,
        session_id: str,
        summary: str,
    ) -> None:
        """更新会话摘要"""
        session = await self.get_session(session_id)
        if session:
            session.summary = summary
            await self.db.commit()
            logger.debug(f"Updated summary for session {session_id}")

    async def archive_session(self, session_id: str) -> bool:
        """归档会话（标记为 inactive）"""
        session = await self.get_session(session_id)
        if session:
            session.status = "archived"
            await self.db.commit()
            logger.info(f"Archived session {session_id}")
            return True
        return False

    async def delete_session(self, session_id: str, user_id: Optional[int] = None) -> bool:
        """删除会话及其所有消息"""
        session = await self.get_session(session_id, user_id)
        if not session:
            return False

        await self.db.execute(
            ConversationMessages.__table__.delete().where(
                ConversationMessages.session_id == session_id
            )
        )

        await self.db.delete(session)
        await self.db.commit()

        logger.info(f"Deleted session {session_id}")
        return True

    async def get_session_stats(self, user_id: int) -> dict[str, Any]:
        """获取用户会话统计"""
        session_count = await self.db.scalar(
            select(func.count(ConversationSessions.id)).where(
                ConversationSessions.user_id == user_id
            )
        )

        active_count = await self.db.scalar(
            select(func.count(ConversationSessions.id)).where(
                and_(
                    ConversationSessions.user_id == user_id,
                    ConversationSessions.status == "active",
                )
            )
        )

        message_count = await self.db.scalar(
            select(func.count(ConversationMessages.id))
            .join(ConversationSessions)
            .where(ConversationSessions.user_id == user_id)
        )

        return {
            "total_sessions": session_count or 0,
            "active_sessions": active_count or 0,
            "total_messages": message_count or 0,
        }

    async def cleanup_old_sessions(
        self,
        days: int = 30,
        batch_size: int = 100,
    ) -> int:
        """清理过期的归档会话"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        query = (
            select(ConversationSessions.session_id)
            .where(
                and_(
                    ConversationSessions.status == "archived",
                    ConversationSessions.updated_at < cutoff_date,
                )
            )
            .limit(batch_size)
        )

        result = await self.db.execute(query)
        session_ids = [row[0] for row in result.all()]

        if not session_ids:
            return 0

        await self.db.execute(
            ConversationMessages.__table__.delete().where(
                ConversationMessages.session_id.in_(session_ids)
            )
        )

        await self.db.execute(
            ConversationSessions.__table__.delete().where(
                ConversationSessions.session_id.in_(session_ids)
            )
        )

        await self.db.commit()

        logger.info(f"Cleaned up {len(session_ids)} old sessions")
        return len(session_ids)


class EpisodicMemoryService:
    """
    中期记忆服务（用于依赖注入）
    """

    def __init__(self, db: AsyncSession):
        self._memory = EpisodicMemory(db)

    async def create_session(self, *args, **kwargs):
        return await self._memory.create_session(*args, **kwargs)

    async def add_message(self, *args, **kwargs):
        return await self._memory.add_message(*args, **kwargs)

    async def add_event(self, *args, **kwargs):
        return await self._memory.add_event(*args, **kwargs)

    async def get_events(self, *args, **kwargs):
        return await self._memory.get_events(*args, **kwargs)

    async def get_trajectory(self, *args, **kwargs):
        return await self._memory.get_trajectory(*args, **kwargs)

    async def get_messages(self, *args, **kwargs):
        return await self._memory.get_messages(*args, **kwargs)

    async def search_similar(self, *args, **kwargs):
        return await self._memory.search_similar(*args, **kwargs)

    async def get_user_sessions(self, *args, **kwargs):
        return await self._memory.get_user_sessions(*args, **kwargs)

    async def update_session_summary(self, *args, **kwargs):
        return await self._memory.update_session_summary(*args, **kwargs)

    async def archive_session(self, *args, **kwargs):
        return await self._memory.archive_session(*args, **kwargs)

    async def delete_session(self, *args, **kwargs):
        return await self._memory.delete_session(*args, **kwargs)
