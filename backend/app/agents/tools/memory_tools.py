"""
Memory Tools - 包装 UnifiedMemoryService / EpisodicMemory / LongTermMemory
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class MemoryManageInput(BaseModel):
    action: str = Field(description="操作类型: create_session, list_sessions, get_session, archive_session, delete_session, get_messages, add_message, search, get_preferences, set_preference, get_memories, add_memory, get_stats, get_context")
    session_id: Optional[str] = Field(None, description="会话ID")
    title: Optional[str] = Field(None, description="会话标题")
    role: Optional[str] = Field(None, description="消息角色（add_message时使用）")
    content: Optional[str] = Field(None, description="消息内容或记忆内容")
    query: Optional[str] = Field(None, description="搜索查询")
    key: Optional[str] = Field(None, description="偏好键")
    value: Optional[Any] = Field(None, description="偏好值")
    pref_type: Optional[str] = Field(None, description="偏好类型")
    memory_type: Optional[str] = Field(None, description="记忆类型: fact, preference, goal, event")
    importance: Optional[int] = Field(None, description="记忆重要性（1-10）")
    limit: Optional[int] = Field(20, description="返回数量限制")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def memory_manage(
        action: str,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
        role: Optional[str] = None,
        content: Optional[str] = None,
        query: Optional[str] = None,
        key: Optional[str] = None,
        value: Optional[Any] = None,
        pref_type: Optional[str] = None,
        memory_type: Optional[str] = None,
        importance: Optional[int] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        from app.services.memory.unified_memory import UnifiedMemoryService, get_session_memory
        from app.services.memory.episodic_memory import EpisodicMemory
        from app.services.memory.longterm_memory import LongTermMemory
        from app.core.errors import ServiceError

        try:
            memory = UnifiedMemoryService(db, user_id=user.id)
            episodic = EpisodicMemory(db)
            longterm = LongTermMemory(db)

            if action == "create_session":
                sid = await memory.create_session(user_id=user.id, title=title)
                return {"success": True, "session_id": sid}
            elif action == "list_sessions":
                sessions = await episodic.get_user_sessions(user_id=user.id, limit=limit)
                return {
                    "success": True,
                    "sessions": [
                        {
                            "session_id": s.session_id,
                            "title": s.title,
                            "status": s.status,
                            "message_count": s.message_count,
                        }
                        for s in sessions
                    ],
                }
            elif action == "get_session":
                if not session_id:
                    return {"success": False, "error": "session_id is required"}
                s = await episodic.get_session(session_id, user_id=user.id)
                if not s:
                    return {"success": False, "error": "Session not found"}
                return {"success": True, "session": {"session_id": s.session_id, "title": s.title, "status": s.status}}
            elif action == "archive_session":
                if not session_id:
                    return {"success": False, "error": "session_id is required"}
                await memory.close_session(session_id)
                return {"success": True, "session_id": session_id, "status": "archived"}
            elif action == "delete_session":
                if not session_id:
                    return {"success": False, "error": "session_id is required"}
                ok = await episodic.delete_session(session_id, user_id=user.id)
                session_mem = get_session_memory()
                await session_mem.clear_session(session_id)
                return {"success": ok, "session_id": session_id}
            elif action == "get_messages":
                if not session_id:
                    return {"success": False, "error": "session_id is required"}
                msgs = await episodic.get_messages(session_id, limit=limit)
                return {
                    "success": True,
                    "messages": [
                        {"message_id": m.message_id, "role": m.role, "content": m.content}
                        for m in msgs
                    ],
                }
            elif action == "add_message":
                if not session_id or not role or content is None:
                    return {"success": False, "error": "session_id, role, content are required"}
                result = await memory.remember(session_id=session_id, user_id=user.id, role=role, content=content)
                return {"success": True, "result": result}
            elif action == "search":
                if not query:
                    return {"success": False, "error": "query is required"}
                msg_results = await episodic.search_similar(query=query, user_id=user.id, limit=limit)
                mem_results = await longterm.search_memories(user_id=user.id, query=query, limit=limit)
                return {"success": True, "messages": msg_results, "memories": mem_results}
            elif action == "get_preferences":
                prefs = {}
                for ptype in ["chat", "ui", "notification"]:
                    prefs.update(await longterm.get_preferences_by_type(user_id=user.id, pref_type=ptype))
                return {"success": True, "preferences": prefs}
            elif action == "set_preference":
                if not key or value is None:
                    return {"success": False, "error": "key and value are required"}
                pref = await longterm.set_preference(
                    user_id=user.id,
                    key=key,
                    value=value,
                    pref_type=pref_type or "general",
                )
                return {"success": True, "preference": {"key": key, "value": value, "confidence": pref.confidence}}
            elif action == "get_memories":
                memories = await longterm.get_memories(user_id=user.id, limit=limit)
                return {
                    "success": True,
                    "memories": [
                        {"memory_id": m.memory_id, "content": m.content, "type": m.memory_type}
                        for m in memories
                    ],
                }
            elif action == "add_memory":
                if not content:
                    return {"success": False, "error": "content is required"}
                mem = await longterm.add_memory(
                    user_id=user.id,
                    content=content,
                    memory_type=memory_type or "fact",
                    importance=importance or 5,
                )
                return {"success": True, "memory": {"memory_id": mem.memory_id, "content": mem.content}}
            elif action == "get_stats":
                stats = await memory.get_user_memory_stats(user_id=user.id)
                return {"success": True, "stats": stats}
            elif action == "get_context":
                if not session_id:
                    return {"success": False, "error": "session_id is required"}
                ctx = await memory.recall(session_id=session_id, user_id=user.id, query=query)
                return {"success": True, "context": ctx}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail}
        except Exception as e:
            logger.exception(f"memory_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="memory_manage",
            func=memory_manage,
            description="管理用户记忆系统（会话、消息、偏好、长期记忆）",
            args_schema=MemoryManageInput,
            coroutine=memory_manage,
        ),
    ]
