"""
协作与血缘API端点

提供：
- 数据血缘查询API
- 影响分析API
- 实时协作WebSocket
- 在线状态管理
"""

from typing import Any, Dict, List, Optional

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.core.security.acl import Permission, ResourceType, require_permission
from app.db.models import DataLineageType, OperationType, Users
from app.services.collaboration_service import (
    CollaborationResourceType,
    CollaborationService,
    CollaborationWebSocketHandler,
    get_collaboration_service,
)
from app.services.asset_lineage_pricing_service import AssetLineagePricingService

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_asset_lineage(entity_type: DataLineageType) -> None:
    if entity_type != DataLineageType.ASSET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only asset lineage is supported",
        )


# ============================================================================
# 数据血缘API
# ============================================================================

@router.get(
    "/lineage/{entity_type}/{entity_id}",
    response_model=Dict[str, Any],
    summary="获取数据血缘",
    description="获取实体的完整数据血缘（上下游）。注意：当前仅支持 entity_type=asset",
)
async def get_lineage(
    entity_type: DataLineageType,
    entity_id: str,
    direction: str = Query("both", enum=["upstream", "downstream", "both"]),
    max_depth: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """获取数据血缘"""
    _ensure_asset_lineage(entity_type)
    service = AssetLineagePricingService(db)

    result = {}

    if direction in ["upstream", "both"]:
        upstream = await service.get_upstream_lineage(entity_id, max_depth)
        result["upstream"] = [
            {
                "nodes": p.get("nodes", []),
                "confidence": p.get("total_confidence", 1.0),
            }
            for p in upstream
        ]

    if direction in ["downstream", "both"]:
        downstream = await service.get_downstream_lineage(entity_id, max_depth)
        result["downstream"] = [
            {
                "nodes": p.get("nodes", []),
                "confidence": p.get("total_confidence", 1.0),
            }
            for p in downstream
        ]

    return result


@router.get(
    "/lineage/{entity_type}/{entity_id}/graph",
    response_model=Dict[str, Any],
    summary="获取血缘图",
    description="获取用于可视化的血缘图数据。注意：当前仅支持 entity_type=asset",
)
async def get_lineage_graph(
    entity_type: DataLineageType,
    entity_id: str,
    max_depth: int = Query(3, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """获取血缘图数据"""
    _ensure_asset_lineage(entity_type)
    service = AssetLineagePricingService(db)
    return await service.get_lineage_graph(entity_id, max_depth)


@router.get(
    "/lineage/{entity_type}/{entity_id}/impact",
    response_model=Dict[str, Any],
    summary="影响分析",
    description="分析修改某实体可能产生的影响。注意：当前仅支持 entity_type=asset",
)
async def analyze_impact(
    entity_type: DataLineageType,
    entity_id: str,
    max_depth: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """影响分析"""
    _ensure_asset_lineage(entity_type)
    service = AssetLineagePricingService(db)
    return await service.get_impact_report(entity_id, max_depth)


@router.get(
    "/spaces/{space_id}/lineage/stats",
    response_model=Dict[str, Any],
    summary="血缘统计",
    description="获取Space的数据血缘统计信息",
)
async def get_lineage_stats(
    space_id: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """血缘统计"""
    service = AssetLineagePricingService(db)
    return await service.get_lineage_statistics(space_id, days)


# ============================================================================
# 协作API
# ============================================================================

@router.get(
    "/spaces/{space_id}/collaboration/sessions",
    response_model=List[Dict[str, Any]],
    summary="活跃会话列表",
    description="获取Space中的所有活跃协作会话",
)
async def get_collaboration_sessions(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """获取活跃会话"""
    service = await get_collaboration_service(db)
    return await service.get_active_sessions(space_id)


@router.get(
    "/spaces/{space_id}/collaboration/{resource_type}/{resource_id}/presence",
    response_model=List[Dict[str, Any]],
    summary="在线用户列表",
    description="获取资源的在线用户列表",
)
async def get_presence(
    space_id: str,
    resource_type: CollaborationResourceType,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """获取在线用户"""
    service = await get_collaboration_service(db)
    return await service.get_presence_list(space_id, resource_type, resource_id)


@router.get(
    "/spaces/{space_id}/collaboration/{resource_type}/{resource_id}/history",
    response_model=List[Dict[str, Any]],
    summary="操作历史",
    description="获取资源的协作操作历史",
)
async def get_operation_history(
    space_id: str,
    resource_type: CollaborationResourceType,
    resource_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """操作历史"""
    service = await get_collaboration_service(db)
    return await service.get_operation_history(
        space_id, resource_type, resource_id, limit
    )


@router.get(
    "/spaces/{space_id}/collaboration/stats",
    response_model=Dict[str, Any],
    summary="协作统计",
    description="获取Space的协作统计信息",
)
async def get_collaboration_stats(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """协作统计"""
    service = await get_collaboration_service(db)
    return await service.get_collaboration_stats(space_id)


# ============================================================================
# WebSocket协作端点
# ============================================================================

@router.websocket("/ws/spaces/{space_id}/collaborate/{resource_type}/{resource_id}")
async def collaboration_websocket(
    websocket: WebSocket,
    space_id: str,
    resource_type: CollaborationResourceType,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    WebSocket协作端点

    消息协议:
    - presence_update: 更新在线状态
    - operation: 发送协作操作
    - get_history: 获取操作历史
    """
    # 从查询参数或token获取用户ID（简化处理）
    # 实际应用中应该通过JWT token验证
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    try:
        # 解析token获取user_id（简化实现）
        # 实际应该使用JWT验证
        user_id = int(websocket.query_params.get("user_id", 0))
        if not user_id:
            await websocket.close(code=4001, reason="Invalid user")
            return

        # 检查权限
        service = await get_collaboration_service(db)
        has_permission = await service.check_collaboration_permission(
            space_id, user_id, Permission.READ
        )

        if not has_permission:
            await websocket.close(code=4003, reason="Permission denied")
            return

        # 处理WebSocket连接
        handler = CollaborationWebSocketHandler(service)
        await handler.handle(websocket, space_id, resource_type, resource_id, user_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close(code=4000, reason="Internal error")


# ============================================================================
# 管理API
# ============================================================================

@router.post(
    "/admin/lineage/purge",
    response_model=Dict[str, Any],
    summary="清理旧血缘数据",
    description="管理员清理过期的血缘数据",
)
async def purge_lineage(
    days: int = Query(365, ge=30, le=1825),
    dry_run: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """清理旧血缘数据"""
    # 检查管理员权限
    # TODO: 实现管理员权限检查

    service = AssetLineagePricingService(db)
    count = await service.purge_old_lineage(days, dry_run)

    return {
        "purged_count": count,
        "dry_run": dry_run,
        "days_threshold": days,
    }


@router.post(
    "/admin/collaboration/cleanup",
    response_model=Dict[str, Any],
    summary="清理不活跃会话",
    description="清理长时间不活跃的协作会话",
)
async def cleanup_sessions(
    max_idle_minutes: int = Query(30, ge=5, le=1440),
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """清理不活跃会话"""
    service = await get_collaboration_service(db)
    count = await service.cleanup_inactive_sessions(max_idle_minutes)

    return {
        "cleaned_sessions": count,
        "max_idle_minutes": max_idle_minutes,
    }
