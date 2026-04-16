"""
记忆管理服务模块

提供分层记忆管理：
- L3: SessionMemory (Redis) - 会话工作记忆
- L4: EpisodicMemory (PostgreSQL) - 情节与流程记忆
- L5: LongTermMemory (PostgreSQL + Neo4j) - 语义与长期记忆
- UnifiedMemoryService - 统一记忆接口

快速开始:
    from app.services.memory import UnifiedMemoryService, get_session_memory

    memory = UnifiedMemoryService(db_session, user_id=1, space_id="space_xxx")
    session_id = await memory.create_session(user_id=1)
    await memory.remember_chat_turn(session_id, "user", "你好")
    context = await memory.recall_chat_context(session_id)
"""

from app.services.memory.checkpoint_service import (
    ResumableWorkflow,
    WorkflowCheckpointService,
)
from app.services.memory.episodic_memory import EpisodicMemory, EpisodicMemoryService
from app.services.memory.longterm_memory import LongTermMemory
from app.services.memory.session_memory import SessionMemory, get_session_memory
from app.services.memory.unified_memory import MemoryAugmentedContext, UnifiedMemoryService

__all__ = [
    # L3 会话工作记忆
    "SessionMemory",
    "get_session_memory",
    # L4 情节记忆
    "EpisodicMemory",
    "EpisodicMemoryService",
    # L5 长期记忆
    "LongTermMemory",
    # 统一接口
    "UnifiedMemoryService",
    "MemoryAugmentedContext",
    # 检查点服务
    "WorkflowCheckpointService",
    "ResumableWorkflow",
]
