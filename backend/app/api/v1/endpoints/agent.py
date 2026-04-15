"""
Agent 端点 - Agent-First 架构统一入口

仅保留：
1. 统一聊天与流式聊天
2. 统一任务状态查询
"""

import json
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps.auth import get_current_user, get_db
from app.schemas.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentTaskCreate,
    AgentTaskResponse,
)
from app.services.base import get_llm_client
from app.agents.core import MainAgent, AgentType
from app.core.config import settings
from app.db.models import AgentTasks, Spaces

router = APIRouter()


def create_main_agent(db: AsyncSession) -> MainAgent:
    space_path = getattr(settings, "UPLOAD_DIR", "/tmp/uploads")
    return MainAgent(
        db=db,
        llm_client=get_llm_client(),
        space_path=space_path,
    )


async def resolve_space_id(db: AsyncSession, space_id: Optional[str]) -> int:
    if not space_id:
        raise HTTPException(status_code=400, detail="space_id is required")
    if space_id.isdigit():
        return int(space_id)
    stmt = select(Spaces.id).where(Spaces.public_id == space_id)
    result = await db.execute(stmt)
    db_id = result.scalar_one_or_none()
    if db_id is None:
        raise HTTPException(status_code=404, detail="Space not found")
    return db_id


async def _create_agent_task_record(
    db: AsyncSession,
    agent_type: str,
    input_data: dict,
    space_id: int,
    user_id: int,
    public_id: str = None,
) -> AgentTasks:
    task = AgentTasks(
        public_id=public_id or str(uuid.uuid4())[:32],
        agent_type=agent_type,
        status="pending",
        input_data=input_data,
        created_by=user_id,
        space_id=space_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def _update_agent_task(
    db: AsyncSession,
    task_public_id: str,
    status: str = None,
    output_data: dict = None,
    subagent_result: dict = None,
    error: str = None,
    started_at: datetime = None,
    finished_at: datetime = None,
) -> AgentTasks:
    stmt = select(AgentTasks).where(AgentTasks.public_id == task_public_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task:
        if status is not None:
            task.status = status
        if output_data is not None:
            task.output_data = output_data
        if subagent_result is not None:
            task.subagent_result = subagent_result
        if error is not None:
            task.error = error
        if started_at is not None:
            task.started_at = started_at
        if finished_at is not None:
            task.finished_at = finished_at
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)

    return task


async def _get_agent_task(db: AsyncSession, task_public_id: str) -> AgentTasks:
    stmt = select(AgentTasks).where(AgentTasks.public_id == task_public_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    req: AgentChatRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = create_main_agent(db)
    space_id_int = await resolve_space_id(db, req.space_id)

    task = await _create_agent_task_record(
        db=db,
        agent_type="chat",
        input_data={"message": req.message, "context": req.context},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    await _update_agent_task(
        db, task.public_id, status="running", started_at=datetime.utcnow()
    )

    try:
        result = await agent.chat(
            message=req.message,
            space_id=req.space_id,
            user_id=current_user.id,
            context=req.context,
            top_k=req.top_k,
            conversation_history=req.history or [],
        )

        await _update_agent_task(
            db,
            task.public_id,
            status="completed",
            output_data=result,
            subagent_result=result,
            finished_at=datetime.utcnow(),
        )

        return AgentChatResponse(
            success=result.get("success", True),
            intent=result.get("intent"),
            agent_type=result.get("agent_type", "unknown"),
            result=result.get("result", {}),
            answer=result.get("answer"),
            sources=result.get("sources"),
            error=result.get("error"),
        )
    except Exception as e:
        await _update_agent_task(
            db,
            task.public_id,
            status="failed",
            error=str(e),
            finished_at=datetime.utcnow(),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def agent_chat_stream(
    req: AgentChatRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.db.session import AsyncSessionLocal

    space_id_int = await resolve_space_id(db, req.space_id)

    task = await _create_agent_task_record(
        db=db,
        agent_type="chat",
        input_data={"message": req.message, "context": req.context},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    await _update_agent_task(
        db, task.public_id, status="running", started_at=datetime.utcnow()
    )

    await db.commit()
    # 注意：不在此处主动关闭 db，由 FastAPI 请求生命周期自动管理

    task_public_id = task.public_id
    final_result = {}

    async def event_stream():
        nonlocal final_result

        async with AsyncSessionLocal() as stream_db:
            try:
                agent = create_main_agent(stream_db)

                async for chunk in agent.stream_chat(
                    message=req.message,
                    space_id=req.space_id,
                    user_id=current_user.id,
                    context=req.context,
                    top_k=req.top_k,
                    conversation_history=req.history or [],
                ):
                    if chunk.get("type") == "intent" and "intent" not in final_result:
                        final_result["intent"] = chunk["data"]
                    if chunk.get("type") == "result":
                        final_result = chunk["data"]
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"

                async with AsyncSessionLocal() as final_db:
                    await _update_agent_task(
                        final_db,
                        task_public_id,
                        status="completed",
                        output_data=final_result,
                        subagent_result=final_result,
                        finished_at=datetime.utcnow(),
                    )

            except Exception as e:
                error_result = {"error": str(e)}
                yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

                async with AsyncSessionLocal() as error_db:
                    await _update_agent_task(
                        error_db,
                        task_public_id,
                        status="failed",
                        error=str(e),
                        finished_at=datetime.utcnow(),
                    )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks", response_model=AgentTaskResponse)
async def create_agent_task(
    req: AgentTaskCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    space_id = await resolve_space_id(db, req.space_id)

    task = await _create_agent_task_record(
        db=db,
        agent_type=req.agent_type,
        input_data=req.input_data,
        space_id=space_id,
        user_id=current_user.id,
    )

    return AgentTaskResponse(
        task_id=task.public_id,
        agent_type=task.agent_type,
        status=task.status,
        created_at=task.created_at,
    )


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_agent_task(db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    progress = 0
    if task.status == "running":
        progress = 50
    elif task.status == "completed":
        progress = 100
    elif task.status == "failed":
        progress = 0

    return {
        "task_id": task.public_id,
        "agent_type": task.agent_type,
        "status": task.status,
        "progress": progress,
        "error": task.error,
        "retry_count": task.retry_count,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "result": task.output_data,
    }
