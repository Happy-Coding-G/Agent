"""
Hybrid Negotiation API - 调试与查询接口 (直接交易模式)

协商和拍卖场景已移除，当前仅支持直接交易。
本端点保留用于查询和历史会话管理。
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.core.errors import ServiceError

router = APIRouter(prefix="/hybrid-negotiations", tags=["hybrid-negotiations"])


class MechanismTypeInfo(BaseModel):
    mechanism_type: str
    description: str
    recommended_for: str


class ScenarioAnalysisResponse(BaseModel):
    mechanism_type: str
    participant_count: int
    expected_concurrency: str
    requires_full_audit: bool
    recommended_engine: str
    engine_description: str


class AuditLogResponse(BaseModel):
    sequence: int
    type: str
    agent_id: int
    role: str
    payload: Dict[str, Any]
    timestamp: str
    vector_clock: Optional[Dict[str, int]]


@router.get("/mechanisms", response_model=List[MechanismTypeInfo])
async def list_mechanism_types():
    """
    列出支持的机制类型

    当前仅支持直接交易。
    """
    return [
        MechanismTypeInfo(
            mechanism_type="direct",
            description="直接交易",
            recommended_for="Agent 评估后一键下单，无需协商"
        ),
    ]


@router.post("/analyze-scenario", response_model=ScenarioAnalysisResponse)
async def analyze_scenario(
    mechanism_type: str = Query(..., description="交易机制类型"),
    expected_participants: int = Query(1, ge=1, description="预期参与者数量"),
    requires_audit: bool = Query(False, description="是否需要完整审计"),
):
    """
    分析场景并推荐引擎

    当前所有场景统一返回 direct + simple。
    """
    return ScenarioAnalysisResponse(
        mechanism_type="direct",
        participant_count=expected_participants,
        expected_concurrency="low",
        requires_full_audit=requires_audit,
        recommended_engine="simple",
        engine_description="直接交易模式 - Agent 评估后一键完成",
    )


@router.get("/comparison", response_model=Dict[str, Any])
async def get_architecture_comparison():
    """
    架构对比说明

    当前仅保留直接交易模式。
    """
    return {
        "comparison": {
            "direct_trade": {
                "name": "直接交易",
                "use_case": "Agent 检索评估后直接下单",
                "storage": "直接状态存储（JSONB）",
                "query_performance": "O(1) - 直接读取当前状态",
                "concurrency_handling": "标准数据库事务",
                "audit_capability": "基础（订单记录）",
                "complexity": "低",
                "best_for": [
                    "标准化数据资产交易",
                    "无需价格协商的场景",
                    "快速成交"
                ]
            }
        },
        "note": "协商和拍卖场景已移除，当前仅支持直接交易模式。"
    }
