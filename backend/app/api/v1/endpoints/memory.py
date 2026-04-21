"""
记忆管理 API 端点

提供对话历史、用户偏好和长期记忆的 REST API 接口。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.db.models import Users
from app.db.session import get_db
from app.services.memory import (
    EpisodicMemory,
    LongTermMemory,
    UnifiedMemoryService,
    get_session_memory,
)

router = APIRouter(prefix="/memory", tags=["memory"])


# ==================== 会话管理 ====================

@router.post("/sessions")
async def create_session(
    title: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """创建新会话"""
    memory = UnifiedMemoryService(db)
    session_id = await memory.create_session(
        user_id=current_user.id,
        title=title,
    )
    return {
        "session_id": session_id,
        "user_id": current_user.id,
        "title": title or "新会话",
    }


@router.get("/sessions")
async def list_sessions(
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户会话列表"""
    episodic = EpisodicMemory(db)
    sessions = await episodic.get_user_sessions(
        user_id=current_user.id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "title": s.title,
                "status": s.status,
                "message_count": s.message_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
                "summary": s.summary,
            }
            for s in sessions
        ],
        "total": len(sessions),
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取会话详情"""
    episodic = EpisodicMemory(db)
    session = await episodic.get_session(session_id, user_id=current_user.id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "title": session.title,
        "status": session.status,
        "message_count": session.message_count,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_message_at": session.last_message_at.isoformat() if session.last_message_at else None,
        "summary": session.summary,
        "metadata": session.metadata,
    }


@router.post("/sessions/{session_id}/archive")
async def archive_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """归档会话"""
    memory = UnifiedMemoryService(db)

    # 验证会话归属
    session = await memory.episodic.get_session(session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await memory.close_session(session_id)

    return {"success": True, "session_id": session_id, "status": "archived"}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """删除会话"""
    episodic = EpisodicMemory(db)

    success = await episodic.delete_session(session_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    # 同时清理短期记忆
    session_memory = get_session_memory()
    await session_memory.clear_session(session_id)

    return {"success": True, "session_id": session_id}


# ==================== 消息管理 ====================

@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取会话消息列表"""
    episodic = EpisodicMemory(db)

    # 验证会话归属
    session = await episodic.get_session(session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await episodic.get_messages(session_id, limit=limit, offset=offset)

    return {
        "session_id": session_id,
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "metadata": m.metadata,
            }
            for m in messages
        ],
        "total": len(messages),
    }


@router.post("/sessions/{session_id}/messages")
async def add_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """添加消息到会话"""
    memory = UnifiedMemoryService(db, user_id=current_user.id)

    # 验证会话归属
    session = await memory.episodic.get_session(session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await memory.remember(
        session_id=session_id,
        user_id=current_user.id,
        role=role,
        content=content,
        metadata=metadata,
    )

    return {
        "success": True,
        "session_id": session_id,
        "short_term": result["short_term"],
        "episodic": result["episodic"],
    }


@router.post("/search")
async def search_memories(
    query: str,
    search_type: str = Query("all", enum=["messages", "memories", "all"]),
    limit: int = Query(10, ge=1, le=50),
    similarity_threshold: float = Query(0.7, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """语义搜索记忆"""
    results = {"messages": [], "memories": []}

    if search_type in ["messages", "all"]:
        episodic = EpisodicMemory(db)
        results["messages"] = await episodic.search_similar(
            query=query,
            user_id=current_user.id,
            limit=limit,
            similarity_threshold=similarity_threshold,
        )

    if search_type in ["memories", "all"]:
        longterm = LongTermMemory(db)
        results["memories"] = await longterm.search_memories(
            user_id=current_user.id,
            query=query,
            limit=limit,
            similarity_threshold=similarity_threshold,
        )

    return results


# ==================== 用户偏好管理 ====================

@router.get("/preferences")
async def get_preferences(
    pref_type: Optional[str] = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户偏好"""
    longterm = LongTermMemory(db)

    if pref_type:
        preferences = await longterm.get_preferences_by_type(
            user_id=current_user.id,
            pref_type=pref_type,
            min_confidence=min_confidence,
        )
    else:
        # 获取所有类型
        preferences = {}
        for ptype in ["chat", "ui", "notification"]:
            prefs = await longterm.get_preferences_by_type(
                user_id=current_user.id,
                pref_type=ptype,
                min_confidence=min_confidence,
            )
            preferences.update(prefs)

    return {"preferences": preferences, "user_id": current_user.id}


@router.post("/preferences")
async def set_preference(
    key: str,
    value: Any,
    pref_type: str = "general",
    confidence: float = Query(0.8, ge=0.0, le=1.0),
    source: str = Query("explicit", enum=["explicit", "implicit", "learned"]),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """设置用户偏好"""
    longterm = LongTermMemory(db)

    pref = await longterm.set_preference(
        user_id=current_user.id,
        key=key,
        value=value,
        pref_type=pref_type,
        confidence=confidence,
        source=source,
    )

    return {
        "success": True,
        "key": key,
        "value": value,
        "pref_type": pref_type,
        "confidence": pref.confidence,
    }


@router.delete("/preferences/{key}")
async def delete_preference(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """删除用户偏好"""
    longterm = LongTermMemory(db)

    success = await longterm.delete_preference(current_user.id, key)
    if not success:
        raise HTTPException(status_code=404, detail="Preference not found")

    return {"success": True, "key": key}


# ==================== 长期记忆管理 ====================

@router.get("/memories")
async def get_memories(
    memory_type: Optional[str] = None,
    min_importance: int = Query(1, ge=1, le=10),
    limit: int = Query(100, ge=1, le=500),
    include_expired: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户长期记忆"""
    longterm = LongTermMemory(db)

    memories = await longterm.get_memories(
        user_id=current_user.id,
        memory_type=memory_type,
        min_importance=min_importance,
        limit=limit,
        include_expired=include_expired,
    )

    return {
        "memories": [
            {
                "memory_id": m.memory_id,
                "content": m.content,
                "memory_type": m.memory_type,
                "importance": m.importance,
                "source": m.source,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "expires_at": m.expires_at.isoformat() if m.expires_at else None,
            }
            for m in memories
        ],
        "total": len(memories),
    }


@router.post("/memories")
async def add_memory(
    content: str,
    memory_type: str = Query("fact", enum=["fact", "preference", "goal", "event"]),
    importance: int = Query(5, ge=1, le=10),
    source: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """添加长期记忆"""
    longterm = LongTermMemory(db)

    memory = await longterm.add_memory(
        user_id=current_user.id,
        content=content,
        memory_type=memory_type,
        importance=importance,
        source=source or "explicit",
    )

    return {
        "success": True,
        "memory_id": memory.memory_id,
        "content": memory.content,
        "memory_type": memory.memory_type,
        "importance": memory.importance,
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """删除长期记忆"""
    longterm = LongTermMemory(db)

    success = await longterm.delete_memory(memory_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"success": True, "memory_id": memory_id}


# ==================== 统计信息 ====================

@router.get("/stats")
async def get_memory_stats(
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户记忆统计"""
    memory = UnifiedMemoryService(db)
    stats = await memory.get_user_memory_stats(current_user.id)

    return {
        "user_id": current_user.id,
        **stats,
    }


@router.get("/context/{session_id}")
async def get_context(
    session_id: str,
    query: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict[str, Any]:
    """获取完整记忆上下文（用于 LLM）"""
    memory = UnifiedMemoryService(db)

    # 验证会话归属
    session = await memory.episodic.get_session(session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = await memory.recall(
        session_id=session_id,
        user_id=current_user.id,
        query=query,
    )

    return context
