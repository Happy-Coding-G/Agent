"""
记忆管理服务模块

提供分层记忆管理：
- L1: SessionMemory (Redis) - 短期记忆
- L2: EpisodicMemory (PostgreSQL) - 中期记忆
- L3: LongTermMemory (PostgreSQL + Neo4j) - 长期记忆
- UnifiedMemoryService - 统一记忆接口

快速开始:
    from app.services.memory import UnifiedMemoryService, get_session_memory

    # 统一记忆服务
    memory = UnifiedMemoryService(db_session)
    await memory.remember(session_id, user_id, "user", "你好")
    context = await memory.recall(session_id, user_id)

    # 单独使用短期记忆
    session_memory = get_session_memory()
    await session_memory.add_message(session_id, "user", "你好")
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
    # L1 短期记忆
    "SessionMemory",
    "get_session_memory",
    # L2 中期记忆
    "EpisodicMemory",
    "EpisodicMemoryService",
    # L3 长期记忆
    "LongTermMemory",
    # 统一接口
    "UnifiedMemoryService",
    "MemoryAugmentedContext",
    # 检查点服务
    "WorkflowCheckpointService",
    "ResumableWorkflow",
]
