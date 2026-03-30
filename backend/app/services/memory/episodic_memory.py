"""
L2 中期记忆 (Episodic Memory) - PostgreSQL 实现

基于 PostgreSQL 的持久化对话历史存储，支持向量检索。
适用于：
- 跨会话的历史消息检索
- 基于语义相似度的记忆召回
- 对话摘要和长期存储
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
    - 会话摘要生成

    使用方式:
        episodic = EpisodicMemory(db_session)
        session = await episodic.create_session(user_id, title="帮助会话")
        await episodic.add_message(session.session_id, "user", "你好")
        similar = await episodic.search_similar("你好", user_id=user_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        user_id: int,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConversationSessions:
        """
        创建新会话

        Args:
            user_id: 用户 ID
            title: 会话标题
            metadata: 可选元数据

        Returns:
            创建的会话对象
        """
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
        """
        获取会话信息

        Args:
            session_id: 会话 ID
            user_id: 可选的用户 ID 过滤

        Returns:
            会话对象或 None
        """
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
        """
        添加消息到会话

        Args:
            session_id: 会话 ID
            role: 角色 (user/assistant/system)
            content: 消息内容
            metadata: 可选元数据
            generate_embedding: 是否生成向量嵌入

        Returns:
            创建的消息对象
        """
        message_id = snowflake_id()
        message = ConversationMessages(
            id=message_id,
            message_id=f"msg_{message_id}",
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )

        # 生成向量嵌入
        if generate_embedding and content:
            try:
                vector, model = await embed_query_with_fallback(content)
                message.embedding = vector
                message.metadata["embedding_model"] = model
            except Exception as exc:
                logger.warning(f"Failed to generate embedding: {exc}")

        self.db.add(message)

        # 更新会话消息计数
        session = await self.get_session(session_id)
        if session:
            session.message_count = (session.message_count or 0) + 1
            session.last_message_at = datetime.utcnow()

        await self.db.commit()
        await self.db.refresh(message)

        logger.debug(f"Added message {message.message_id} to session {session_id}")
        return message

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        include_embeddings: bool = False,
    ) -> list[ConversationMessages]:
        """
        获取会话的消息列表

        Args:
            session_id: 会话 ID
            limit: 返回数量限制
            offset: 分页偏移
            include_embeddings: 是否包含向量数据

        Returns:
            消息对象列表
        """
        query = (
            select(ConversationMessages)
            .where(ConversationMessages.session_id == session_id)
            .order_by(ConversationMessages.created_at)
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        # 默认不返回嵌入向量（节省内存）
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
        """
        基于语义相似度搜索历史消息

        Args:
            query: 查询文本
            user_id: 可选的用户过滤
            limit: 返回数量
            similarity_threshold: 相似度阈值
            session_id: 可选的会话过滤

        Returns:
            相似消息列表（包含相似度分数）
        """
        # 生成查询向量
        query_vector, _ = await embed_query_with_fallback(query)

        # 构建基础查询
        base_query = select(
            ConversationMessages,
            (1 - ConversationMessages.embedding.cosine_distance(query_vector)).label("similarity"),
        ).where(
            ConversationMessages.embedding.isnot(None)
        )

        # 添加相似度过滤
        base_query = base_query.where(
            (1 - ConversationMessages.embedding.cosine_distance(query_vector)) >= similarity_threshold
        )

        # 添加会话过滤
        if session_id:
            base_query = base_query.where(
                ConversationMessages.session_id == session_id
            )

        # 添加用户过滤（通过 session 关联）
        if user_id:
            base_query = base_query.join(
                ConversationSessions,
                ConversationMessages.session_id == ConversationSessions.session_id,
            ).where(ConversationSessions.user_id == user_id)

        # 排序和限制
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
        """
        获取用户的会话列表

        Args:
            user_id: 用户 ID
            status: 可选的状态过滤
            limit: 返回数量
            offset: 分页偏移

        Returns:
            会话列表
        """
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
        """
        更新会话摘要

        Args:
            session_id: 会话 ID
            summary: 摘要内容
        """
        session = await self.get_session(session_id)
        if session:
            session.summary = summary
            await self.db.commit()
            logger.debug(f"Updated summary for session {session_id}")

    async def archive_session(self, session_id: str) -> bool:
        """
        归档会话（标记为 inactive）

        Args:
            session_id: 会话 ID

        Returns:
            是否成功
        """
        session = await self.get_session(session_id)
        if session:
            session.status = "archived"
            await self.db.commit()
            logger.info(f"Archived session {session_id}")
            return True
        return False

    async def delete_session(self, session_id: str, user_id: Optional[int] = None) -> bool:
        """
        删除会话及其所有消息

        Args:
            session_id: 会话 ID
            user_id: 可选的用户 ID 验证

        Returns:
            是否成功
        """
        session = await self.get_session(session_id, user_id)
        if not session:
            return False

        # 删除关联的消息
        await self.db.execute(
            ConversationMessages.__table__.delete().where(
                ConversationMessages.session_id == session_id
            )
        )

        # 删除会话
        await self.db.delete(session)
        await self.db.commit()

        logger.info(f"Deleted session {session_id}")
        return True

    async def get_session_stats(self, user_id: int) -> dict[str, Any]:
        """
        获取用户会话统计

        Args:
            user_id: 用户 ID

        Returns:
            统计信息
        """
        # 总会话数
        session_count = await self.db.scalar(
            select(func.count(ConversationSessions.id)).where(
                ConversationSessions.user_id == user_id
            )
        )

        # 活跃会话数
        active_count = await self.db.scalar(
            select(func.count(ConversationSessions.id)).where(
                and_(
                    ConversationSessions.user_id == user_id,
                    ConversationSessions.status == "active",
                )
            )
        )

        # 总消息数
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
        """
        清理过期的归档会话

        Args:
            days: 删除 N 天前的归档会话
            batch_size: 每批处理数量

        Returns:
            删除的会话数
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # 查找需要删除的会话
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

        # 删除关联消息
        await self.db.execute(
            ConversationMessages.__table__.delete().where(
                ConversationMessages.session_id.in_(session_ids)
            )
        )

        # 删除会话
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

    提供与 EpisodicMemory 相同的功能，但支持依赖注入模式。
    """

    def __init__(self, db: AsyncSession):
        self._memory = EpisodicMemory(db)

    async def create_session(self, *args, **kwargs):
        return await self._memory.create_session(*args, **kwargs)

    async def add_message(self, *args, **kwargs):
        return await self._memory.add_message(*args, **kwargs)

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
