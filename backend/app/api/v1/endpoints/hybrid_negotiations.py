"""
Hybrid Negotiation API - 调试与查询接口
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.trade.hybrid_negotiation_service import (
    HybridNegotiationService,
    ScenarioProfile,
    NegotiationMechanism,
    AuctionEngine,
)
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
    return [
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.BILATERAL,
            description="双边协商（1对1）",
            recommended_for="买卖双方一对一价格协商，低并发场景"
        ),
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.AUCTION,
            description="拍卖（1对N）",
            recommended_for="多方竞拍场景，需要处理高并发出价"
        ),
        MechanismTypeInfo(
            mechanism_type=NegotiationMechanism.CONTRACT_NET,
            description="合同网（任务招标）",
            recommended_for="任务分发和承包商选择"
        ),
    ]


@router.post("/analyze-scenario", response_model=ScenarioAnalysisResponse)
async def analyze_scenario(
    mechanism_type: str = Query(..., description="协商机制类型"),
    expected_participants: int = Query(2, ge=2, description="预期参与者数量"),
    requires_audit: bool = Query(False, description="是否需要完整审计"),
):
    try:
        profile = HybridNegotiationService.analyze_scenario(
            mechanism_type=mechanism_type,
            expected_participants=expected_participants,
            requires_audit=requires_audit,
        )

        engine_desc = {
            "simple": "简化版（直接状态存储）- 适用于低并发、简单查询场景",
            "event_sourced": "事件溯源版 - 适用于高并发、需要完整审计的场景"
        }.get(profile.recommended_engine, "未知")

        return ScenarioAnalysisResponse(
            mechanism_type=profile.mechanism_type.value,
            participant_count=profile.participant_count,
            expected_concurrency=profile.expected_concurrency.value,
            requires_full_audit=profile.requires_full_audit,
            recommended_engine=profile.recommended_engine,
            engine_description=engine_desc,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}/state", response_model=Dict[str, Any])
async def get_negotiation_state(
    session_id: str,
    include_audit_log: bool = Query(False, description="是否包含完整审计日志"),
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = HybridNegotiationService(db)
        state = await service.get_state(
            session_id=session_id,
            include_audit_log=include_audit_log,
        )
        return state

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/{session_id}/audit-log", response_model=List[AuditLogResponse])
async def get_audit_log(
    session_id: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        from sqlalchemy import select
        from app.db.models import NegotiationSessions

        result = await db.execute(
            select(NegotiationSessions).where(
                NegotiationSessions.negotiation_id == session_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if session.seller_user_id != current_user.id and session.buyer_user_id != current_user.id:
            pass

        from app.services.trade.hybrid_negotiation_service import AuctionEngine

        auction_engine = AuctionEngine(db)
        audit_log = await auction_engine.get_full_audit_log(session_id)

        return [AuditLogResponse(**event) for event in audit_log]

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/comparison", response_model=Dict[str, Any])
async def get_architecture_comparison():
    return {
        "comparison": {
            "simplified": {
                "name": "简化版（双边协商）",
                "use_case": "1对1协商",
                "storage": "直接状态存储（JSONB）",
                "query_performance": "O(1) - 直接读取当前状态",
                "concurrency_handling": "乐观锁（version字段）",
                "audit_capability": "有限（仅保留最近N条历史）",
                "complexity": "低",
                "best_for": [
                    "买卖双方一对一协商",
                    "低并发场景",
                    "快速查询当前状态",
                    "简单业务逻辑"
                ]
            },
            "event_sourced": {
                "name": "事件溯源版（拍卖）",
                "use_case": "1对N拍卖",
                "storage": "事件流 + 投影状态",
                "query_performance": "O(1)投影查询 / O(n)事件重放",
                "concurrency_handling": "乐观锁 + 事件顺序保证",
                "audit_capability": "完整（不可篡改的事件历史）",
                "complexity": "中",
                "best_for": [
                    "多方竞拍场景",
                    "高并发出价",
                    "需要完整审计日志",
                    "顺序敏感的业务"
                ]
            }
        },
        "routing_logic": {
            "description": "自动路由决策逻辑",
            "rules": [
                {"condition": "mechanism_type == 'bilateral'", "engine": "simplified"},
                {"condition": "mechanism_type == 'auction' AND participants <= 2", "engine": "simplified"},
                {"condition": "mechanism_type == 'auction' AND participants > 2", "engine": "event_sourced"},
                {"condition": "mechanism_type == 'contract_net'", "engine": "event_sourced"}
            ]
        },
        "note": "Agent-First 架构中，机制选择和引擎路由由 TradeAgent 自动处理，无需手动指定。"
    }
