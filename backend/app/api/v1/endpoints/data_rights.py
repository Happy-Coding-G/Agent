"""
数据权益执行 API

提供数据访问时的权益强制执行接口。
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.data_rights import RightsEnforcementEngine, enforce_data_access
from app.core.errors import ServiceError

router = APIRouter(prefix="/data-rights", tags=["data-rights"])


class DataAccessRequest(BaseModel):
    """数据访问请求"""
    transaction_id: str = Field(..., description="权益交易ID")
    query: str = Field(..., description="数据查询语句")
    access_type: str = Field(default="query", description="访问类型: query/download/api")


class DataAccessResponse(BaseModel):
    """数据访问响应"""
    success: bool
    data: Optional[list] = None
    metadata: dict = Field(default_factory=dict)
    watermark_info: Optional[dict] = None
    message: str = ""


class UsageStatsResponse(BaseModel):
    """使用情况统计响应"""
    transaction_id: str
    total_accesses: int
    total_rows_accessed: int
    unique_queries: int
    policy_type: str


@router.post("/access", response_model=DataAccessResponse)
async def access_data_with_rights(
    request: DataAccessRequest,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    在权益保护下访问数据

    此接口会自动：
    1. 验证权益交易是否有效
    2. 检查访问权限
    3. 改写查询以符合权益限制
    4. 添加数字水印
    5. 记录审计日志

    示例：
    ```json
    {
        "transaction_id": "txn_abc123",
        "query": "SELECT * FROM sales_data WHERE region='CN'",
        "access_type": "query"
    }
    ```
    """
    try:
        # 创建执行引擎
        engine = RightsEnforcementEngine(
            db,
            request.transaction_id,
            current_user.id
        )

        # 检查访问权限
        allowed, reason = await engine.check_access_permission(request.access_type)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

        # 改写查询
        rewritten_query = await engine.rewrite_query(request.query)

        # 执行查询（这里应该调用实际的数据查询服务）
        # 为演示，返回元数据
        metadata = {
            "original_query": request.query,
            "rewritten_query": rewritten_query,
            "enforced": True,
            "buyer_id": current_user.id,
            "transaction_id": request.transaction_id,
        }

        return DataAccessResponse(
            success=True,
            data=[],  # 实际应该返回查询结果
            metadata=metadata,
            watermark_info={
                "applied": True,
                "type": "visible",
                "notice": "This data is provided under license.",
            },
            message="Access permitted with rights enforcement",
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/stats/{transaction_id}", response_model=UsageStatsResponse)
async def get_usage_statistics(
    transaction_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取数据权益使用统计

    返回指定权益交易的使用情况统计。
    """
    try:
        engine = RightsEnforcementEngine(
            db,
            transaction_id,
            current_user.id
        )

        stats = await engine.get_usage_stats()

        return UsageStatsResponse(
            transaction_id=transaction_id,
            **stats
        )

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/validate")
async def validate_rights(
    transaction_id: str,
    access_type: str = "query",
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    验证数据权益是否有效

    在实际访问数据前，可以先调用此接口验证权限。
    """
    try:
        engine = RightsEnforcementEngine(
            db,
            transaction_id,
            current_user.id
        )

        allowed, reason = await engine.check_access_permission(access_type)

        return {
            "valid": allowed,
            "transaction_id": transaction_id,
            "access_type": access_type,
            "message": reason,
        }

    except ServiceError as e:
        return {
            "valid": False,
            "transaction_id": transaction_id,
            "access_type": access_type,
            "message": str(e),
        }
