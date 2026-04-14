"""
本文件负责暴露与主 Agent 及其子 Agent 相关的 API，覆盖：
1. 统一聊天与流式聊天。
2. Agent 任务创建、状态查询与结果持久化。
3. 文件查询、资产整理与文档审核等子 Agent 能力。
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
    FileQueryRequest,
    FileQueryResult,
    AssetOrganizeRequest,
    AssetClusterResponse,
    ReviewRequest,
    ReviewResponse,
)
from app.services.base import get_llm_client
from app.agents.core import MainAgent, AgentType
from app.core.config import settings
from app.db.models import AgentTasks, AssetClusters, AssetClusterMembership, ReviewLogs

from app.db.models import Spaces

router = APIRouter(prefix="/agent", tags=["agent"])


# 功能：创建请求级 MainAgent，统一复用当前数据库会话与 LLM 客户端。
def create_main_agent(db: AsyncSession) -> MainAgent:

    space_path = getattr(settings, "UPLOAD_DIR", "/tmp/uploads")
    return MainAgent(
        db=db,
        llm_client=get_llm_client(),
        space_path=space_path,
    )



# 功能：将 space_id 从 public_id 或字符串数字解析成数据库内部主键。
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



# 功能：写入一条 Agent 任务初始记录，便于后续跟踪执行状态。
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



# 功能：更新 Agent 任务状态、结果、错误信息和执行时间。
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



# 功能：根据任务公开 ID 读取任务记录。
async def _get_agent_task(db: AsyncSession, task_public_id: str) -> AgentTasks:
    stmt = select(AgentTasks).where(AgentTasks.public_id == task_public_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()



# 功能：处理一次非流式 Agent 对话请求，并持久化任务结果。
@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    req: AgentChatRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = create_main_agent(db)

    # Resolve space_id from public_id or integer
    space_id_int = await resolve_space_id(db, req.space_id)

    # Create task record
    task = await _create_agent_task_record(
        db=db,
        agent_type="chat",  # Will be updated after intent detection
        input_data={"message": req.message, "context": req.context},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    # Update to running
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
        )

        # Update with result
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



# 功能：以 SSE 方式流式返回 Agent 对话结果，并在流结束后更新任务状态。
@router.post("/chat/stream")
async def agent_chat_stream(
    req: AgentChatRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.db.session import AsyncSessionLocal

    # 1. 解析 space_id
    space_id_int = await resolve_space_id(db, req.space_id)

    # 2. 创建任务记录
    task = await _create_agent_task_record(
        db=db,
        agent_type="chat",
        input_data={"message": req.message, "context": req.context},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    # 3. 更新为运行状态
    await _update_agent_task(
        db, task.public_id, status="running", started_at=datetime.utcnow()
    )

    # 4. 关键：提交并关闭请求级会话，释放连接池资源
    await db.commit()
    await db.close()

    task_public_id = task.public_id
    final_result = {}

    # 功能：按事件流逐步产出聊天结果，并使用独立会话更新任务记录。
    async def event_stream():
        nonlocal final_result

        # 流内部创建新的短生命周期会话
        async with AsyncSessionLocal() as stream_db:
            try:
                agent = create_main_agent(stream_db)

                async for chunk in agent.stream_chat(
                    message=req.message,
                    space_id=req.space_id,
                    user_id=current_user.id,
                    context=req.context,
                    top_k=req.top_k,
                ):
                    # Update task with intent if detected
                    if chunk.get("type") == "intent" and "intent" not in final_result:
                        final_result["intent"] = chunk["data"]
                    if chunk.get("type") == "result":
                        final_result = chunk["data"]
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"

                # 最终更新 - 使用新的独立会话
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

                # 错误更新 - 使用新的独立会话
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


# 功能：创建一个可异步执行和追踪的 Agent 任务记录。
@router.post("/task", response_model=AgentTaskResponse)
async def create_agent_task(
    req: AgentTaskCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve space_id from public_id or integer
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



# 功能：查询指定 Agent 任务的当前状态与基础进度信息。
@router.get("/task/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_agent_task(db, task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Calculate progress based on status
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
    }



# 功能：调用文件查询能力，用自然语言检索空间内文件内容。
@router.post("/file/query", response_model=FileQueryResult)
async def file_query(
    req: FileQueryRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent = create_main_agent(db)

    try:
        result = await agent.chat(
            message=f"文件查询: {req.query}",
            space_id=req.space_id,
            user_id=current_user.id,
        )
        # Extract file results from subagent result
        sub_result = result.get("subagent_result", result)
        files = sub_result.get("files", []) if isinstance(sub_result, dict) else []
        return FileQueryResult(
            files=files,
            error=sub_result.get("error") if isinstance(sub_result, dict) else None,
        )
    except Exception as e:
        return FileQueryResult(files=[], error=str(e))



# 功能：触发资产整理子 Agent，并将聚类结果保存到数据库。
@router.post("/asset/organize")
async def organize_assets(
    req: AssetOrganizeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve space_id from public_id or integer
    space_id_int = await resolve_space_id(db, req.space_id)

    # Create task record
    task = await _create_agent_task_record(
        db=db,
        agent_type="asset_organize",
        input_data={"asset_ids": req.asset_ids, "generate_report": req.generate_report},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    await _update_agent_task(
        db, task.public_id, status="running", started_at=datetime.utcnow()
    )

    agent = create_main_agent(db)
    try:
        result = await agent.subagents.invoke_subagent(
            AgentType.ASSET_ORGANIZE,
            {
                "user_request": "整理资产",
                "space_id": req.space_id,
                "user_id": current_user.id,
                "asset_ids": req.asset_ids,
            },
        )

        # Save clusters to database
        saved_clusters = []
        clusters_data = result.get("clusters", [])
        if clusters_data and isinstance(clusters_data, list):
            for cluster_data in clusters_data:
                cluster = AssetClusters(
                    public_id=str(uuid.uuid4())[:32],
                    space_id=space_id_int,
                    name=cluster_data.get("name", f"Cluster {len(saved_clusters) + 1}"),
                    description=cluster_data.get("description"),
                    summary_report=result.get("summary_report")
                    if req.generate_report
                    else None,
                    graph_cluster_id=cluster_data.get("cluster_id"),
                    cluster_method="community_detection",
                    asset_count=len(cluster_data.get("assets", [])),
                    publication_ready=False,
                    created_by=current_user.id,
                )
                db.add(cluster)
                await db.flush()

                # Add memberships
                for asset_id in cluster_data.get("assets", []):
                    membership = AssetClusterMembership(
                        cluster_id=cluster.id,
                        asset_id=asset_id,
                    )
                    db.add(membership)

                saved_clusters.append(
                    {
                        "cluster_id": cluster.public_id,
                        "name": cluster.name,
                        "asset_count": cluster.asset_count,
                    }
                )

        await db.commit()

        await _update_agent_task(
            db,
            task.public_id,
            status="completed",
            output_data={
                "clusters": saved_clusters,
                "summary_report": result.get("summary_report"),
            },
            subagent_result=result,
            finished_at=datetime.utcnow(),
        )

        return {
            "status": "completed" if result.get("success") else "failed",
            "task_id": task.public_id,
            "asset_count": len(req.asset_ids),
            "clusters": saved_clusters,
            "summary_report": result.get("summary_report"),
            "error": result.get("error"),
        }
    except Exception as e:
        await _update_agent_task(
            db,
            task.public_id,
            status="failed",
            error=str(e),
            finished_at=datetime.utcnow(),
        )
        return {
            "status": "error",
            "task_id": task.public_id,
            "asset_count": len(req.asset_ids),
            "error": str(e),
        }



# 功能：读取指定空间下已保存的资产聚类结果。
@router.get("/clusters", response_model=list[AssetClusterResponse])
async def get_asset_clusters(
    space_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve space_id from public_id or integer
    space_id_int = await resolve_space_id(db, space_id)

    stmt = select(AssetClusters).where(AssetClusters.space_id == space_id_int)
    result = await db.execute(stmt)
    clusters = result.scalars().all()

    response = []
    for cluster in clusters:
        # Get membership count
        membership_stmt = select(AssetClusterMembership).where(
            AssetClusterMembership.cluster_id == cluster.id
        )
        membership_result = await db.execute(membership_stmt)
        memberships = membership_result.scalars().all()
        asset_ids = [m.asset_id for m in memberships]

        response.append(
            AssetClusterResponse(
                cluster_id=cluster.public_id,
                name=cluster.name,
                description=cluster.description,
                summary_report=cluster.summary_report,
                asset_count=cluster.asset_count or len(asset_ids),
                assets=asset_ids,
            )
        )

    return response



# 功能：触发文档审核子 Agent，并落库审核日志与任务结果。
@router.post("/review/{doc_id}", response_model=ReviewResponse)
async def trigger_review(
    doc_id: str,
    req: ReviewRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Parse space_id
    try:
        space_id_int = int(req.space_id) if req.space_id else 0
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid space_id")

    # Create task record
    task = await _create_agent_task_record(
        db=db,
        agent_type="review",
        input_data={"doc_id": doc_id, "review_type": req.review_type},
        space_id=space_id_int,
        user_id=current_user.id,
    )

    await _update_agent_task(
        db, task.public_id, status="running", started_at=datetime.utcnow()
    )

    agent = create_main_agent(db)
    try:
        result = await agent.subagents.invoke_subagent(
            AgentType.REVIEW,
            {
                "user_request": f"审查文档 {doc_id}",
                "space_id": req.space_id,
                "user_id": current_user.id,
                "doc_id": doc_id,
                "review_type": req.review_type,
            },
        )

        # Save review log to database
        review_log = ReviewLogs(
            public_id=str(uuid.uuid4())[:32],
            doc_id=doc_id,  # Note: This should be UUID, not string
            review_type=req.review_type,
            score=result.get("score", 0.0),
            passed=result.get("passed", False),
            issues={
                "issues": result.get("issues", []),
                "recommendations": result.get("recommendations", []),
            },
            rework_needed=result.get("rework_needed", False),
            rework_count=result.get("rework_count", 0),
            final_status=result.get("final_status", "pending"),
            created_by=current_user.id,
        )
        db.add(review_log)
        await db.commit()

        await _update_agent_task(
            db,
            task.public_id,
            status="completed",
            output_data=result,
            subagent_result=result,
            finished_at=datetime.utcnow(),
        )

        return ReviewResponse(
            doc_id=doc_id,
            review_type=req.review_type,
            score=result.get("score", 0.0),
            passed=result.get("passed", False),
            issues=result.get("issues", []),
            final_status=result.get("final_status", "pending"),
            rework_count=result.get("rework_count", 0),
        )
    except Exception as e:
        await _update_agent_task(
            db,
            task.public_id,
            status="failed",
            error=str(e),
            finished_at=datetime.utcnow(),
        )
        return ReviewResponse(
            doc_id=doc_id,
            review_type=req.review_type,
            score=0.0,
            passed=False,
            issues=[str(e)],
            final_status="error",
            rework_count=0,
        )
