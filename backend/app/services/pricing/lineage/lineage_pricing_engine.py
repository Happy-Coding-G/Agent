"""
Lineage Pricing Engine - 血缘驱动定价引擎

将数据血缘特征纳入定价模型：
1. 血缘完整性评分
2. 质量传播分析
3. 风险传导评估
4. 溯源可信度计算
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime
import numpy as np
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.services.trade.data_lineage_tracker import DataLineageTracker
from app.db.models import DataAssets, DataRightsTransactions

logger = logging.getLogger(__name__)


class LineageQualityGrade(Enum):
    """血缘质量等级"""
    EXCELLENT = "A"  # 完整血缘，高质量上游
    GOOD = "B"       # 较完整，质量良好
    FAIR = "C"       # 部分缺失，质量一般
    POOR = "D"       # 严重缺失或低质量


@dataclass
class LineageNodeMetrics:
    """血缘节点指标"""
    node_id: str
    node_type: str  # raw, processed, derived
    quality_score: float  # 0-1
    depth: int  # 距离根节点的深度
    reliability: float  # 节点可信度
    verification_status: str  # verified, unverified, suspicious


@dataclass
class LineagePathMetrics:
    """血缘路径指标"""
    path_id: str
    source_nodes: List[str]  # 源头节点
    sink_nodes: List[str]    # 汇聚节点
    path_length: int
    min_quality: float  # 路径上最低质量
    avg_quality: float
    bottleneck_nodes: List[str]  # 质量瓶颈节点


@dataclass
class LineagePricingFeatures:
    """
    血缘定价特征

    综合评估数据资产的血缘价值、风险和稀缺性
    """
    # 完整性特征
    lineage_depth: int = 0
    lineage_breadth: int = 0
    lineage_completeness: float = 0.0  # [0,1]
    lineage_coverage_ratio: float = 0.0  # 实际血缘/期望血缘

    # 质量传播特征
    upstream_quality_score: float = 0.5  # 上游整体质量
    quality_degradation_rate: float = 0.0  # 质量衰减率
    processing_quality_loss: float = 0.0  # 处理过程损失
    overall_lineage_quality: float = 0.5  # 综合血缘质量

    # 溯源特征
    data_provenance_score: float = 0.5  # 数据溯源可信度
    verification_coverage: float = 0.0  # 验证覆盖度
    audit_trail_completeness: float = 0.0  # 审计链完整度

    # 风险特征
    upstream_risk_score: float = 0.0  # 上游风险
    single_point_failure_risk: float = 0.0  # 单点故障风险
    dependency_concentration: float = 0.0  # 依赖集中度
    alternative_source_availability: float = 0.0  # 替代源可用性

    # 价值特征
    derivation_complexity: float = 0.0  # 派生复杂度 (处理步骤数/深度)
    lineage_uniqueness: float = 0.5  # 血缘路径独特性
    data_freshness_score: float = 0.5  # 数据新鲜度
    historical_stability: float = 0.5  # 历史稳定性

    # 元数据
    feature_confidence: float = 0.7  # 特征置信度
    assessment_timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_vector(self) -> np.ndarray:
        """转换为特征向量"""
        return np.array([
            self.lineage_completeness,
            self.upstream_quality_score,
            self.quality_degradation_rate,
            self.data_provenance_score,
            self.upstream_risk_score,
            self.single_point_failure_risk,
            self.derivation_complexity,
            self.lineage_uniqueness,
            self.alternative_source_availability,
            self.overall_lineage_quality,
        ], dtype=np.float32)

    @property
    def quality_grade(self) -> LineageQualityGrade:
        """计算质量等级"""
        if self.overall_lineage_quality >= 0.85:
            return LineageQualityGrade.EXCELLENT
        elif self.overall_lineage_quality >= 0.70:
            return LineageQualityGrade.GOOD
        elif self.overall_lineage_quality >= 0.50:
            return LineageQualityGrade.FAIR
        else:
            return LineageQualityGrade.POOR


class QualityPropagationModel:
    """
    质量传播模型

    模拟质量在血缘链中的传播和衰减
    """

    def __init__(self, decay_factor: float = 0.95):
        """
        Args:
            decay_factor: 每跳质量衰减因子
        """
        self.decay_factor = decay_factor

    def calculate_propagated_quality(
        self,
        source_quality: float,
        hops: int,
        processing_loss: float = 0.0,
    ) -> float:
        """
        计算传播后的质量

        Q_final = Q_source * (decay ^ hops) * (1 - processing_loss)
        """
        propagated = source_quality * (self.decay_factor ** hops)
        final = propagated * (1 - processing_loss)
        return max(0.0, min(1.0, final))

    def analyze_quality_propagation_path(
        self,
        lineage_path: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        分析质量在血缘路径中的传播

        Returns:
            {
                "final_quality": float,
                "bottleneck_nodes": List[str],
                "improvement_suggestions": List[str],
            }
        """
        current_quality = 1.0
        bottlenecks = []

        for i, node in enumerate(lineage_path):
            node_quality = node.get("quality_score", 0.5)
            processing_loss = node.get("processing_loss", 0.0)

            # 计算到当前节点的质量
            current_quality = self.calculate_propagated_quality(
                current_quality,
                hops=1,
                processing_loss=processing_loss,
            )

            # 如果当前节点质量显著低于传播质量，记录为瓶颈
            if node_quality < current_quality * 0.8:
                bottlenecks.append({
                    "node_id": node.get("id"),
                    "quality_gap": current_quality - node_quality,
                })

            # 更新当前质量为两者较小值
            current_quality = min(current_quality, node_quality)

        suggestions = self._generate_improvement_suggestions(bottlenecks)

        return {
            "final_quality": current_quality,
            "bottleneck_nodes": bottlenecks,
            "improvement_suggestions": suggestions,
        }

    def _generate_improvement_suggestions(
        self,
        bottlenecks: List[Dict],
    ) -> List[str]:
        """生成质量改进建议"""
        suggestions = []

        for bottleneck in bottlenecks:
            gap = bottleneck.get("quality_gap", 0)
            if gap > 0.3:
                suggestions.append(
                    f"节点 {bottleneck['node_id']} 质量严重不足，"
                    f"建议优先修复 (差距: {gap:.2f})"
                )
            elif gap > 0.15:
                suggestions.append(
                    f"节点 {bottleneck['node_id']} 质量有改进空间 "
                    f"(差距: {gap:.2f})"
                )

        return suggestions


class RiskAssessmentModel:
    """
    风险评估模型

    评估数据资产的依赖风险和供应链风险
    """

    def assess_dependency_risk(
        self,
        lineage_tree: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        评估依赖风险

        Returns:
            {
                "overall_risk": float,  # 综合风险
                "availability_risk": float,  # 可用性风险
                "integrity_risk": float,  # 完整性风险
                "compliance_risk": float,  # 合规风险
            }
        """
        nodes = lineage_tree.get("nodes", [])
        edges = lineage_tree.get("edges", [])

        # 1. 可用性风险 - 单点故障分析
        critical_nodes = self._identify_critical_nodes(nodes, edges)
        availability_risk = len(critical_nodes) / max(len(nodes), 1)

        # 2. 完整性风险 - 未验证节点比例
        unverified_ratio = sum(
            1 for n in nodes
            if n.get("verification_status") != "verified"
        ) / max(len(nodes), 1)
        integrity_risk = unverified_ratio

        # 3. 合规风险 - 敏感数据处理
        sensitive_nodes = [
            n for n in nodes
            if n.get("sensitivity_level") in ["high", "critical"]
        ]
        compliance_risk = len(sensitive_nodes) / max(len(nodes), 1)

        # 综合风险 (加权)
        overall_risk = (
            availability_risk * 0.4 +
            integrity_risk * 0.35 +
            compliance_risk * 0.25
        )

        return {
            "overall_risk": overall_risk,
            "availability_risk": availability_risk,
            "integrity_risk": integrity_risk,
            "compliance_risk": compliance_risk,
            "critical_nodes": [n.get("id") for n in critical_nodes],
        }

    def _identify_critical_nodes(
        self,
        nodes: List[Dict],
        edges: List[Dict],
    ) -> List[Dict]:
        """识别关键节点（单点故障）"""
        # 计算每个节点的出度（下游依赖数）
        out_degree = {}
        for edge in edges:
            src = edge.get("source")
            out_degree[src] = out_degree.get(src, 0) + 1

        # 出度高的节点是关键节点
        threshold = np.percentile(list(out_degree.values()) or [0], 75)
        critical = [
            node for node in nodes
            if out_degree.get(node.get("id"), 0) > threshold
        ]

        return critical

    def calculate_scarcity_index(
        self,
        asset_id: str,
        alternative_sources: List[Dict],
    ) -> float:
        """
        计算稀缺性指数

        基于替代数据源的数量和质量
        """
        if not alternative_sources:
            return 1.0  # 完全稀缺

        # 考虑替代源数量
        count_factor = 1 / (1 + len(alternative_sources) * 0.5)

        # 考虑替代源质量
        avg_quality = np.mean([
            s.get("quality_score", 0.5)
            for s in alternative_sources
        ])
        quality_factor = 1 - avg_quality

        # 综合稀缺性
        scarcity = (count_factor * 0.6 + quality_factor * 0.4)

        return min(1.0, scarcity)


class LineagePricingEngine:
    """
    血缘驱动定价引擎

    整合血缘分析、质量传播、风险评估，生成定价特征
    """

    def __init__(
        self,
        db: AsyncSession,
        lineage_tracker: Optional[DataLineageTracker] = None,
    ):
        self.db = db
        self.lineage_tracker = lineage_tracker or DataLineageTracker(db)
        self.quality_model = QualityPropagationModel()
        self.risk_model = RiskAssessmentModel()

    async def analyze_lineage_for_pricing(
        self,
        asset_id: str,
        depth: int = 3,
    ) -> LineagePricingFeatures:
        """
        分析资产血缘并生成定价特征

        Args:
            asset_id: 资产ID
            depth: 血缘分析深度

        Returns:
            LineagePricingFeatures
        """
        try:
            # 1. 获取血缘树
            lineage_tree = await self.lineage_tracker.get_lineage_tree(
                asset_id, max_depth=depth
            )

            if not lineage_tree:
                logger.warning(f"No lineage data for asset {asset_id}")
                return self._default_features()

            # 2. 分析血缘结构
            structure_metrics = self._analyze_structure(lineage_tree)

            # 3. 质量传播分析
            quality_metrics = self._analyze_quality_propagation(lineage_tree)

            # 4. 风险评估
            risk_metrics = self.risk_model.assess_dependency_risk(lineage_tree)

            # 5. 稀缺性分析
            scarcity_metrics = await self._analyze_scarcity(asset_id, lineage_tree)

            # 6. 溯源可信度
            provenance_metrics = self._analyze_provenance(lineage_tree)

            # 7. 构建特征
            features = LineagePricingFeatures(
                lineage_depth=structure_metrics["depth"],
                lineage_breadth=structure_metrics["breadth"],
                lineage_completeness=structure_metrics["completeness"],
                lineage_coverage_ratio=structure_metrics["coverage"],

                upstream_quality_score=quality_metrics["upstream_quality"],
                quality_degradation_rate=quality_metrics["degradation_rate"],
                processing_quality_loss=quality_metrics["processing_loss"],
                overall_lineage_quality=quality_metrics["overall_quality"],

                data_provenance_score=provenance_metrics["score"],
                verification_coverage=provenance_metrics["verification_coverage"],
                audit_trail_completeness=provenance_metrics["audit_completeness"],

                upstream_risk_score=risk_metrics["overall_risk"],
                single_point_failure_risk=risk_metrics["availability_risk"],
                dependency_concentration=risk_metrics.get("concentration", 0.5),
                alternative_source_availability=scarcity_metrics["alternative_availability"],

                derivation_complexity=structure_metrics["complexity"],
                lineage_uniqueness=scarcity_metrics["uniqueness"],
                data_freshness_score=quality_metrics.get("freshness", 0.5),
                historical_stability=provenance_metrics.get("stability", 0.5),

                feature_confidence=self._calculate_confidence(lineage_tree),
            )

            return features

        except Exception as e:
            logger.exception(f"Failed to analyze lineage for {asset_id}: {e}")
            return self._default_features()

    def _analyze_structure(self, lineage_tree: Dict) -> Dict[str, Any]:
        """分析血缘结构"""
        nodes = lineage_tree.get("nodes", [])
        edges = lineage_tree.get("edges", [])

        if not nodes:
            return {
                "depth": 0, "breadth": 0,
                "completeness": 0, "coverage": 0,
                "complexity": 0,
            }

        # 计算深度（最长路径）
        depths = self._calculate_node_depths(nodes, edges)
        max_depth = max(depths.values()) if depths else 0

        # 计算宽度（每层的最大节点数）
        level_counts = {}
        for node_id, depth in depths.items():
            level_counts[depth] = level_counts.get(depth, 0) + 1
        max_breadth = max(level_counts.values()) if level_counts else 0

        # 完整性评估
        expected_nodes = self._estimate_expected_nodes(max_depth)
        completeness = len(nodes) / max(expected_nodes, 1)

        # 派生复杂度
        processing_steps = len([
            n for n in nodes
            if n.get("type") in ["processed", "derived"]
        ])
        complexity = processing_steps / max_depth if max_depth > 0 else 0

        return {
            "depth": max_depth,
            "breadth": max_breadth,
            "completeness": min(1.0, completeness),
            "coverage": min(1.0, completeness),
            "complexity": min(1.0, complexity),
        }

    def _calculate_node_depths(
        self,
        nodes: List[Dict],
        edges: List[Dict],
    ) -> Dict[str, int]:
        """计算每个节点在血缘树中的深度"""
        # 构建邻接表
        adj = {}
        for edge in edges:
            src = edge.get("source")
            dst = edge.get("target")
            if src not in adj:
                adj[src] = []
            adj[src].append(dst)

        # BFS计算深度
        depths = {}

        # 找到根节点（没有入边的节点）
        all_targets = set(edge.get("target") for edge in edges)
        roots = [
            n.get("id") for n in nodes
            if n.get("id") not in all_targets
        ]

        for root in roots:
            depths[root] = 0
            queue = [root]

            while queue:
                current = queue.pop(0)
                current_depth = depths.get(current, 0)

                for neighbor in adj.get(current, []):
                    if neighbor not in depths:
                        depths[neighbor] = current_depth + 1
                        queue.append(neighbor)

        return depths

    def _estimate_expected_nodes(self, depth: int) -> int:
        """估计给定深度下预期的节点数"""
        # 假设每级平均分支因子为2
        if depth == 0:
            return 1
        return 2 ** (depth + 1) - 1

    def _analyze_quality_propagation(
        self,
        lineage_tree: Dict,
    ) -> Dict[str, float]:
        """分析质量传播"""
        nodes = lineage_tree.get("nodes", [])

        if not nodes:
            return {
                "upstream_quality": 0.5,
                "degradation_rate": 0.0,
                "processing_loss": 0.0,
                "overall_quality": 0.5,
            }

        # 上游节点质量（深度较浅的节点）
        upstream_nodes = [
            n for n in nodes
            if n.get("depth", 999) <= 1
        ]
        upstream_quality = np.mean([
            n.get("quality_score", 0.5)
            for n in upstream_nodes
        ]) if upstream_nodes else 0.5

        # 处理步骤损失
        processing_nodes = [
            n for n in nodes
            if n.get("type") in ["processed", "derived"]
        ]
        processing_loss = np.mean([
            n.get("processing_loss", 0.0)
            for n in processing_nodes
        ]) if processing_nodes else 0.0

        # 整体质量（加权平均，深度越浅权重越高）
        total_weight = 0
        weighted_quality = 0
        for node in nodes:
            depth = node.get("depth", 0)
            weight = 1.0 / (1 + depth)  # 深度越大权重越小
            quality = node.get("quality_score", 0.5)
            weighted_quality += weight * quality
            total_weight += weight

        overall_quality = weighted_quality / total_weight if total_weight > 0 else 0.5

        # 质量衰减率
        quality_scores = [
            n.get("quality_score", 0.5) for n in nodes
        ]
        if len(quality_scores) > 1:
            degradation = max(0, quality_scores[0] - np.mean(quality_scores[1:]))
        else:
            degradation = 0.0

        return {
            "upstream_quality": upstream_quality,
            "degradation_rate": degradation,
            "processing_loss": processing_loss,
            "overall_quality": overall_quality,
        }

    async def _analyze_scarcity(
        self,
        asset_id: str,
        lineage_tree: Dict,
    ) -> Dict[str, Any]:
        """分析稀缺性"""
        # 查询替代数据源
        alternative_sources = await self._find_alternative_sources(asset_id)

        # 计算稀缺性指数
        scarcity = self.risk_model.calculate_scarcity_index(
            asset_id, alternative_sources
        )

        # 血缘独特性（路径越独特越稀缺）
        nodes = lineage_tree.get("nodes", [])
        unique_paths = len(set(
            n.get("data_source") for n in nodes
            if n.get("data_source")
        ))
        uniqueness = min(1.0, unique_paths / max(len(nodes), 1))

        return {
            "scarcity_index": scarcity,
            "alternative_availability": 1 - scarcity,
            "uniqueness": uniqueness,
            "alternative_count": len(alternative_sources),
        }

    async def _find_alternative_sources(
        self,
        asset_id: str,
    ) -> List[Dict]:
        """查找替代数据源"""
        # 查询同类型的其他资产
        stmt = select(DataAssets).where(
            DataAssets.asset_id != asset_id,
            DataAssets.is_active == True,
        )

        result = await self.db.execute(stmt)
        alternatives = result.scalars().all()

        return [
            {
                "asset_id": alt.asset_id,
                "quality_score": alt.quality_overall_score,
                "similarity": 0.5,  # 简化处理
            }
            for alt in alternatives[:10]  # 限制数量
        ]

    def _analyze_provenance(self, lineage_tree: Dict) -> Dict[str, float]:
        """分析溯源可信度"""
        nodes = lineage_tree.get("nodes", [])

        if not nodes:
            return {
                "score": 0.5,
                "verification_coverage": 0.0,
                "audit_completeness": 0.0,
            }

        # 验证覆盖度
        verified_count = sum(
            1 for n in nodes
            if n.get("verification_status") == "verified"
        )
        verification_coverage = verified_count / len(nodes)

        # 审计链完整度
        audited_count = sum(
            1 for n in nodes
            if n.get("audit_trail") is not None
        )
        audit_completeness = audited_count / len(nodes)

        # 综合溯源分数
        score = (
            verification_coverage * 0.5 +
            audit_completeness * 0.3 +
            0.2  # 基础分
        )

        return {
            "score": score,
            "verification_coverage": verification_coverage,
            "audit_completeness": audit_completeness,
        }

    def _calculate_confidence(self, lineage_tree: Dict) -> float:
        """计算特征置信度"""
        nodes = lineage_tree.get("nodes", [])

        if not nodes:
            return 0.3  # 低置信度

        # 节点数量越多置信度越高
        count_factor = min(1.0, len(nodes) / 10)

        # 验证状态越好置信度越高
        verified_ratio = sum(
            1 for n in nodes
            if n.get("verification_status") == "verified"
        ) / len(nodes)

        confidence = 0.4 * count_factor + 0.6 * verified_ratio
        return min(1.0, confidence)

    def _default_features(self) -> LineagePricingFeatures:
        """返回默认特征（当血缘数据不可用时）"""
        return LineagePricingFeatures(
            lineage_completeness=0.3,
            upstream_quality_score=0.5,
            overall_lineage_quality=0.4,
            feature_confidence=0.3,
        )

    def calculate_price_adjustment(
        self,
        features: LineagePricingFeatures,
    ) -> Dict[str, float]:
        """
        基于血缘特征计算价格调整

        Returns:
            {
                "adjustment_factor": float,  # 调整因子 (0.5 - 2.0)
                "quality_premium": float,    # 质量溢价
                "scarcity_premium": float,   # 稀缺性溢价
                "risk_discount": float,      # 风险折价
                "reasoning": str,            # 调整理由
            }
        """
        adjustments = []

        # 1. 质量调整
        quality = features.overall_lineage_quality
        if quality >= 0.9:
            quality_adj = 0.15  # 15%溢价
            adjustments.append("卓越血缘质量")
        elif quality >= 0.75:
            quality_adj = 0.08
            adjustments.append("良好血缘质量")
        elif quality >= 0.5:
            quality_adj = 0.0
        else:
            quality_adj = -0.15
            adjustments.append("血缘质量不足")

        # 2. 稀缺性调整
        scarcity = 1 - features.alternative_source_availability
        scarcity_adj = scarcity * 0.2  # 最高20%稀缺性溢价
        if scarcity > 0.7:
            adjustments.append("高度稀缺")

        # 3. 风险调整
        risk = features.upstream_risk_score
        risk_adj = -risk * 0.25  # 最高25%风险折价
        if risk > 0.6:
            adjustments.append("高风险折价")

        # 4. 复杂度调整
        complexity = features.derivation_complexity
        complexity_adj = complexity * 0.1  # 处理复杂度溢价

        # 综合调整
        total_adj = quality_adj + scarcity_adj + risk_adj + complexity_adj

        # 限制调整范围
        adjustment_factor = 1 + max(-0.4, min(0.4, total_adj))

        reasoning = "; ".join(adjustments) if adjustments else "标准定价"

        return {
            "adjustment_factor": adjustment_factor,
            "quality_premium": quality_adj,
            "scarcity_premium": scarcity_adj,
            "risk_discount": risk_adj,
            "complexity_premium": complexity_adj,
            "reasoning": reasoning,
        }
