"""
Data Rights Service - 数据权益服务

Phase 1: 数据权益协商与交易的基础服务实现
"""

from __future__ import annotations

import hashlib
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import BlackboardEvents
from app.services.trade.negotiation_event_store import NegotiationEventStore
from app.services.trade.data_rights_events import (
    DataAssetRegisterPayload,
    DataRightsPayload,
    DataRightsCounterPayload,
    ComputationAgreementPayload,
    DataAccessAuditPayload,
    PolicyViolationPayload,
    RightsRevokePayload,
    DataRightsType,
    ComputationMethod,
    DataSensitivityLevel,
    QualityMetrics,
    ProcessingStep,
)
from app.services.trade.event_sourcing_blackboard import StateProjector
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class DataRightsService:
    """
    数据权益服务

    负责数据资产的登记、权益协商、交易执行和审计
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_store = NegotiationEventStore(db)
        self.state_projector = StateProjector(db)

    # =========================================================================
    # 数据资产管理（仅通过事件溯源维护，不写入 DataAssets 表）
    # =========================================================================

    async def register_data_asset(
        self,
        owner_id: int,
        asset_name: str,
        data_type: str,
        sensitivity_level: DataSensitivityLevel,
        raw_data_source: str,
        storage_location: str,
        asset_description: Optional[str] = None,
        processing_chain: Optional[List[ProcessingStep]] = None,
        quality_metrics: Optional[QualityMetrics] = None,
        data_size_bytes: int = 0,
        record_count: Optional[int] = None,
        related_entities: Optional[List[str]] = None,
    ) -> str:
        """
        登记数据资产

        Args:
            owner_id: 数据所有者ID
            asset_name: 资产名称
            data_type: 数据类型（medical, financial等）
            sensitivity_level: 敏感度级别
            raw_data_source: 原始数据来源
            storage_location: 存储位置
            asset_description: 资产描述
            processing_chain: 数据处理链
            quality_metrics: 质量指标
            data_size_bytes: 数据大小（字节）
            record_count: 记录数
            related_entities: 关联的知识图谱实体ID

        Returns:
            asset_id: 生成的资产ID
        """
        # 生成资产ID
        asset_id = f"asset_{uuid.uuid4().hex[:24]}"

        # 构建血缘链
        lineage_root = None
        processing_chain_hash = None

        if processing_chain:
            lineage_nodes = []
            previous_hash = "0"

            for step in processing_chain:
                node_data = f"{step.index}:{step.step_type}:{step.logic_code}:{previous_hash}"
                node_hash = hashlib.sha256(node_data.encode()).hexdigest()[:32]
                lineage_nodes.append({
                    "index": step.index,
                    "type": step.step_type,
                    "hash": node_hash,
                    "parent": previous_hash,
                })
                previous_hash = node_hash

            lineage_root = lineage_nodes[0]["hash"] if lineage_nodes else None
            processing_chain_hash = hashlib.sha256(
                str(processing_chain).encode()
            ).hexdigest()[:32]

        # 计算综合质量分
        overall_score = 0.0
        if quality_metrics:
            overall_score = quality_metrics.overall_score

        # 构建事件载荷
        payload = DataAssetRegisterPayload(
            asset_id=asset_id,
            owner_id=owner_id,
            asset_name=asset_name,
            asset_description=asset_description,
            data_type=data_type,
            sensitivity_level=sensitivity_level,
            raw_data_source=raw_data_source,
            processing_chain=processing_chain or [],
            lineage_root=lineage_root,
            quality_metrics=quality_metrics,
            storage_location=storage_location,
            data_size_bytes=data_size_bytes,
            record_count=record_count,
            related_entities=related_entities or [],
        )

        # 发出资产登记事件
        await self.event_store.append_event(
            session_id=asset_id,  # 资产ID作为会话ID
            session_type="data_asset",
            event_type="DATA_ASSET_REGISTER",
            agent_id=owner_id,
            agent_role="data_owner",
            payload=payload.model_dump(),
        )

        logger.info(f"Data asset registered: {asset_id} by owner {owner_id}")

        return asset_id

    async def get_data_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        获取数据资产信息

        仅从事件溯源中重建资产状态（不再查询 DataAssets 表）。
        """
        # 从事件溯源中重建资产状态
        events = await self.event_store.get_events(
            session_id=asset_id,
            start_seq=0,
        )

        if not events:
            return None

        # 找到最新的资产登记事件
        register_event = None
        for event in reversed(events):
            if event.event_type == "DATA_ASSET_REGISTER":
                register_event = event
                break

        if not register_event:
            return None

        return {
            "asset_id": asset_id,
            "owner_id": register_event.agent_id,
            **register_event.payload,
        }

    async def list_owner_assets(self, owner_id: int) -> List[Dict[str, Any]]:
        """
        列出所有者的数据资产

        从事件溯源黑板中查询 DATA_ASSET_REGISTER 事件重建列表。
        """
        result = await self.db.execute(
            select(BlackboardEvents)
            .where(
                and_(
                    BlackboardEvents.agent_id == owner_id,
                    BlackboardEvents.event_type == "DATA_ASSET_REGISTER",
                    BlackboardEvents.session_type == "data_asset",
                )
            )
            .order_by(BlackboardEvents.event_timestamp.desc())
        )
        events = result.scalars().all()

        # 注意：raw_data 不再作为可交易资产展示。
        # 可交易资产统一由 DataAssets 表承载（knowledge_report 等生成型资产）。
        return [
            {
                "asset_id": e.session_id,
                "asset_name": e.payload.get("asset_name", ""),
                "data_type": e.payload.get("data_type", ""),
                "asset_type": "raw_data",
                "is_available_for_trade": False,
            }
            for e in events
        ]

    # =========================================================================
    # 数据权益协商
    # =========================================================================

    async def initiate_rights_negotiation(
        self,
        owner_id: int,
        asset_id: str,
        offered_rights: List[DataRightsType],
        usage_scope: Dict[str, Any],
        computation_method: ComputationMethod,
        validity_period: int,
        price: Optional[float] = None,
        restrictions: Optional[List[str]] = None,
    ) -> str:
        """
        发起数据权益协商

        Args:
            owner_id: 数据所有者ID
            asset_id: 数据资产ID
            offered_rights: 提供的权益类型列表
            usage_scope: 使用范围定义
            computation_method: 隐私计算方法
            validity_period: 有效期（天）
            price: 期望价格
            restrictions: 附加限制

        Returns:
            negotiation_id: 协商会话ID
        """
        # 验证资产存在
        asset = await self.get_data_asset(asset_id)
        if not asset:
            raise ServiceError(404, f"Data asset not found: {asset_id}")

        if asset["owner_id"] != owner_id:
            raise ServiceError(403, "Only asset owner can initiate negotiation")

        # 验证敏感度与计算方法的兼容性
        sensitivity = asset.get("sensitivity_level", "medium")
        if sensitivity in ["high", "critical"] and computation_method == ComputationMethod.RAW_DATA:
            raise ServiceError(
                400,
                "High sensitivity data cannot use RAW_DATA computation method"
            )

        # 生成协商ID
        negotiation_id = f"dr_neg_{uuid.uuid4().hex[:20]}"

        # 构建权益报价
        rights_payload = DataRightsPayload(
            data_asset_id=asset_id,
            rights_types=offered_rights,
            usage_scope=usage_scope,
            computation_method=computation_method,
            anonymization_level=self._determine_anonymization_level(sensitivity),
            validity_period=validity_period,
            price=price,
            restrictions=restrictions or [],
        )

        # 发出协商发起事件
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="DATA_RIGHTS_NEGOTIATION_INIT",
            agent_id=owner_id,
            agent_role="data_owner",
            payload={
                "asset_id": asset_id,
                "offered_rights": [r.value for r in offered_rights],
                "quality_score": asset.get("quality_metrics", {}).get("overall_score", 0),
                "suggested_price": price,
                "privacy_level": sensitivity,
                **rights_payload.model_dump(),
            },
        )

        logger.info(f"Data rights negotiation initiated: {negotiation_id}")

        return negotiation_id

    async def counter_rights_offer(
        self,
        negotiation_id: str,
        buyer_id: int,
        requested_rights: List[DataRightsType],
        proposed_usage_scope: Dict[str, Any],
        proposed_computation_method: ComputationMethod,
        proposed_validity_period: int,
        counter_price: Optional[float] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        买方提出反报价

        Args:
            negotiation_id: 协商会话ID
            buyer_id: 买方ID
            requested_rights: 请求的权益类型
            proposed_usage_scope: 提议的使用范围
            proposed_computation_method: 提议的隐私计算方法
            proposed_validity_period: 提议的有效期
            counter_price: 反报价价格
            message: 协商消息

        Returns:
            反报价结果
        """
        # 验证协商存在
        events = await self.event_store.get_events(
            session_id=negotiation_id,
            start_seq=0,
        )

        if not events:
            raise ServiceError(404, "Negotiation not found")

        # 获取资产信息
        init_event = events[0]
        asset_id = init_event.payload.get("asset_id")

        # 构建反报价载荷
        counter_payload = DataRightsCounterPayload(
            original_rights_id=f"{negotiation_id}_offer_0",
            data_asset_id=asset_id,
            requested_rights_types=requested_rights,
            proposed_usage_scope=proposed_usage_scope,
            proposed_computation_method=proposed_computation_method,
            proposed_validity_period=proposed_validity_period,
            counter_price=counter_price,
            message=message,
        )

        # 发出反报价事件
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="DATA_RIGHTS_COUNTER",
            agent_id=buyer_id,
            agent_role="data_buyer",
            payload=counter_payload.model_dump(),
        )

        return {
            "negotiation_id": negotiation_id,
            "status": "countered",
            "counter_by": buyer_id,
        }

    async def grant_data_rights(
        self,
        negotiation_id: str,
        owner_id: int,
        final_rights: DataRightsPayload,
    ) -> str:
        """
        授予数据权益

        当协商达成一致后，正式授予权益
        """
        # 生成交易ID
        transaction_id = f"drt_{uuid.uuid4().hex[:20]}"

        # 发出权益授予事件
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="DATA_RIGHTS_GRANT",
            agent_id=owner_id,
            agent_role="data_owner",
            payload={
                "transaction_id": transaction_id,
                **final_rights.model_dump(),
            },
        )

        logger.info(f"Data rights granted: transaction {transaction_id}")

        return transaction_id

    # =========================================================================
    # 隐私计算协议
    # =========================================================================

    async def negotiate_computation_protocol(
        self,
        negotiation_id: str,
        data_sensitivity: DataSensitivityLevel,
        buyer_requirements: Dict[str, Any],
    ) -> ComputationAgreementPayload:
        """
        协商隐私计算协议

        根据数据敏感度和买方需求，选择最合适的隐私计算方法
        """
        # 评分逻辑
        method_scores = self._score_computation_methods(
            data_sensitivity,
            buyer_requirements,
        )

        # 选择最佳方法
        best_method = max(method_scores, key=lambda x: x["score"])
        selected_method = best_method["method"]

        # 生成约束
        constraints = self._generate_constraints(
            selected_method,
            data_sensitivity,
        )

        # 确定验证机制
        verification = self._get_verification_mechanism(selected_method)

        # 成本分摊（默认买方承担70%）
        cost_allocation = {"buyer": 0.7, "seller": 0.3}

        agreement = ComputationAgreementPayload(
            negotiation_id=negotiation_id,
            computation_method=selected_method,
            constraints=constraints,
            verification_mechanism=verification,
            cost_allocation=cost_allocation,
        )

        # 发出协议达成事件
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="COMPUTATION_AGREEMENT",
            agent_id=0,  # 系统决定
            agent_role="system",
            payload=agreement.model_dump(),
        )

        return agreement

    def _score_computation_methods(
        self,
        sensitivity: DataSensitivityLevel,
        requirements: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        为各种隐私计算方法评分
        """
        methods = [
            {
                "method": ComputationMethod.MULTI_PARTY_COMPUTATION,
                "data_exposure": "none",
                "precision": "exact",
                "overhead": "very_high",
            },
            {
                "method": ComputationMethod.TEE,
                "data_exposure": "encrypted",
                "precision": "exact",
                "overhead": "medium",
            },
            {
                "method": ComputationMethod.FEDERATED_LEARNING,
                "data_exposure": "none",
                "precision": "high",
                "overhead": "high",
            },
            {
                "method": ComputationMethod.DIFFERENTIAL_PRIVACY,
                "data_exposure": "aggregated",
                "precision": "noisy",
                "overhead": "low",
            },
        ]

        results = []
        for m in methods:
            score = 0.0

            # 敏感度匹配
            if sensitivity in [DataSensitivityLevel.HIGH, DataSensitivityLevel.CRITICAL]:
                if m["data_exposure"] == "none":
                    score += 50

            # 精度需求
            required_precision = requirements.get("precision")
            if required_precision == "exact" and m["precision"] == "exact":
                score += 30

            # 成本考量
            overhead_scores = {"low": 30, "medium": 20, "high": 10, "very_high": 0}
            score += overhead_scores.get(m["overhead"], 0)

            results.append({"method": m["method"], "score": score})

        return results

    def _generate_constraints(
        self,
        method: ComputationMethod,
        sensitivity: DataSensitivityLevel,
    ) -> Dict[str, Any]:
        """生成计算约束"""
        if method == ComputationMethod.DIFFERENTIAL_PRIVACY:
            # 高敏感度数据使用更小的 epsilon（更多噪声）
            epsilon = 0.1 if sensitivity == DataSensitivityLevel.CRITICAL else 0.5
            return {"epsilon": epsilon, "delta": 1e-5}

        elif method == ComputationMethod.MULTI_PARTY_COMPUTATION:
            return {"min_participants": 3, "corruption_threshold": 1}

        elif method == ComputationMethod.TEE:
            return {"attestation_required": True, "secure_boot": True}

        return {}

    def _get_verification_mechanism(self, method: ComputationMethod) -> str:
        """获取验证机制"""
        if method == ComputationMethod.TEE:
            return "tee_attestation"
        elif method == ComputationMethod.MULTI_PARTY_COMPUTATION:
            return "protocol_verification"
        else:
            return "third_party_audit"

    # =========================================================================
    # 审计与合规
    # =========================================================================

    async def record_data_access(
        self,
        transaction_id: str,
        negotiation_id: str,
        data_asset_id: str,
        buyer_id: int,
        access_purpose: str,
        computation_method_used: ComputationMethod,
        query_fingerprint: str,
        result_size_bytes: int,
        result_aggregation_level: str,
        policy_compliance: Dict[str, Any],
    ) -> None:
        """
        记录数据访问审计日志
        """
        audit_payload = DataAccessAuditPayload(
            negotiation_id=negotiation_id,
            data_asset_id=data_asset_id,
            data_buyer=buyer_id,
            access_timestamp=datetime.now(timezone.utc),
            access_purpose=access_purpose,
            computation_method_used=computation_method_used,
            query_fingerprint=query_fingerprint,
            result_size_bytes=result_size_bytes,
            result_aggregation_level=result_aggregation_level,
            policy_compliance_check=policy_compliance,
        )

        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="DATA_ACCESS_AUDIT",
            agent_id=buyer_id,
            agent_role="data_buyer",
            payload=audit_payload.model_dump(),
        )

    async def report_policy_violation(
        self,
        negotiation_id: str,
        violation_type: str,
        severity: str,
        details: Dict[str, Any],
        evidence: Dict[str, Any],
        automatic_action: Optional[str] = None,
    ) -> None:
        """
        报告策略违规
        """
        violation_payload = PolicyViolationPayload(
            negotiation_id=negotiation_id,
            violation_type=violation_type,
            severity=severity,
            violation_details=details,
            evidence=evidence,
            automatic_action_taken=automatic_action,
        )

        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="POLICY_VIOLATION",
            agent_id=0,  # 系统报告
            agent_role="system",
            payload=violation_payload.model_dump(),
        )

    async def revoke_rights(
        self,
        transaction_id: str,
        negotiation_id: str,
        revoked_by: int,
        reason: str,
        revoke_type: str,
    ) -> None:
        """
        撤销数据权益
        """
        revoke_payload = RightsRevokePayload(
            negotiation_id=negotiation_id,
            rights_id=transaction_id,
            revoked_by=revoked_by,
            revoke_reason=reason,
            revoke_type=revoke_type,
        )

        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="RIGHTS_REVOKE",
            agent_id=revoked_by,
            agent_role="data_owner" if revoke_type != "breach" else "system",
            payload=revoke_payload.model_dump(),
        )

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _determine_anonymization_level(
        self,
        sensitivity: str,
    ) -> int:
        """根据敏感度确定默认脱敏级别"""
        level_map = {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }
        return level_map.get(sensitivity, 2)

    async def get_negotiation_history(
        self,
        negotiation_id: str,
    ) -> List[Dict[str, Any]]:
        """
        获取协商历史
        """
        events = await self.event_store.get_events(
            session_id=negotiation_id,
            start_seq=0,
        )

        return [
            {
                "sequence": e.sequence_number,
                "event_type": e.event_type,
                "agent_id": e.agent_id,
                "agent_role": e.agent_role,
                "timestamp": e.event_timestamp.isoformat(),
                "payload": e.payload,
            }
            for e in events
        ]
