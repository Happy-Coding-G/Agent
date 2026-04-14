"""
Token Usage API - Token用量统计接口

提供用户查询自己Token使用情况的API端点
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.db.session import get_db
from app.db.models import Users, FeatureType
from app.services.token_usage_service import TokenUsageService
from app.schemas.common import ResponseModel

router = APIRouter()


@router.get("/summary", response_model=ResponseModel[Dict[str, Any]])
async def get_usage_summary(
    start_date: Optional[datetime] = Query(None, description="开始日期 (ISO格式)"),
    end_date: Optional[datetime] = Query(None, description="结束日期 (ISO格式)"),
    days: int = Query(30, ge=1, le=365, description="查询最近N天"),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取Token用量汇总统计

    包括：
    - 总请求数
    - 总Token消耗
    - 总成本
    - 按功能分类统计
    - 按模型分类统计
    """
    # 如果未指定日期，使用days参数
    if start_date is None:
        start_date = datetime.utcnow() - timedelta(days=days)
    if end_date is None:
        end_date = datetime.utcnow()

    service = TokenUsageService(db)
    summary = await service.get_user_usage_summary(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
    )

    return ResponseModel(
        success=True,
        data=summary,
    )


@router.get("/daily", response_model=ResponseModel[List[Dict[str, Any]]])
async def get_daily_usage(
    days: int = Query(30, ge=1, le=365, description="查询最近N天"),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取每日Token用量趋势
    """
    service = TokenUsageService(db)
    daily_usage = await service.get_user_daily_usage(
        user_id=current_user.id,
        days=days,
    )

    return ResponseModel(
        success=True,
        data=daily_usage,
    )


@router.get("/recent", response_model=ResponseModel[List[Dict[str, Any]]])
async def get_recent_usage(
    limit: int = Query(50, ge=1, le=200, description="返回记录数"),
    feature: Optional[str] = Query(None, description="按功能类型筛选"),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取最近Token使用明细

    可用于查看具体每次调用的详细信息，包括功能边界标识
    """
    service = TokenUsageService(db)

    if feature:
        try:
            feature_type = FeatureType(feature)
            usages = await service.get_feature_boundary_usage(
                user_id=current_user.id,
                feature_type=feature_type,
                limit=limit,
            )
        except ValueError:
            usages = []
    else:
        usages = await service.get_recent_usage(
            user_id=current_user.id,
            limit=limit,
        )

    return ResponseModel(
        success=True,
        data=usages,
    )


@router.get("/features", response_model=ResponseModel[List[Dict[str, str]]])
async def get_feature_types(
    current_user: Users = Depends(get_current_user),
):
    """
    获取功能类型列表

    返回所有可用的功能边界标识类型，用于前端筛选
    """
    features = [
        {"value": f.value, "label": _get_feature_label(f)}
        for f in FeatureType
    ]

    return ResponseModel(
        success=True,
        data=features,
    )


def _get_feature_label(feature: FeatureType) -> str:
    """获取功能类型中文标签"""
    labels = {
        FeatureType.CHAT: "RAG对话",
        FeatureType.CHAT_STREAM: "流式对话",
        FeatureType.ASSET_GENERATION: "资产生成",
        FeatureType.ASSET_ORGANIZE: "资产整理",
        FeatureType.TRADE_NEGOTIATION: "交易协商",
        FeatureType.TRADE_PRICING: "交易定价",
        FeatureType.INGEST_PIPELINE: "文档摄入",
        FeatureType.GRAPH_CONSTRUCTION: "图谱构建",
        FeatureType.REVIEW: "文档审核",
        FeatureType.FILE_QUERY: "文件查询",
        FeatureType.EMBEDDING: "文本嵌入",
        FeatureType.OTHER: "其他",
    }
    return labels.get(feature, feature.value)


@router.post("/admin/initialize-prices", response_model=ResponseModel[Dict[str, str]])
async def initialize_model_prices(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    初始化模型定价 (管理员接口)

    初始化各模型的Token单价数据
    """
    # 简单权限检查 (实际项目中应该使用更完善的权限系统)
    if not current_user.is_admin:
        return ResponseModel(
            success=False,
            message="权限不足",
        )

    service = TokenUsageService(db)
    await service.initialize_model_prices()

    return ResponseModel(
        success=True,
        data={"message": "模型定价初始化成功"},
    )
