"""
L5 长期记忆 (Long-term Memory) - PostgreSQL + Neo4j 实现

存储用户的持久性偏好、习惯和知识：
- 用户偏好（交互风格、主题偏好等）
- 提取的知识和事实
- Agent 决策模式学习
- 跨会话的个性化信息
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_client import embed_query_with_fallback
from app.db.models import AgentDecisionLogs, UserMemories, UserPreferences
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    长期记忆管理器

    管理用户的持久化信息：
    - 用户偏好（UserPreferences）
    - 长期记忆（UserMemories）
    - Agent 决策日志（AgentDecisionLogs）
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 用户偏好管理 ====================

    async def set_preference(
        self,
        user_id: int,
        key: str,
        value: Any,
        pref_type: str = "general",
        confidence: float = 0.5,
        source: str = "implicit",
    ) -> UserPreferences:
        """设置用户偏好"""
        result = await self.db.execute(
            select(UserPreferences).where(
                and_(
                    UserPreferences.user_id == user_id,
                    UserPreferences.key == key,
                )
            )
        )
        existing = result.scalar_one_or_none()

        value_str = json.dumps(value) if not isinstance(value, str) else value

        if existing:
            existing.value = value_str
            existing.confidence = (existing.confidence + confidence) / 2
            existing.source = source
            existing.updated_at = datetime.utcnow()
            pref = existing
        else:
            pref = UserPreferences(
                id=snowflake_id(),
                user_id=user_id,
                pref_type=pref_type,
                key=key,
                value=value_str,
                confidence=confidence,
                source=source,
            )
            self.db.add(pref)

        await self.db.commit()
        await self.db.refresh(pref)

        logger.debug(f"Set preference {key}={value} for user {user_id}")
        return pref

    async def get_preference(
        self,
        user_id: int,
        key: str,
        default: Any = None,
    ) -> Any:
        """获取用户偏好"""
        result = await self.db.execute(
            select(UserPreferences).where(
                and_(
                    UserPreferences.user_id == user_id,
                    UserPreferences.key == key,
                )
            )
        )
        pref = result.scalar_one_or_none()

        if pref is None:
            return default

        try:
            return json.loads(pref.value)
        except json.JSONDecodeError:
            return pref.value

    async def get_preferences_by_type(
        self,
        user_id: int,
        pref_type: str,
        min_confidence: float = 0.0,
    ) -> dict[str, Any]:
        """获取指定类型的所有偏好"""
        result = await self.db.execute(
            select(UserPreferences).where(
                and_(
                    UserPreferences.user_id == user_id,
                    UserPreferences.pref_type == pref_type,
                    UserPreferences.confidence >= min_confidence,
                )
            )
        )

        prefs = {}
        for pref in result.scalars().all():
            try:
                prefs[pref.key] = json.loads(pref.value)
            except json.JSONDecodeError:
                prefs[pref.key] = pref.value

        return prefs

    async def delete_preference(self, user_id: int, key: str) -> bool:
        """删除用户偏好"""
        result = await self.db.execute(
            select(UserPreferences).where(
                and_(
                    UserPreferences.user_id == user_id,
                    UserPreferences.key == key,
                )
            )
        )
        pref = result.scalar_one_or_none()

        if pref:
            await self.db.delete(pref)
            await self.db.commit()
            return True
        return False

    # ==================== 长期记忆管理 ====================

    async def add_memory(
        self,
        user_id: int,
        content: str,
        memory_type: str = "fact",
        importance: int = 5,
        source: Optional[str] = None,
        context: Optional[dict] = None,
        expires_at: Optional[datetime] = None,
        generate_embedding: bool = True,
    ) -> UserMemories:
        """添加长期记忆"""
        memory_id = f"mem_{snowflake_id()}"

        memory = UserMemories(
            id=snowflake_id(),
            memory_id=memory_id,
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            source=source,
            context=context or {},
            expires_at=expires_at,
        )

        if generate_embedding:
            try:
                vector, model = await embed_query_with_fallback(content)
                memory.embedding = vector
                memory.context["embedding_model"] = model
            except Exception as exc:
                logger.warning(f"Failed to generate memory embedding: {exc}")

        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)

        logger.info(f"Added memory {memory_id} for user {user_id}: {content[:50]}...")
        return memory

    async def get_memories(
        self,
        user_id: int,
        memory_type: Optional[str] = None,
        min_importance: int = 1,
        limit: int = 100,
        include_expired: bool = False,
    ) -> list[UserMemories]:
        """获取用户的长期记忆"""
        query = select(UserMemories).where(
            and_(
                UserMemories.user_id == user_id,
                UserMemories.importance >= min_importance,
            )
        )

        if memory_type:
            query = query.where(UserMemories.memory_type == memory_type)

        if not include_expired:
            query = query.where(
                and_(
                    UserMemories.expires_at.is_(None),
                    UserMemories.expires_at > datetime.utcnow(),
                )
            )

        query = query.order_by(desc(UserMemories.importance)).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def search_memories(
        self,
        user_id: int,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """基于语义相似度搜索记忆"""
        query_vector, _ = await embed_query_with_fallback(query)

        base_query = select(
            UserMemories,
            (1 - UserMemories.embedding.cosine_distance(query_vector)).label("similarity"),
        ).where(
            and_(
                UserMemories.user_id == user_id,
                UserMemories.embedding.isnot(None),
            )
        )

        base_query = base_query.where(
            (1 - UserMemories.embedding.cosine_distance(query_vector)) >= similarity_threshold
        )

        if memory_type:
            base_query = base_query.where(UserMemories.memory_type == memory_type)

        base_query = base_query.order_by(desc("similarity")).limit(limit)

        result = await self.db.execute(base_query)

        memories = []
        for mem, similarity in result.all():
            memories.append({
                "memory_id": mem.memory_id,
                "content": mem.content,
                "memory_type": mem.memory_type,
                "importance": mem.importance,
                "similarity": round(float(similarity), 4),
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
            })

        return memories

    async def update_memory_importance(
        self,
        memory_id: str,
        importance_delta: int,
    ) -> bool:
        """更新记忆重要性"""
        result = await self.db.execute(
            select(UserMemories).where(UserMemories.memory_id == memory_id)
        )
        memory = result.scalar_one_or_none()

        if memory:
            memory.importance = max(1, min(10, memory.importance + importance_delta))
            await self.db.commit()
            return True
        return False

    async def delete_memory(self, memory_id: str, user_id: Optional[int] = None) -> bool:
        """删除记忆"""
        q = select(UserMemories).where(UserMemories.memory_id == memory_id)

        if user_id:
            q = q.where(UserMemories.user_id == user_id)

        result = await self.db.execute(q)
        memory = result.scalar_one_or_none()

        if memory:
            await self.db.delete(memory)
            await self.db.commit()
            return True
        return False

    # ==================== 语义提取增强 ====================

    async def extract_and_store_facts(
        self,
        user_id: int,
        session_summary: str,
    ) -> list[dict[str, Any]]:
        """
        从会话摘要中提取稳定事实并写入 UserMemories

        TODO: 接入 LLM 进行结构化事实提取
        """
        facts = []
        # 简单的启发式提取作为 fallback
        indicators = [
            ("喜欢", "preference", 7),
            ("偏好", "preference", 7),
            ("需要", "goal", 6),
            ("目标", "goal", 6),
            ("关注", "interest", 6),
            ("讨厌", "preference", 7),
        ]

        for keyword, mtype, importance in indicators:
            if keyword in session_summary:
                # 提取 keyword 所在的简单句子片段
                idx = session_summary.find(keyword)
                start = max(0, idx - 20)
                end = min(len(session_summary), idx + 40)
                snippet = session_summary[start:end].strip(" ，。！？")
                if snippet:
                    memory = await self.add_memory(
                        user_id=user_id,
                        content=snippet,
                        memory_type=mtype,
                        importance=importance,
                        source="session_summary_extraction",
                    )
                    facts.append({
                        "memory_id": memory.memory_id,
                        "type": mtype,
                        "content": memory.content,
                    })

        return facts

    async def get_user_profile(self, user_id: int) -> dict[str, Any]:
        """
        聚合用户画像：UserPreferences + UserMemories
        """
        preferences = await self.get_preferences_by_type(
            user_id=user_id,
            pref_type="chat",
            min_confidence=0.5,
        )
        memories = await self.get_memories(
            user_id=user_id,
            min_importance=5,
            limit=20,
        )

        return {
            "user_id": user_id,
            "preferences": preferences,
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "content": m.content,
                    "memory_type": m.memory_type,
                    "importance": m.importance,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in memories
            ],
        }

    # ==================== Agent 决策日志 ====================

    async def log_decision(
        self,
        task_id: str,
        agent_type: str,
        decision: str,
        context: dict[str, Any],
        reasoning: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> AgentDecisionLogs:
        """记录 Agent 决策"""
        log = AgentDecisionLogs(
            id=snowflake_id(),
            log_id=f"log_{snowflake_id()}",
            task_id=task_id,
            agent_type=agent_type,
            decision=decision,
            context=context,
            reasoning=reasoning,
            outcome=outcome,
        )

        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        logger.debug(f"Logged decision for {agent_type}: {decision}")
        return log

    async def get_decision_history(
        self,
        agent_type: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[AgentDecisionLogs]:
        """获取决策历史"""
        query = select(AgentDecisionLogs)

        if agent_type:
            query = query.where(AgentDecisionLogs.agent_type == agent_type)

        if task_id:
            query = query.where(AgentDecisionLogs.task_id == task_id)

        query = query.order_by(desc(AgentDecisionLogs.created_at)).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ==================== 记忆维护 ====================

    async def consolidate_memories(self, user_id: int) -> dict[str, int]:
        """整合记忆"""
        stats = {"merged": 0, "deleted": 0, "updated": 0}

        expired = await self.db.execute(
            select(UserMemories).where(
                and_(
                    UserMemories.user_id == user_id,
                    UserMemories.expires_at < datetime.utcnow(),
                )
            )
        )

        for memory in expired.scalars().all():
            await self.db.delete(memory)
            stats["deleted"] += 1

        await self.db.commit()

        logger.info(f"Memory consolidation for user {user_id}: {stats}")
        return stats

    async def get_memory_summary(self, user_id: int) -> dict[str, Any]:
        """获取记忆摘要"""
        total_memories = await self.db.scalar(
            select(func.count(UserMemories.id)).where(UserMemories.user_id == user_id)
        )

        type_counts = await self.db.execute(
            select(
                UserMemories.memory_type,
                func.count(UserMemories.id),
            )
            .where(UserMemories.user_id == user_id)
            .group_by(UserMemories.memory_type)
        )

        avg_importance = await self.db.scalar(
            select(func.avg(UserMemories.importance)).where(
                UserMemories.user_id == user_id
            )
        )

        return {
            "total_memories": total_memories or 0,
            "by_type": {row[0]: row[1] for row in type_counts.all()},
            "average_importance": round(float(avg_importance or 0), 2),
        }
