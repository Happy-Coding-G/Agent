"""
Asset Lineage Pricing Service - 资产血缘与定价统一服务

整合血缘追踪、质量评估、确定性定价三大能力：
- 无 ML 强依赖（torch/scipy）
- 血缘数据直接驱动定价因子
- 统一使用 data_lineage 表（兼容 current_entity_type/current_entity_id 等现有列）
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataAssets, DataLineage, DataLineageType
from app.services.trade.data_rights_events import (
    ComputationMethod,
    DataRightsType,
    DataSensitivityLevel,
    QualityMetrics,
)
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)
LINEAGE_HASH_VERSION = "asset_lineage_pricing_v1"

# ============================================================================
# 常量与配置
# ============================================================================

BASE_PRICE_BY_TYPE = {
    "medical": 10000.0,
    "financial": 8000.0,
    "behavioral": 5000.0,
    "location": 3000.0,
    "demographic": 2000.0,
    "generic": 1000.0,
}

RIGHTS_VALUE_MULTIPLIERS = {
    DataRightsType.USAGE_RIGHT: 0.3,
    DataRightsType.ANALYSIS_RIGHT: 0.5,
    DataRightsType.DERIVATIVE_RIGHT: 0.8,
    DataRightsType.SUB_LICENSE_RIGHT: 1.0,
}

RIGHTS_TYPE_ALIASES = {
    "view": DataRightsType.USAGE_RIGHT,
    "usage": DataRightsType.USAGE_RIGHT,
    "usage_right": DataRightsType.USAGE_RIGHT,
    "download": DataRightsType.ANALYSIS_RIGHT,
    "analysis": DataRightsType.ANALYSIS_RIGHT,
    "analysis_right": DataRightsType.ANALYSIS_RIGHT,
    "derivative": DataRightsType.DERIVATIVE_RIGHT,
    "derivative_right": DataRightsType.DERIVATIVE_RIGHT,
    "sub_license": DataRightsType.SUB_LICENSE_RIGHT,
    "sub_license_right": DataRightsType.SUB_LICENSE_RIGHT,
}

SENSITIVITY_DISCOUNTS = {
    DataSensitivityLevel.LOW: 1.0,
    DataSensitivityLevel.MEDIUM: 0.9,
    DataSensitivityLevel.HIGH: 0.7,
    DataSensitivityLevel.CRITICAL: 0.5,
}

COMPUTATION_COST_FACTORS = {
    ComputationMethod.RAW_DATA: 0.0,
    ComputationMethod.DIFFERENTIAL_PRIVACY: 0.1,
    ComputationMethod.TEE: 0.3,
    ComputationMethod.FEDERATED_LEARNING: 0.5,
    ComputationMethod.MULTI_PARTY_COMPUTATION: 1.0,
}

COMPUTATION_METHOD_ALIASES = {
    "raw_data": ComputationMethod.RAW_DATA,
    "differential_privacy": ComputationMethod.DIFFERENTIAL_PRIVACY,
    "tee": ComputationMethod.TEE,
    "trusted_execution_environment": ComputationMethod.TEE,
    "federated_learning": ComputationMethod.FEDERATED_LEARNING,
    "mpc": ComputationMethod.MULTI_PARTY_COMPUTATION,
    "multi_party_computation": ComputationMethod.MULTI_PARTY_COMPUTATION,
}


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class PricingFactors:
    """定价因子明细"""
    base_value: float
    quality_multiplier: float
    scarcity_multiplier: float
    lineage_multiplier: float
    rights_scope_multiplier: float
    market_multiplier: float
    sensitivity_multiplier: float
    computation_cost: float


@dataclass
class PricingResult:
    """定价结果"""
    asset_id: str
    base_value: float
    fair_value: float
    recommended_price: float
    price_range_min: float
    price_range_max: float
    factors: PricingFactors
    lineage_verified: bool
    quality_score: float


@dataclass
class PriceRange:
    """价格区间"""
    min: float
    recommended: float
    max: float


# ============================================================================
# 核心服务
# ============================================================================

class AssetLineagePricingService:
    """资产血缘与定价统一服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================================
    # 血缘记录
    # ========================================================================

    async def record_lineage(
        self,
        current_entity_type: DataLineageType,
        current_entity_id: str,
        relationship: str,
        source_type: Optional[DataLineageType] = None,
        source_id: Optional[str] = None,
        user_id: int | None = None,
        space_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        confidence_score: float = 1.0,
        transformation_logic: Optional[str] = None,
        auto_commit: bool = False,
    ) -> DataLineage:
        """记录数据血缘关系（使用 DataLineage 现有字段名）。"""
        if user_id is None:
            raise ValueError("user_id is required when recording lineage")

        lineage_id = f"lin_{snowflake_id()}"
        current_type = self._entity_type_value(current_entity_type)
        source_type_value = self._entity_type_value(source_type) if source_type else "unknown"
        source_id_value = source_id or ""
        parent_hashes = await self._get_parent_hashes(source_type_value, source_id_value)
        step_index = await self._get_next_step_index(current_type, current_entity_id)
        lineage_hash = self._calculate_lineage_hash(
            source_type=source_type_value,
            source_id=source_id_value,
            current_entity_type=current_type,
            current_entity_id=current_entity_id,
            relationship=relationship,
            transformation_logic=transformation_logic,
            parent_hashes=parent_hashes,
            step_index=step_index,
        )
        metadata = dict(extra_metadata or {})
        metadata["hash_version"] = LINEAGE_HASH_VERSION
        metadata["parent_hashes"] = parent_hashes

        lineage = DataLineage(
            id=snowflake_id(),
            lineage_id=lineage_id,
            current_entity_type=current_type,
            current_entity_id=current_entity_id,
            source_type=source_type_value,
            source_id=source_id_value,
            source_metadata=metadata,
            relationship=relationship,
            transformation_logic=transformation_logic,
            confidence_score=confidence_score,
            lineage_hash=lineage_hash,
            parent_hash=parent_hashes[0] if parent_hashes else None,
            step_index=step_index,
            space_id=space_id,
            extra_metadata=metadata,
            created_by=user_id,
        )

        self.db.add(lineage)
        await self.db.flush()
        if auto_commit:
            await self.db.commit()
            await self.db.refresh(lineage)

        logger.info(
            f"Lineage recorded: {lineage_id} - {current_type}:{current_entity_id} "
            f"<- {source_type_value}:{source_id_value}"
        )
        return lineage

    async def build_asset_lineage(
        self,
        asset_id: str,
        processing_chain: List[Dict[str, Any]],
        user_id: int | None = None,
        auto_commit: bool = False,
    ) -> Optional[str]:
        """
        构建完整的数据血缘链。

        Args:
            asset_id: 数据资产ID
            processing_chain: 数据处理步骤列表，每项含 step_type, logic, quality_report

        Returns:
            lineage_root: 血缘根节点哈希
        """
        if user_id is None:
            raise ValueError("user_id is required when building lineage")

        previous_hash = "0"
        root_hash = None

        for i, step in enumerate(processing_chain):
            node_id = f"{asset_id}_node_{i}"
            logic = step.get("logic", "")
            logic_hash = hashlib.sha256(logic.encode()).hexdigest()[:32]

            parent_hashes = [] if previous_hash == "0" else [previous_hash]
            relationship = step.get("step_type", "processed")
            transformation_logic = logic[:200]
            provenance_hash = self._calculate_lineage_hash(
                source_type="unknown",
                source_id="",
                current_entity_type=DataLineageType.ASSET.value,
                current_entity_id=asset_id,
                relationship=relationship,
                transformation_logic=transformation_logic,
                parent_hashes=parent_hashes,
                step_index=i,
            )

            lineage_id = f"lin_{snowflake_id()}"
            metadata = {
                "node_id": node_id,
                "logic_hash": logic_hash,
                "hash_version": LINEAGE_HASH_VERSION,
                "parent_hashes": parent_hashes,
            }
            lineage = DataLineage(
                id=snowflake_id(),
                lineage_id=lineage_id,
                current_entity_type=DataLineageType.ASSET.value,
                current_entity_id=asset_id,
                source_type="unknown",
                source_id="",
                relationship=relationship,
                transformation_logic=transformation_logic,
                confidence_score=1.0,
                lineage_hash=provenance_hash,
                parent_hash=previous_hash if previous_hash != "0" else None,
                step_index=i,
                quality_metrics=step.get("quality_report", {}),
                source_metadata=metadata,
                extra_metadata=metadata,
                created_by=user_id,
            )
            self.db.add(lineage)

            if i == 0:
                root_hash = provenance_hash
            previous_hash = provenance_hash

        await self.db.flush()
        if auto_commit:
            await self.db.commit()
        logger.info(f"Built lineage chain for {asset_id}: {len(processing_chain)} nodes")
        return root_hash

    # ========================================================================
    # 血缘查询
    # ========================================================================

    async def get_upstream_lineage(
        self,
        asset_id: str,
        max_depth: int = 5,
        min_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """获取上游血缘（数据来源）。"""
        paths: List[List[DataLineage]] = []
        visited: set = set()

        async def _trace(
            current_type: str,
            current_id: str,
            current_path: List[DataLineage],
            depth: int,
        ) -> None:
            if depth > max_depth or f"{current_type}:{current_id}" in visited:
                return
            visited.add(f"{current_type}:{current_id}")

            result = await self.db.execute(
                select(DataLineage)
                .where(
                    and_(
                        DataLineage.current_entity_type == current_type,
                        DataLineage.current_entity_id == current_id,
                        DataLineage.source_id.isnot(None),
                        DataLineage.source_id != "",
                        DataLineage.confidence_score >= min_confidence,
                    )
                )
                .order_by(DataLineage.created_at.desc())
            )
            records = result.scalars().all()

            if not records:
                if current_path:
                    paths.append(current_path)
                return

            for record in records:
                new_path = current_path + [record]
                if record.source_type and record.source_id:
                    await _trace(record.source_type, record.source_id, new_path, depth + 1)
                else:
                    paths.append(new_path)

        await _trace(DataLineageType.ASSET.value, asset_id, [], 0)
        return [self._build_path_dict(p) for p in paths]

    async def get_downstream_lineage(
        self,
        asset_id: str,
        max_depth: int = 5,
        min_confidence: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """获取下游血缘（数据去向）。"""
        paths: List[List[DataLineage]] = []
        visited: set = set()

        async def _trace(
            source_type: str,
            source_id: str,
            current_path: List[DataLineage],
            depth: int,
        ) -> None:
            if depth > max_depth or f"{source_type}:{source_id}" in visited:
                return
            visited.add(f"{source_type}:{source_id}")

            result = await self.db.execute(
                select(DataLineage)
                .where(
                    and_(
                        DataLineage.source_type == source_type,
                        DataLineage.source_id == source_id,
                        DataLineage.confidence_score >= min_confidence,
                    )
                )
                .order_by(DataLineage.created_at.desc())
            )
            records = result.scalars().all()

            if not records:
                if current_path:
                    paths.append(current_path)
                return

            for record in records:
                new_path = current_path + [record]
                await _trace(
                    record.current_entity_type,
                    record.current_entity_id,
                    new_path,
                    depth + 1,
                )

        await _trace(DataLineageType.ASSET.value, asset_id, [], 0)
        return [self._build_path_dict(p) for p in paths]

    async def get_lineage_graph(
        self,
        asset_id: str,
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """获取血缘图（用于可视化），边格式统一为 source/target。"""
        upstream = await self.get_upstream_lineage(asset_id, max_depth)
        downstream = await self.get_downstream_lineage(asset_id, max_depth)

        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        def _add_node(node_id: str, node_type: str, name: str = ""):
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "type": node_type,
                    "name": name or node_id,
                }

        def _process_paths(paths: List[Dict[str, Any]]):
            for path in paths:
                for node in path.get("nodes", []):
                    _add_node(node["id"], node.get("type", "unknown"), node.get("name", ""))
                for edge in path.get("edges", []):
                    edges.append(edge)

        _process_paths(upstream)
        _process_paths(downstream)

        center = f"asset:{asset_id}"
        _add_node(center, "asset", asset_id)

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "center_node": center,
        }

    async def get_impact_report(
        self,
        asset_id: str,
        max_depth: int = 5,
    ) -> Dict[str, Any]:
        """生成影响分析报告。"""
        downstream = await self.get_downstream_lineage(asset_id, max_depth)

        affected: Dict[str, Dict[str, Any]] = {}
        critical_paths = 0

        for path in downstream:
            confidence = path.get("total_confidence", 1.0)
            if confidence >= 0.8:
                critical_paths += 1

            for i, node in enumerate(path.get("nodes", [])):
                nid = node["id"]
                if nid not in affected:
                    affected[nid] = {
                        "entity_id": nid,
                        "entity_type": node.get("type", "unknown"),
                        "name": node.get("name", nid),
                        "distance": i + 1,
                    }

        total = len(affected)
        risk_score = self._calculate_risk_score(total, critical_paths, downstream)

        return {
            "source": f"asset:{asset_id}",
            "summary": {
                "total_affected": total,
                "critical_paths": critical_paths,
                "risk_score": risk_score,
                "risk_level": (
                    "high" if risk_score > 0.7 else "medium" if risk_score > 0.3 else "low"
                ),
            },
            "affected_entities": list(affected.values()),
        }

    async def verify_lineage_integrity(self, asset_id: str) -> bool:
        """
        验证血缘链完整性。
        无血缘记录视为通过；旧数据无 lineage_hash 视为通过。
        """
        result = await self.db.execute(
            select(DataLineage)
            .where(
                and_(
                    DataLineage.current_entity_type == DataLineageType.ASSET.value,
                    DataLineage.current_entity_id == asset_id,
                )
            )
            .order_by(DataLineage.step_index, DataLineage.created_at)
        )
        records = result.scalars().all()

        if not records:
            return True

        for i, record in enumerate(records):
            if not record.lineage_hash:
                continue
            metadata = record.extra_metadata if isinstance(record.extra_metadata, dict) else {}
            if metadata.get("hash_version") != LINEAGE_HASH_VERSION:
                continue

            parent_hashes = metadata.get("parent_hashes")
            if parent_hashes is None:
                parent_hashes = [record.parent_hash] if record.parent_hash else []

            record_step_index = record.step_index if isinstance(record.step_index, int) else i
            expected_hash = self._calculate_lineage_hash(
                source_type=record.source_type,
                source_id=record.source_id,
                current_entity_type=record.current_entity_type,
                current_entity_id=record.current_entity_id,
                relationship=record.relationship,
                transformation_logic=record.transformation_logic,
                parent_hashes=parent_hashes,
                step_index=record_step_index,
            )

            if record.lineage_hash != expected_hash:
                logger.error(
                    f"Lineage integrity check failed for {asset_id} at step {i}"
                )
                return False

        logger.info(f"Lineage integrity verified for {asset_id}")
        return True

    async def purge_old_lineage(self, days: int = 365, dry_run: bool = False) -> int:
        """清理旧血缘数据。"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(func.count(DataLineage.id)).where(DataLineage.created_at < cutoff)
        )
        count = result.scalar() or 0

        if not dry_run:
            await self.db.execute(
                text("DELETE FROM data_lineage WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            await self.db.commit()
            logger.info(f"Purged {count} old lineage records")

        return count

    # ========================================================================
    # 质量评估
    # ========================================================================

    async def assess_quality(
        self,
        asset_id: str,
        sample_data: Optional[List[Dict[str, Any]]] = None,
    ) -> QualityMetrics:
        """评估数据质量。"""
        asset = await self._get_asset(asset_id)

        if asset and asset.quality_overall_score and asset.quality_overall_score > 0:
            return QualityMetrics(
                completeness=asset.quality_completeness or 0.0,
                accuracy=asset.quality_accuracy or 0.0,
                timeliness=asset.quality_timeliness or 0.0,
                consistency=asset.quality_consistency or 0.0,
                uniqueness=asset.quality_uniqueness or 0.0,
            )

        if sample_data:
            return self._auto_assess(sample_data)

        return QualityMetrics(
            completeness=0.5,
            accuracy=0.5,
            timeliness=0.5,
            consistency=0.5,
            uniqueness=0.5,
        )

    async def update_quality_metrics(
        self,
        asset_id: str,
        metrics: QualityMetrics,
    ) -> None:
        """更新资产质量评分。"""
        asset = await self._get_asset(asset_id)
        if asset:
            asset.quality_completeness = metrics.completeness
            asset.quality_accuracy = metrics.accuracy
            asset.quality_timeliness = metrics.timeliness
            asset.quality_consistency = metrics.consistency
            asset.quality_uniqueness = metrics.uniqueness
            asset.quality_overall_score = metrics.overall_score
            await self.db.flush()
            logger.info(
                f"Updated quality metrics for {asset_id}: {metrics.overall_score:.3f}"
            )

    # ========================================================================
    # 定价
    # ========================================================================

    async def calculate_price(
        self,
        asset_id: str,
        rights_types: Optional[List[str]] = None,
        computation_method: Optional[str] = None,
        market_multiplier: float = 1.0,
    ) -> PricingResult:
        """
        计算资产公允价格。

        fair_value = base * quality * scarcity * lineage * rights * market * sensitivity + computation_cost
        """
        asset = await self._get_asset(asset_id)
        if not asset:
            raise ValueError(f"Data asset not found: {asset_id}")

        # 1. 基础价值
        base_value = self._calculate_base_value(asset)

        # 2. 质量乘数
        quality_multiplier = self._calculate_quality_multiplier(asset)

        # 3. 稀缺性乘数
        scarcity_multiplier = await self._calculate_scarcity_multiplier(asset)

        # 4. 血缘乘数
        lineage_multiplier = await self._calculate_lineage_multiplier(asset_id)

        # 5. 权益范围乘数
        rights_scope_multiplier = self._calculate_rights_scope_multiplier(rights_types)

        # 6. 市场乘数
        market_multiplier = max(0.1, market_multiplier)

        # 7. 敏感度折扣
        sensitivity_multiplier = self._calculate_sensitivity_multiplier(asset)

        # 8. 计算成本
        computation_cost = self._calculate_computation_cost(
            base_value, computation_method
        )

        factors = PricingFactors(
            base_value=base_value,
            quality_multiplier=quality_multiplier,
            scarcity_multiplier=scarcity_multiplier,
            lineage_multiplier=lineage_multiplier,
            rights_scope_multiplier=rights_scope_multiplier,
            market_multiplier=market_multiplier,
            sensitivity_multiplier=sensitivity_multiplier,
            computation_cost=computation_cost,
        )

        fair_value = (
            base_value
            * quality_multiplier
            * scarcity_multiplier
            * lineage_multiplier
            * rights_scope_multiplier
            * market_multiplier
            * sensitivity_multiplier
            + computation_cost
        )

        fair_value = max(0.0, fair_value)
        recommended = max(1.0, round(fair_value))

        return PricingResult(
            asset_id=asset_id,
            base_value=round(base_value, 2),
            fair_value=round(fair_value, 2),
            recommended_price=recommended,
            price_range_min=round(fair_value * 0.8, 2),
            price_range_max=round(fair_value * 1.3, 2),
            factors=factors,
            lineage_verified=await self.verify_lineage_integrity(asset_id),
            quality_score=asset.quality_overall_score or 0.0,
        )

    async def suggest_price_range(
        self,
        asset_id: str,
        rights_types: Optional[List[str]] = None,
        computation_method: Optional[str] = None,
    ) -> PriceRange:
        """建议价格区间。"""
        result = await self.calculate_price(asset_id, rights_types, computation_method)
        return PriceRange(
            min=result.price_range_min,
            recommended=result.recommended_price,
            max=result.price_range_max,
        )

    async def get_pricing_factors(
        self,
        asset_id: str,
    ) -> PricingFactors:
        """获取定价因子（不计算完整价格）。"""
        result = await self.calculate_price(asset_id)
        return result.factors

    # ========================================================================
    # 内部辅助方法
    # ========================================================================

    def _entity_type_value(self, entity_type: DataLineageType | str) -> str:
        if isinstance(entity_type, DataLineageType):
            return entity_type.value
        return str(entity_type)

    def _calculate_lineage_hash(
        self,
        *,
        source_type: str,
        source_id: str,
        current_entity_type: str,
        current_entity_id: str,
        relationship: Optional[str],
        transformation_logic: Optional[str],
        parent_hashes: List[str],
        step_index: int,
    ) -> str:
        normalized_parent_hashes = [
            value for value in (parent_hashes or []) if isinstance(value, str) and value
        ]
        payload = {
            "version": LINEAGE_HASH_VERSION,
            "source_type": source_type if isinstance(source_type, str) and source_type else "unknown",
            "source_id": source_id if isinstance(source_id, str) else "",
            "current_entity_type": current_entity_type if isinstance(current_entity_type, str) else "",
            "current_entity_id": current_entity_id if isinstance(current_entity_id, str) else "",
            "relationship": relationship if isinstance(relationship, str) else "",
            "transformation_logic": transformation_logic if isinstance(transformation_logic, str) else "",
            "parent_hashes": sorted(normalized_parent_hashes),
            "step_index": step_index,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def _get_parent_hashes(self, source_type: str, source_id: str) -> List[str]:
        if not source_type or source_type == "unknown" or not source_id:
            return []

        result = await self.db.execute(
            select(DataLineage.lineage_hash)
            .where(
                and_(
                    DataLineage.current_entity_type == source_type,
                    DataLineage.current_entity_id == source_id,
                    DataLineage.lineage_hash.isnot(None),
                )
            )
            .order_by(DataLineage.step_index.desc(), DataLineage.created_at.desc())
            .limit(1)
        )
        lineage_hash = result.scalar_one_or_none()
        return [lineage_hash] if isinstance(lineage_hash, str) and lineage_hash else []

    async def _get_next_step_index(self, entity_type: str, entity_id: str) -> int:
        result = await self.db.execute(
            select(func.max(DataLineage.step_index)).where(
                and_(
                    DataLineage.current_entity_type == entity_type,
                    DataLineage.current_entity_id == entity_id,
                )
            )
        )
        current_max = result.scalar_one_or_none()
        return int(current_max) + 1 if isinstance(current_max, int) else 0

    async def _get_asset(self, asset_id: str) -> Optional[DataAssets]:
        result = await self.db.execute(
            select(DataAssets).where(DataAssets.asset_id == asset_id)
        )
        return result.scalar_one_or_none()

    def _build_path_dict(self, records: List[DataLineage]) -> Dict[str, Any]:
        """从血缘记录构建路径字典。"""
        nodes = []
        edges = []
        total_confidence = 1.0

        for record in records:
            target_id = f"{record.current_entity_type}:{record.current_entity_id}"
            nodes.append({
                "id": target_id,
                "type": record.current_entity_type,
                "name": record.current_entity_id,
            })

            if record.source_type and record.source_id:
                source_id = f"{record.source_type}:{record.source_id}"
                nodes.append({
                    "id": source_id,
                    "type": record.source_type,
                    "name": record.source_id,
                })
                edges.append({
                    "source": source_id,
                    "target": target_id,
                    "relationship": record.relationship or "derived",
                })

            total_confidence *= record.confidence_score or 1.0

        # 去重节点
        seen = set()
        unique_nodes = []
        for n in nodes:
            if n["id"] not in seen:
                seen.add(n["id"])
                unique_nodes.append(n)

        return {
            "nodes": unique_nodes,
            "edges": edges,
            "total_confidence": round(total_confidence, 4),
        }

    def _calculate_risk_score(
        self,
        affected_count: int,
        critical_count: int,
        paths: List[Dict[str, Any]],
    ) -> float:
        count_score = min(affected_count / 100, 1.0) * 0.3
        critical_score = min(critical_count / 10, 1.0) * 0.4
        if paths:
            avg_conf = sum(p.get("total_confidence", 1.0) for p in paths) / len(paths)
            confidence_score = (1 - avg_conf) * 0.3
        else:
            confidence_score = 0.0
        return min(count_score + critical_score + confidence_score, 1.0)

    def _calculate_base_value(self, asset: DataAssets) -> float:
        base_price = BASE_PRICE_BY_TYPE.get(asset.data_type, BASE_PRICE_BY_TYPE["generic"])

        if asset.record_count and asset.record_count > 0:
            volume_factor = min(2.0, 1.0 + (asset.record_count / 100000))
        else:
            volume_factor = 1.0

        if asset.data_size_bytes and asset.data_size_bytes > 0:
            size_gb = asset.data_size_bytes / (1024 ** 3)
            size_factor = min(1.5, 1.0 + (size_gb / 10))
        else:
            size_factor = 1.0

        return base_price * volume_factor * size_factor

    def _calculate_quality_multiplier(self, asset: DataAssets) -> float:
        if asset.quality_overall_score and asset.quality_overall_score > 0:
            quality_score = asset.quality_overall_score
        else:
            quality_score = (
                (asset.quality_completeness or 0.0) * 0.25
                + (asset.quality_accuracy or 0.0) * 0.30
                + (asset.quality_timeliness or 0.0) * 0.20
                + (asset.quality_consistency or 0.0) * 0.15
                + (asset.quality_uniqueness or 0.0) * 0.10
            )
        return 0.5 + (quality_score * 1.5)

    async def _calculate_scarcity_multiplier(self, asset: DataAssets) -> float:
        result = await self.db.execute(
            select(func.count(DataAssets.id)).where(
                and_(
                    DataAssets.data_type == asset.data_type,
                    DataAssets.is_active == True,
                    DataAssets.is_available_for_trade == True,
                )
            )
        )
        similar_count = result.scalar() or 0
        # 同类资产越少，稀缺性越高
        if similar_count <= 1:
            return 2.0
        elif similar_count <= 5:
            return 1.5
        elif similar_count <= 20:
            return 1.2
        else:
            return 1.0

    async def _calculate_lineage_multiplier(self, asset_id: str) -> float:
        lineage_verified = await self.verify_lineage_integrity(asset_id)
        if not lineage_verified:
            return 0.7

        # 检查上游深度和置信度
        upstream = await self.get_upstream_lineage(asset_id, max_depth=3)
        max_depth_found = 0
        min_confidence = 1.0

        for path in upstream:
            depth = len(path.get("nodes", []))
            if depth > max_depth_found:
                max_depth_found = depth
            conf = path.get("total_confidence", 1.0)
            if conf < min_confidence:
                min_confidence = conf

        if max_depth_found >= 3 and min_confidence >= 0.8:
            return 1.05

        # 无血缘时走安全 fallback
        if max_depth_found == 0:
            return 0.9

        return 1.0

    async def get_lineage_statistics(
        self, space_id: Optional[str] = None, days: int = 30
    ) -> Dict[str, Any]:
        """获取血缘统计信息。"""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        query = select(func.count(DataLineage.id)).where(
            DataLineage.created_at >= since
        )
        if space_id:
            query = query.where(DataLineage.space_id == space_id)
        result = await self.db.execute(query)
        total = result.scalar() or 0

        type_query = (
            select(DataLineage.current_entity_type, func.count(DataLineage.id))
            .where(DataLineage.created_at >= since)
            .group_by(DataLineage.current_entity_type)
        )
        if space_id:
            type_query = type_query.where(DataLineage.space_id == space_id)
        type_result = await self.db.execute(type_query)
        by_type = {row[0]: row[1] for row in type_result.all()}

        return {
            "total_records": total,
            "entities_by_type": by_type,
            "period_days": days,
            "space_id": space_id,
        }

    def _calculate_rights_scope_multiplier(
        self, rights_types: Optional[List[str]]
    ) -> float:
        multiplier = 1.0
        if not rights_types:
            rights_types = ["view", "download", "derivative_right", "sub_license_right"]

        for rt in rights_types:
            enum_val = RIGHTS_TYPE_ALIASES.get(rt.lower())
            if enum_val:
                multiplier += RIGHTS_VALUE_MULTIPLIERS.get(enum_val, 0.1)
            else:
                multiplier += 0.1

        return multiplier

    def _calculate_sensitivity_multiplier(self, asset: DataAssets) -> float:
        level = asset.sensitivity_level
        if level is None:
            return 0.9
        return SENSITIVITY_DISCOUNTS.get(level, 0.7)

    def _calculate_computation_cost(
        self, base_value: float, computation_method: Optional[str]
    ) -> float:
        if not computation_method:
            computation_method = "raw_data"

        method = COMPUTATION_METHOD_ALIASES.get(computation_method.lower())
        if not method:
            method = ComputationMethod.RAW_DATA

        factor = COMPUTATION_COST_FACTORS.get(method, 0.0)
        return base_value * factor

    def _auto_assess(self, data: List[Dict[str, Any]]) -> QualityMetrics:
        if not data:
            return QualityMetrics(0, 0, 0, 0, 0)

        completeness = self._assess_completeness(data)
        accuracy = 0.8
        timeliness = 0.9
        consistency = self._assess_consistency(data)
        uniqueness = self._assess_uniqueness(data)

        return QualityMetrics(
            completeness=completeness,
            accuracy=accuracy,
            timeliness=timeliness,
            consistency=consistency,
            uniqueness=uniqueness,
        )

    def _assess_completeness(self, data: List[Dict[str, Any]]) -> float:
        if not data:
            return 0.0
        total_fields = 0
        non_null_fields = 0
        for record in data:
            for value in record.values():
                total_fields += 1
                if value is not None and value != "":
                    non_null_fields += 1
        return non_null_fields / total_fields if total_fields > 0 else 0.0

    def _assess_consistency(self, data: List[Dict[str, Any]]) -> float:
        if not data or len(data) < 2:
            return 1.0
        first_keys = set(data[0].keys())
        consistent_count = sum(
            1 for record in data if set(record.keys()) == first_keys
        )
        return consistent_count / len(data)

    def _assess_uniqueness(self, data: List[Dict[str, Any]]) -> float:
        if not data:
            return 0.0
        seen = set()
        duplicates = 0
        for record in data:
            record_hash = hashlib.sha256(
                json.dumps(record, sort_keys=True).encode()
            ).hexdigest()
            if record_hash in seen:
                duplicates += 1
            seen.add(record_hash)
        return 1.0 - (duplicates / len(data))
