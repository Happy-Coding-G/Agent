"""
Data Lineage Tracker - 数据血缘追踪服务

Phase 2: 实现数据资产的完整血缘追踪与质量评估
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import DataLineageNodes, DataAssets
from app.services.trade.data_rights_events import (
    ProcessingStep,
    QualityMetrics,
)

logger = logging.getLogger(__name__)


@dataclass
class LineageNode:
    """血缘节点数据类"""
    node_id: str
    node_type: str  # raw, processed, aggregated, derived
    parent_nodes: List[str]
    processing_logic: str
    quality_metrics: Dict[str, float]
    provenance_hash: str
    timestamp: datetime


class DataLineageTracker:
    """
    数据血缘追踪器

    职责：
    1. 构建和维护数据处理链
    2. 计算血缘哈希确保完整性
    3. 支持血缘溯源和影响分析
    4. 与知识图谱集成
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_lineage_chain(
        self,
        asset_id: str,
        raw_data_source: str,
        processing_chain: List[ProcessingStep],
    ) -> str:
        """
        构建完整的数据血缘链

        Args:
            asset_id: 数据资产ID
            raw_data_source: 原始数据来源
            processing_chain: 数据处理步骤列表

        Returns:
            lineage_root: 血缘根节点哈希
        """
        lineage_nodes = []
        previous_hash = "0"
        root_hash = None

        for i, step in enumerate(processing_chain):
            # 生成节点ID
            node_id = f"{asset_id}_node_{i}"

            # 计算处理逻辑哈希
            logic_hash = hashlib.sha256(
                step.logic_code.encode()
            ).hexdigest()[:32]

            # 计算血缘哈希（包含父节点信息）
            provenance_data = {
                "node_id": node_id,
                "node_type": step.step_type,
                "logic_hash": logic_hash,
                "parent_hash": previous_hash,
                "step_index": step.index,
            }
            provenance_hash = hashlib.sha256(
                json.dumps(provenance_data, sort_keys=True).encode()
            ).hexdigest()[:32]

            # 创建节点
            node = LineageNode(
                node_id=node_id,
                node_type=step.step_type,
                parent_nodes=[previous_hash] if previous_hash != "0" else [],
                processing_logic=step.logic_code[:200],  # 截断存储
                quality_metrics=step.quality_report,
                provenance_hash=provenance_hash,
                timestamp=datetime.now(timezone.utc),
            )
            lineage_nodes.append(node)

            # 设置根哈希
            if i == 0:
                root_hash = provenance_hash

            # 保存到数据库
            await self._save_lineage_node(asset_id, node)

            previous_hash = provenance_hash

        logger.info(f"Built lineage chain for {asset_id}: {len(lineage_nodes)} nodes")
        return root_hash

    async def _save_lineage_node(self, asset_id: str, node: LineageNode) -> None:
        """保存血缘节点到数据库"""
        db_node = DataLineageNodes(
            node_id=node.node_id,
            asset_id=asset_id,
            node_type=node.node_type,
            parent_nodes=node.parent_nodes,
            processing_logic_hash=hashlib.sha256(
                node.processing_logic.encode()
            ).hexdigest()[:32],
            quality_metrics=node.quality_metrics,
            provenance_hash=node.provenance_hash,
        )
        self.db.add(db_node)

    async def verify_lineage_integrity(self, asset_id: str) -> bool:
        """
        验证血缘链完整性

        检查每个节点的哈希是否正确，确保数据未被篡改
        """
        nodes = await self._get_lineage_chain(asset_id)

        if not nodes:
            return True  # 无血缘链视为通过

        for i, node in enumerate(nodes):
            # 重建哈希验证
            expected_data = {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "logic_hash": node.processing_logic_hash,
                "parent_hash": node.parent_nodes[0] if node.parent_nodes else "0",
                "step_index": i,
            }
            expected_hash = hashlib.sha256(
                json.dumps(expected_data, sort_keys=True).encode()
            ).hexdigest()[:32]

            if node.provenance_hash != expected_hash:
                logger.error(
                    f"Lineage integrity check failed for {asset_id} at node {i}"
                )
                return False

        logger.info(f"Lineage integrity verified for {asset_id}")
        return True

    async def _get_lineage_chain(self, asset_id: str) -> List[DataLineageNodes]:
        """获取完整血缘链"""
        stmt = (
            select(DataLineageNodes)
            .where(DataLineageNodes.asset_id == asset_id)
            .order_by(DataLineageNodes.created_at)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_lineage_tree(self, asset_id: str) -> Dict[str, Any]:
        """
        获取血缘树形结构

        返回完整的血缘关系，支持可视化展示
        """
        nodes = await self._get_lineage_chain(asset_id)

        if not nodes:
            return {"asset_id": asset_id, "nodes": [], "edges": []}

        # 构建节点列表
        node_list = [
            {
                "id": node.node_id,
                "type": node.node_type,
                "quality": node.quality_metrics,
                "hash": node.provenance_hash[:16] + "...",
            }
            for node in nodes
        ]

        # 构建边列表
        edge_list = []
        for i, node in enumerate(nodes):
            for parent in node.parent_nodes:
                edge_list.append({
                    "from": parent[:16] + "..." if len(parent) > 16 else parent,
                    "to": node.node_id,
                    "label": f"step_{i}",
                })

        return {
            "asset_id": asset_id,
            "root_hash": nodes[0].provenance_hash if nodes else None,
            "node_count": len(nodes),
            "nodes": node_list,
            "edges": edge_list,
        }

    async def get_upstream_dependencies(
        self,
        asset_id: str,
    ) -> List[Dict[str, Any]]:
        """
        获取上游依赖

        追溯数据的来源
        """
        asset = await self._get_asset(asset_id)
        if not asset:
            return []

        return [{
            "source": asset.raw_data_source,
            "type": "raw_data",
            "lineage_root": asset.lineage_root,
        }]

    async def get_downstream_impact(
        self,
        asset_id: str,
    ) -> List[Dict[str, Any]]:
        """
        获取下游影响

        分析哪些资产依赖于当前资产
        """
        # 查询所有引用了当前 asset_id 的数据资产
        stmt = select(DataAssets).where(
            and_(
                DataAssets.is_active == True,
                DataAssets.processing_chain_hash.isnot(None),
            )
        )
        result = await self.db.execute(stmt)
        all_assets = result.scalars().all()

        impacted = []
        for asset in all_assets:
            # 检查是否依赖当前资产
            if await self._is_dependent_on(asset.asset_id, asset_id):
                impacted.append({
                    "asset_id": asset.asset_id,
                    "asset_name": asset.asset_name,
                    "owner_id": asset.owner_id,
                })

        return impacted

    async def _is_dependent_on(
        self,
        dependent_asset_id: str,
        parent_asset_id: str,
    ) -> bool:
        """检查一个资产是否依赖于另一个资产"""
        # 实现依赖检查逻辑
        # 可以通过分析 lineage 链中的数据源引用
        nodes = await self._get_lineage_chain(dependent_asset_id)
        for node in nodes:
            if node.node_type == "derived" and parent_asset_id in str(node.parent_nodes):
                return True
        return False

    async def _get_asset(self, asset_id: str) -> Optional[DataAssets]:
        """获取资产信息"""
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class DataQualityAssessor:
    """
    数据质量评估器

    多维度评估数据质量
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def assess_quality(
        self,
        asset_id: str,
        sample_data: Optional[List[Dict]] = None,
    ) -> QualityMetrics:
        """
        评估数据质量

        Args:
            asset_id: 数据资产ID
            sample_data: 样本数据（用于自动评估）

        Returns:
            QualityMetrics: 质量指标
        """
        # 从数据库获取资产信息
        asset = await self._get_asset(asset_id)

        if asset and asset.quality_overall_score > 0:
            # 已有人工评估结果
            return QualityMetrics(
                completeness=asset.quality_completeness,
                accuracy=asset.quality_accuracy,
                timeliness=asset.quality_timeliness,
                consistency=asset.quality_consistency,
                uniqueness=asset.quality_uniqueness,
            )

        # 自动评估
        if sample_data:
            return await self._auto_assess(sample_data)

        # 默认返回中等质量
        return QualityMetrics(
            completeness=0.5,
            accuracy=0.5,
            timeliness=0.5,
            consistency=0.5,
            uniqueness=0.5,
        )

    async def _auto_assess(self, data: List[Dict]) -> QualityMetrics:
        """基于样本数据自动评估质量"""
        if not data:
            return QualityMetrics(0, 0, 0, 0, 0)

        # 完整性：非空值比例
        completeness = self._assess_completeness(data)

        # 准确性：基于规则检查
        accuracy = self._assess_accuracy(data)

        # 时效性：数据年龄
        timeliness = self._assess_timeliness(data)

        # 一致性：格式一致性
        consistency = self._assess_consistency(data)

        # 唯一性：重复记录比例
        uniqueness = self._assess_uniqueness(data)

        return QualityMetrics(
            completeness=completeness,
            accuracy=accuracy,
            timeliness=timeliness,
            consistency=consistency,
            uniqueness=uniqueness,
        )

    def _assess_completeness(self, data: List[Dict]) -> float:
        """评估完整性"""
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

    def _assess_accuracy(self, data: List[Dict]) -> float:
        """评估准确性（简化版）"""
        # 实际实现可以包括：格式验证、范围检查、引用完整性等
        return 0.8  # 默认较高准确性

    def _assess_timeliness(self, data: List[Dict]) -> float:
        """评估时效性"""
        # 检查数据中的时间戳字段
        # 越新的数据时效性越高
        return 0.9  # 默认较高时效性

    def _assess_consistency(self, data: List[Dict]) -> float:
        """评估一致性"""
        if not data or len(data) < 2:
            return 1.0

        # 检查字段一致性
        first_keys = set(data[0].keys())
        consistent_count = sum(
            1 for record in data if set(record.keys()) == first_keys
        )

        return consistent_count / len(data)

    def _assess_uniqueness(self, data: List[Dict]) -> float:
        """评估唯一性"""
        if not data:
            return 0.0

        # 计算重复记录比例
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

    async def update_quality_metrics(
        self,
        asset_id: str,
        metrics: QualityMetrics,
    ) -> None:
        """更新资产质量评分"""
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        asset = result.scalar_one_or_none()

        if asset:
            asset.quality_completeness = metrics.completeness
            asset.quality_accuracy = metrics.accuracy
            asset.quality_timeliness = metrics.timeliness
            asset.quality_consistency = metrics.consistency
            asset.quality_uniqueness = metrics.uniqueness
            asset.quality_overall_score = metrics.overall_score

            await self.db.flush()
            logger.info(f"Updated quality metrics for {asset_id}: {metrics.overall_score:.3f}")

    async def _get_asset(self, asset_id: str) -> Optional[DataAssets]:
        """获取资产信息"""
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
