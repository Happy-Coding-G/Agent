"""
DataLineageSkill - 数据血缘追踪Skill

提供数据血缘查询、质量评估、影响分析等能力。
无状态、只读的Skill，可被多个Agent复用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.data_lineage_tracker import (
    DataLineageTracker,
    DataQualityAssessor,
)
from app.services.trade.data_rights_events import QualityMetrics

logger = logging.getLogger(__name__)


@dataclass
class LineageSummary:
    """血缘摘要"""
    asset_id: str
    node_count: int
    root_hash: Optional[str]
    integrity_verified: bool
    quality_score: float
    data_source: str
    processing_steps: List[str]


@dataclass
class ImpactAnalysis:
    """影响分析结果"""
    asset_id: str
    upstream_count: int
    downstream_count: int
    total_impact_score: float
    risk_level: str  # low, medium, high
    affected_assets: List[Dict[str, Any]]


@dataclass
class QualityAssessment:
    """质量评估结果"""
    asset_id: str
    overall_score: float
    completeness: float
    accuracy: float
    timeliness: float
    consistency: float
    uniqueness: float
    assessment_method: str  # manual, auto, mixed
    recommendations: List[str]


class DataLineageSkill:
    """
    数据血缘追踪Skill

    职责：
    1. 查询数据血缘树和依赖关系
    2. 评估数据质量
    3. 分析变更影响范围
    4. 验证数据完整性

    使用示例：
        skill = DataLineageSkill(db)

        # 获取血缘摘要
        summary = await skill.get_lineage_summary(asset_id)

        # 评估质量
        quality = await skill.assess_quality(asset_id, sample_data)

        # 影响分析
        impact = await skill.analyze_impact(asset_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.tracker = DataLineageTracker(db)
        self.assessor = DataQualityAssessor(db)

    # ========================================================================
    # 血缘查询API
    # ========================================================================

    async def get_lineage_summary(self, asset_id: str) -> LineageSummary:
        """
        获取数据血缘摘要

        快速了解资产的来源和处理历程。
        """
        try:
            # 获取血缘树
            tree = await self.tracker.get_lineage_tree(asset_id)

            # 验证完整性
            integrity = await self.tracker.verify_lineage_integrity(asset_id)

            # 获取上游依赖
            upstream = await self.tracker.get_upstream_dependencies(asset_id)
            data_source = upstream[0]["source"] if upstream else "unknown"

            # 提取处理步骤
            steps = []
            for node in tree.get("nodes", []):
                if node.get("type") != "raw":
                    steps.append(f"{node['type']}: {node['id']}")

            return LineageSummary(
                asset_id=asset_id,
                node_count=tree.get("node_count", 0),
                root_hash=tree.get("root_hash"),
                integrity_verified=integrity,
                quality_score=0.0,  # 需单独查询
                data_source=data_source,
                processing_steps=steps,
            )

        except Exception as e:
            logger.error(f"Failed to get lineage summary for {asset_id}: {e}")
            return LineageSummary(
                asset_id=asset_id,
                node_count=0,
                root_hash=None,
                integrity_verified=False,
                quality_score=0.0,
                data_source="unknown",
                processing_steps=[],
            )

    async def get_lineage_graph(self, asset_id: str) -> Dict[str, Any]:
        """
        获取血缘图数据（用于可视化）

        Returns:
            {
                "nodes": [{"id": str, "type": str, "quality": dict}],
                "edges": [{"from": str, "to": str, "label": str}],
                "metadata": {"root_hash": str, "verified": bool}
            }
        """
        try:
            tree = await self.tracker.get_lineage_tree(asset_id)
            integrity = await self.tracker.verify_lineage_integrity(asset_id)

            return {
                **tree,
                "metadata": {
                    "verified": integrity,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        except Exception as e:
            logger.error(f"Failed to get lineage graph for {asset_id}: {e}")
            return {
                "asset_id": asset_id,
                "nodes": [],
                "edges": [],
                "metadata": {"error": str(e)},
            }

    async def get_upstream(self, asset_id: str) -> List[Dict[str, Any]]:
        """
        获取上游依赖（数据来源）
        """
        try:
            return await self.tracker.get_upstream_dependencies(asset_id)
        except Exception as e:
            logger.error(f"Failed to get upstream for {asset_id}: {e}")
            return []

    async def get_downstream(self, asset_id: str) -> List[Dict[str, Any]]:
        """
        获取下游影响（哪些资产依赖此数据）
        """
        try:
            return await self.tracker.get_downstream_impact(asset_id)
        except Exception as e:
            logger.error(f"Failed to get downstream for {asset_id}: {e}")
            return []

    # ========================================================================
    # 质量评估API
    # ========================================================================

    async def assess_quality(
        self,
        asset_id: str,
        sample_data: Optional[List[Dict]] = None,
    ) -> QualityAssessment:
        """
        评估数据质量

        多维度质量评分和改进建议。
        """
        try:
            # 获取质量指标
            metrics = await self.assessor.assess_quality(asset_id, sample_data)

            # 判断评估方式
            assessment_method = "manual" if not sample_data else "auto"

            # 生成改进建议
            recommendations = self._generate_quality_recommendations(metrics)

            return QualityAssessment(
                asset_id=asset_id,
                overall_score=metrics.overall_score,
                completeness=metrics.completeness,
                accuracy=metrics.accuracy,
                timeliness=metrics.timeliness,
                consistency=metrics.consistency,
                uniqueness=metrics.uniqueness,
                assessment_method=assessment_method,
                recommendations=recommendations,
            )

        except Exception as e:
            logger.error(f"Failed to assess quality for {asset_id}: {e}")
            return QualityAssessment(
                asset_id=asset_id,
                overall_score=0.0,
                completeness=0.0,
                accuracy=0.0,
                timeliness=0.0,
                consistency=0.0,
                uniqueness=0.0,
                assessment_method="error",
                recommendations=[f"评估失败: {str(e)}"],
            )

    async def batch_assess_quality(
        self,
        asset_ids: List[str],
    ) -> Dict[str, Any]:
        """
        批量评估质量

        用于资产组合的质量报告。
        """
        results = []
        total_score = 0.0

        for asset_id in asset_ids:
            assessment = await self.assess_quality(asset_id)
            results.append({
                "asset_id": asset_id,
                "score": assessment.overall_score,
                "grade": self._score_to_grade(assessment.overall_score),
            })
            total_score += assessment.overall_score

        avg_score = total_score / len(asset_ids) if asset_ids else 0

        return {
            "assessments": results,
            "average_score": round(avg_score, 3),
            "average_grade": self._score_to_grade(avg_score),
            "asset_count": len(asset_ids),
        }

    def _score_to_grade(self, score: float) -> str:
        """分数转等级"""
        if score >= 0.9:
            return "A+"
        elif score >= 0.8:
            return "A"
        elif score >= 0.7:
            return "B"
        elif score >= 0.6:
            return "C"
        else:
            return "D"

    def _generate_quality_recommendations(self, metrics: QualityMetrics) -> List[str]:
        """生成质量改进建议"""
        recommendations = []

        if metrics.completeness < 0.8:
            recommendations.append("数据完整性较低，建议补充缺失值")

        if metrics.accuracy < 0.7:
            recommendations.append("数据准确性需提升，建议增加验证规则")

        if metrics.timeliness < 0.6:
            recommendations.append("数据时效性不足，建议更新数据源")

        if metrics.consistency < 0.7:
            recommendations.append("数据格式不一致，建议标准化处理")

        if metrics.uniqueness < 0.9:
            recommendations.append("存在重复记录，建议去重")

        if not recommendations:
            recommendations.append("数据质量良好，继续保持")

        return recommendations

    # ========================================================================
    # 影响分析API
    # ========================================================================

    async def analyze_impact(self, asset_id: str) -> ImpactAnalysis:
        """
        分析变更影响范围

        评估修改此资产可能影响的其他资产。
        """
        try:
            # 获取上下游
            upstream = await self.get_upstream(asset_id)
            downstream = await self.get_downstream(asset_id)

            # 计算影响分数
            downstream_count = len(downstream)
            if downstream_count == 0:
                risk_level = "low"
                impact_score = 0.1
            elif downstream_count <= 3:
                risk_level = "medium"
                impact_score = 0.4
            else:
                risk_level = "high"
                impact_score = 0.8

            return ImpactAnalysis(
                asset_id=asset_id,
                upstream_count=len(upstream),
                downstream_count=downstream_count,
                total_impact_score=impact_score,
                risk_level=risk_level,
                affected_assets=downstream,
            )

        except Exception as e:
            logger.error(f"Failed to analyze impact for {asset_id}: {e}")
            return ImpactAnalysis(
                asset_id=asset_id,
                upstream_count=0,
                downstream_count=0,
                total_impact_score=0.0,
                risk_level="unknown",
                affected_assets=[],
            )

    async def verify_integrity(self, asset_id: str) -> Dict[str, Any]:
        """
        验证血缘链完整性

        检查数据是否被篡改。
        """
        try:
            verified = await self.tracker.verify_lineage_integrity(asset_id)

            return {
                "asset_id": asset_id,
                "verified": verified,
                "status": "valid" if verified else "compromised",
                "message": "血缘链完整性验证通过" if verified else "警告：血缘链可能被篡改",
            }
        except Exception as e:
            logger.error(f"Failed to verify integrity for {asset_id}: {e}")
            return {
                "asset_id": asset_id,
                "verified": False,
                "status": "error",
                "message": f"验证失败: {str(e)}",
            }

    # ========================================================================
    # 血缘比较API
    # ========================================================================

    async def compare_lineage(
        self,
        asset_id_1: str,
        asset_id_2: str,
    ) -> Dict[str, Any]:
        """
        比较两个资产的血缘关系

        用于检测数据重复或关联性。
        """
        try:
            tree1 = await self.get_lineage_graph(asset_id_1)
            tree2 = await self.get_lineage_graph(asset_id_2)

            # 计算相似度（简化版：比较数据源和节点数）
            source1 = tree1.get("nodes", [{}])[0].get("id", "") if tree1.get("nodes") else ""
            source2 = tree2.get("nodes", [{}])[0].get("id", "") if tree2.get("nodes") else ""

            similarity = 0.0
            if source1 == source2:
                similarity += 0.5

            node_diff = abs(tree1.get("node_count", 0) - tree2.get("node_count", 0))
            if node_diff == 0:
                similarity += 0.3
            elif node_diff <= 2:
                similarity += 0.1

            return {
                "asset_id_1": asset_id_1,
                "asset_id_2": asset_id_2,
                "similarity_score": round(similarity, 2),
                "same_source": source1 == source2,
                "node_count_diff": node_diff,
                "conclusion": "可能同源" if similarity > 0.5 else "独立来源",
            }

        except Exception as e:
            logger.error(f"Failed to compare lineage: {e}")
            return {
                "asset_id_1": asset_id_1,
                "asset_id_2": asset_id_2,
                "similarity_score": 0.0,
                "error": str(e),
            }
