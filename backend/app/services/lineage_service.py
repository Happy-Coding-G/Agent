"""
数据血缘追踪系统

追踪数据从创建到当前状态的完整生命周期：
- 数据来源记录（Source）
- 转换过程追踪（Transformation）
- 依赖关系管理（Dependency）
- 影响分析（Impact Analysis）
- 血缘可视化（Visualization）

使用场景：
1. 数据溯源：查看Asset/File的数据来源
2. 影响分析：修改上游数据时了解影响范围
3. 合规审计：追踪敏感数据的流转路径
4. 数据质量：识别数据问题的传播路径
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security.audit import AuditAction, audit_logger
from app.db.models import (
    AssetProvenance,
    DataLineage,
    DataLineageType,
    Files,
    SpaceMembers,
    Users,
)
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)


# ============================================================================
# 血缘类型定义
# ============================================================================

class LineageEventType(str, Enum):
    """血缘事件类型"""
    # 数据创建
    CREATED = "created"
    IMPORTED = "imported"
    GENERATED = "generated"

    # 数据处理
    TRANSFORMED = "transformed"
    PROCESSED = "processed"
    EXTRACTED = "extracted"

    # 数据流转
    COPIED = "copied"
    MOVED = "moved"
    SHARED = "shared"
    EXPORTED = "exported"

    # 数据派生
    DERIVED = "derived"
    AGGREGATED = "aggregated"
    JOINED = "joined"

    # 数据删除
    DELETED = "deleted"
    ARCHIVED = "archived"


class LineageDirection(str, Enum):
    """血缘方向"""
    UPSTREAM = "upstream"    # 上游（数据来源）
    DOWNSTREAM = "downstream"  # 下游（数据去向）
    BOTH = "both"


@dataclass
class LineageNode:
    """血缘图中的节点"""
    id: str
    entity_type: str  # file, asset, knowledge, user, external
    entity_id: str
    name: str
    space_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    created_at: Optional[datetime] = None


@dataclass
class LineageEdge:
    """血缘图中的边"""
    id: str
    source_id: str
    target_id: str
    relationship: str
    event_type: LineageEventType
    confidence: float  # 0.0 - 1.0
    metadata: Dict[str, Any] = None
    created_at: Optional[datetime] = None
    created_by: Optional[int] = None


@dataclass
class LineagePath:
    """血缘路径"""
    nodes: List[LineageNode]
    edges: List[LineageEdge]
    total_confidence: float


@dataclass
class ImpactAnalysisResult:
    """影响分析结果"""
    source_id: str
    affected_entities: List[Dict[str, Any]]
    total_count: int
    critical_paths: List[LineagePath]
    risk_score: float


# ============================================================================
# 核心服务
# ============================================================================

class LineageService:
    """
    数据血缘服务

    提供完整的数据血缘管理能力
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================================
    # 血缘记录创建
    # ========================================================================

    async def record_lineage(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        event_type: LineageEventType,
        source_entity_type: Optional[DataLineageType] = None,
        source_entity_id: Optional[str] = None,
        user_id: Optional[int] = None,
        space_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        transformation_logic: Optional[str] = None,
        request=None,
    ) -> DataLineage:
        """
        记录数据血缘关系

        Args:
            entity_type: 目标实体类型
            entity_id: 目标实体ID
            event_type: 事件类型
            source_entity_type: 来源实体类型
            source_entity_id: 来源实体ID
            user_id: 操作用户ID
            space_id: Space ID
            metadata: 额外元数据
            confidence: 置信度（0-1）
            transformation_logic: 转换逻辑描述
            request: HTTP请求对象

        Returns:
            创建的血缘记录
        """
        lineage_id = f"lin_{snowflake_id()}"

        lineage = DataLineage(
            id=snowflake_id(),
            lineage_id=lineage_id,
            entity_type=entity_type,
            entity_id=entity_id,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            relationship=event_type.value,
            metadata={
                **(metadata or {}),
                "event_type": event_type.value,
                "confidence": confidence,
            },
            transformation_logic=transformation_logic,
            confidence_score=confidence,
            space_id=space_id,
            created_by=user_id,
        )

        self.db.add(lineage)
        await self.db.commit()
        await self.db.refresh(lineage)

        # 记录审计日志
        if user_id:
            await audit_logger.log(
                db=self.db,
                action=AuditAction.ASSET_CREATE if event_type == LineageEventType.CREATED else AuditAction.ASSET_UPDATE,
                user_id=user_id,
                resource_type=entity_type.value,
                resource_id=entity_id,
                request=request,
                new_state={
                    "lineage_id": lineage_id,
                    "event": event_type.value,
                    "source": f"{source_entity_type.value}:{source_entity_id}" if source_entity_type else None,
                },
            )

        logger.info(
            f"Lineage recorded: {lineage_id} - {entity_type.value}:{entity_id} "
            f"<- {source_entity_type.value}:{source_entity_id if event_type else 'null'}"
        )

        return lineage

    async def record_file_upload_lineage(
        self,
        file_id: str,
        user_id: int,
        space_id: str,
        source_type: str = "upload",  # upload, import, sync
        source_info: Optional[Dict[str, Any]] = None,
        request=None,
    ) -> DataLineage:
        """记录文件上传血缘"""
        return await self.record_lineage(
            entity_type=DataLineageType.FILE,
            entity_id=file_id,
            event_type=LineageEventType.IMPORTED if source_type == "import" else LineageEventType.CREATED,
            user_id=user_id,
            space_id=space_id,
            metadata={
                "source_type": source_type,
                **(source_info or {}),
            },
            request=request,
        )

    async def record_asset_creation_lineage(
        self,
        asset_id: str,
        source_file_id: Optional[str],
        user_id: int,
        space_id: str,
        extraction_config: Optional[Dict[str, Any]] = None,
        request=None,
    ) -> DataLineage:
        """记录Asset创建血缘（从File提取）"""
        return await self.record_lineage(
            entity_type=DataLineageType.ASSET,
            entity_id=asset_id,
            event_type=LineageEventType.EXTRACTED,
            source_entity_type=DataLineageType.FILE if source_file_id else None,
            source_entity_id=source_file_id,
            user_id=user_id,
            space_id=space_id,
            metadata=extraction_config,
            transformation_logic="Asset extraction from file",
            request=request,
        )

    async def record_knowledge_ingestion_lineage(
        self,
        knowledge_id: str,
        source_file_ids: List[str],
        user_id: int,
        space_id: str,
        chunk_config: Optional[Dict[str, Any]] = None,
        request=None,
    ) -> List[DataLineage]:
        """记录知识库摄入血缘"""
        lineages = []

        for file_id in source_file_ids:
            lineage = await self.record_lineage(
                entity_type=DataLineageType.KNOWLEDGE,
                entity_id=knowledge_id,
                event_type=LineageEventType.DERIVED,
                source_entity_type=DataLineageType.FILE,
                source_entity_id=file_id,
                user_id=user_id,
                space_id=space_id,
                metadata=chunk_config,
                transformation_logic="Knowledge extraction and chunking",
                request=request,
            )
            lineages.append(lineage)

        return lineages

    async def record_graph_construction_lineage(
        self,
        graph_id: str,
        source_knowledge_ids: List[str],
        user_id: int,
        space_id: str,
        extraction_model: Optional[str] = None,
        request=None,
    ) -> List[DataLineage]:
        """记录知识图谱构建血缘"""
        lineages = []

        for knowledge_id in source_knowledge_ids:
            lineage = await self.record_lineage(
                entity_type=DataLineageType.KNOWLEDGE,  # 图谱也是知识的一种形式
                entity_id=graph_id,
                event_type=LineageEventType.TRANSFORMED,
                source_entity_type=DataLineageType.KNOWLEDGE,
                source_entity_id=knowledge_id,
                user_id=user_id,
                space_id=space_id,
                metadata={"extraction_model": extraction_model},
                transformation_logic="Entity and relation extraction",
                request=request,
            )
            lineages.append(lineage)

        return lineages

    # ========================================================================
    # 血缘查询
    # ========================================================================

    async def get_upstream_lineage(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        max_depth: int = 5,
        min_confidence: float = 0.0,
    ) -> List[LineagePath]:
        """
        获取上游血缘（数据来源）

        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            max_depth: 最大追溯深度
            min_confidence: 最小置信度

        Returns:
            血缘路径列表
        """
        paths = []
        visited = set()

        async def trace_upstream(
            current_type: DataLineageType,
            current_id: str,
            current_path: List[DataLineage],
            depth: int,
        ):
            if depth > max_depth or f"{current_type.value}:{current_id}" in visited:
                return

            visited.add(f"{current_type.value}:{current_id}")

            # 查询上游记录
            result = await self.db.execute(
                select(DataLineage).where(
                    and_(
                        DataLineage.entity_type == current_type,
                        DataLineage.entity_id == current_id,
                        DataLineage.source_entity_id.isnot(None),
                        DataLineage.confidence_score >= min_confidence,
                    )
                ).order_by(DataLineage.created_at.desc())
            )

            records = result.scalars().all()

            if not records:
                # 到达源头
                if current_path:
                    paths.append(await self._build_path(current_path))
                return

            for record in records:
                new_path = current_path + [record]

                if record.source_entity_type and record.source_entity_id:
                    await trace_upstream(
                        record.source_entity_type,
                        record.source_entity_id,
                        new_path,
                        depth + 1,
                    )
                else:
                    paths.append(await self._build_path(new_path))

        await trace_upstream(entity_type, entity_id, [], 0)
        return paths

    async def get_downstream_lineage(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        max_depth: int = 5,
        min_confidence: float = 0.0,
    ) -> List[LineagePath]:
        """
        获取下游血缘（数据去向）

        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            max_depth: 最大追溯深度
            min_confidence: 最小置信度

        Returns:
            血缘路径列表
        """
        paths = []
        visited = set()

        async def trace_downstream(
            current_type: DataLineageType,
            current_id: str,
            current_path: List[DataLineage],
            depth: int,
        ):
            if depth > max_depth or f"{current_type.value}:{current_id}" in visited:
                return

            visited.add(f"{current_type.value}:{current_id}")

            # 查询下游记录（作为来源的记录）
            result = await self.db.execute(
                select(DataLineage).where(
                    and_(
                        DataLineage.source_entity_type == current_type,
                        DataLineage.source_entity_id == current_id,
                        DataLineage.confidence_score >= min_confidence,
                    )
                ).order_by(DataLineage.created_at.desc())
            )

            records = result.scalars().all()

            if not records:
                # 到达末端
                if current_path:
                    paths.append(await self._build_path(current_path))
                return

            for record in records:
                new_path = current_path + [record]
                await trace_downstream(
                    record.entity_type,
                    record.entity_id,
                    new_path,
                    depth + 1,
                )

        await trace_downstream(entity_type, entity_id, [], 0)
        return paths

    async def get_full_lineage(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        max_depth: int = 5,
    ) -> Dict[str, List[LineagePath]]:
        """
        获取完整血缘（上下游）

        Returns:
            {"upstream": [...], "downstream": [...]}
        """
        upstream = await self.get_upstream_lineage(entity_type, entity_id, max_depth)
        downstream = await self.get_downstream_lineage(entity_type, entity_id, max_depth)

        return {
            "upstream": upstream,
            "downstream": downstream,
        }

    async def get_lineage_graph(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """
        获取血缘图（用于可视化）

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        nodes: Dict[str, LineageNode] = {}
        edges: List[LineageEdge] = []

        # 获取完整血缘
        full_lineage = await self.get_full_lineage(
            entity_type, entity_id, max_depth
        )

        # 添加上游节点和边
        for path in full_lineage["upstream"]:
            for edge in path.edges:
                if edge.source_id not in nodes:
                    nodes[edge.source_id] = await self._get_node_info(edge.source_id)
                if edge.target_id not in nodes:
                    nodes[edge.target_id] = await self._get_node_info(edge.target_id)
                edges.append(edge)

        # 添加下游节点和边
        for path in full_lineage["downstream"]:
            for edge in path.edges:
                if edge.source_id not in nodes:
                    nodes[edge.source_id] = await self._get_node_info(edge.source_id)
                if edge.target_id not in nodes:
                    nodes[edge.target_id] = await self._get_node_info(edge.target_id)
                edges.append(edge)

        # 添加中心节点
        center_key = f"{entity_type.value}:{entity_id}"
        if center_key not in nodes:
            nodes[center_key] = await self._get_node_info(center_key)

        return {
            "nodes": [n.__dict__ for n in nodes.values()],
            "edges": [e.__dict__ for e in edges],
            "center_node": center_key,
        }

    # ========================================================================
    # 影响分析
    # ========================================================================

    async def analyze_impact(
        self,
        entity_type: DataLineageType,
        entity_id: str,
        max_depth: int = 5,
    ) -> ImpactAnalysisResult:
        """
        分析修改某实体可能产生的影响

        Returns:
            影响分析结果
        """
        # 获取所有下游血缘
        downstream_paths = await self.get_downstream_lineage(
            entity_type, entity_id, max_depth
        )

        # 收集受影响实体
        affected = {}
        critical_paths = []

        for path in downstream_paths:
            # 检查路径置信度
            if path.total_confidence >= 0.8:
                critical_paths.append(path)

            for edge in path.edges:
                key = f"{edge.target_id}"
                if key not in affected:
                    node = await self._get_node_info(edge.target_id)
                    affected[key] = {
                        "entity_id": edge.target_id,
                        "entity_type": node.entity_type if node else "unknown",
                        "name": node.name if node else "Unknown",
                        "distance": path.edges.index(edge) + 1,
                        "confidence": edge.confidence,
                    }

        # 计算风险评分
        risk_score = self._calculate_risk_score(
            len(affected),
            len(critical_paths),
            downstream_paths,
        )

        return ImpactAnalysisResult(
            source_id=f"{entity_type.value}:{entity_id}",
            affected_entities=list(affected.values()),
            total_count=len(affected),
            critical_paths=critical_paths,
            risk_score=risk_score,
        )

    async def get_impact_report(
        self,
        entity_type: DataLineageType,
        entity_id: str,
    ) -> Dict[str, Any]:
        """生成详细的影响分析报告"""
        impact = await self.analyze_impact(entity_type, entity_id)

        # 按类型分组
        by_type = {}
        for entity in impact.affected_entities:
            t = entity["entity_type"]
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(entity)

        # 按距离分组
        by_distance = {}
        for entity in impact.affected_entities:
            d = entity["distance"]
            if d not in by_distance:
                by_distance[d] = []
            by_distance[d].append(entity)

        return {
            "source": impact.source_id,
            "summary": {
                "total_affected": impact.total_count,
                "critical_paths": len(impact.critical_paths),
                "risk_score": impact.risk_score,
                "risk_level": "high" if impact.risk_score > 0.7 else "medium" if impact.risk_score > 0.3 else "low",
            },
            "by_type": by_type,
            "by_distance": by_distance,
            "critical_details": [
                {
                    "path_confidence": p.total_confidence,
                    "nodes": [n.name for n in p.nodes],
                }
                for p in impact.critical_paths
            ],
        }

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def _build_path(self, records: List[DataLineage]) -> LineagePath:
        """从血缘记录构建路径"""
        nodes = []
        edges = []
        total_confidence = 1.0

        for i, record in enumerate(records):
            # 添加源节点
            if i == 0 and record.source_entity_type and record.source_entity_id:
                source_key = f"{record.source_entity_type.value}:{record.source_entity_id}"
                source_node = await self._get_node_info(source_key)
                if source_node:
                    nodes.append(source_node)

            # 添加目标节点
            target_key = f"{record.entity_type.value}:{record.entity_id}"
            target_node = await self._get_node_info(target_key)
            if target_node:
                nodes.append(target_node)

            # 添加边
            edge = LineageEdge(
                id=record.lineage_id,
                source_id=f"{record.source_entity_type.value}:{record.source_entity_id}" if record.source_entity_type else "",
                target_id=target_key,
                relationship=record.relationship,
                event_type=LineageEventType(record.metadata.get("event_type", "created")),
                confidence=record.confidence_score,
                metadata=record.metadata,
                created_at=record.created_at,
                created_by=record.created_by,
            )
            edges.append(edge)
            total_confidence *= record.confidence_score

        return LineagePath(
            nodes=nodes,
            edges=edges,
            total_confidence=total_confidence,
        )

    async def _get_node_info(self, composite_id: str) -> Optional[LineageNode]:
        """获取节点信息"""
        try:
            parts = composite_id.split(":", 1)
            if len(parts) != 2:
                return None

            entity_type_str, entity_id = parts

            # 根据类型查询实体信息
            if entity_type_str == DataLineageType.FILE.value:
                result = await self.db.execute(
                    select(Files).where(Files.file_id == entity_id)
                )
                file = result.scalar_one_or_none()
                if file:
                    return LineageNode(
                        id=composite_id,
                        entity_type=DataLineageType.FILE.value,
                        entity_id=entity_id,
                        name=file.filename,
                        space_id=file.space_id,
                        metadata={"file_type": file.file_type, "size": file.file_size},
                    )

            elif entity_type_str == DataLineageType.ASSET.value:
                # Asset查询
                result = await self.db.execute(
                    select(AssetProvenance).where(AssetProvenance.asset_id == entity_id)
                )
                asset = result.scalar_one_or_none()
                if asset:
                    return LineageNode(
                        id=composite_id,
                        entity_type=DataLineageType.ASSET.value,
                        entity_id=entity_id,
                        name=asset.name,
                        space_id=None,
                        metadata={"data_type": asset.data_type},
                    )

            # 默认节点
            return LineageNode(
                id=composite_id,
                entity_type=entity_type_str,
                entity_id=entity_id,
                name=entity_id[:20],
            )

        except Exception as e:
            logger.error(f"Error getting node info for {composite_id}: {e}")
            return None

    def _calculate_risk_score(
        self,
        affected_count: int,
        critical_count: int,
        paths: List[LineagePath],
    ) -> float:
        """计算风险评分"""
        # 基于受影响数量
        count_score = min(affected_count / 100, 1.0) * 0.3

        # 基于关键路径数量
        critical_score = min(critical_count / 10, 1.0) * 0.4

        # 基于平均置信度（低置信度意味着不确定性高）
        if paths:
            avg_confidence = sum(p.total_confidence for p in paths) / len(paths)
            confidence_score = (1 - avg_confidence) * 0.3
        else:
            confidence_score = 0

        return min(count_score + critical_score + confidence_score, 1.0)

    # ========================================================================
    # 批量操作和维护
    # ========================================================================

    async def bulk_record_lineage(
        self,
        records: List[Dict[str, Any]],
    ) -> List[DataLineage]:
        """批量记录血缘"""
        lineages = []

        for record_data in records:
            lineage = DataLineage(
                id=snowflake_id(),
                lineage_id=f"lin_{snowflake_id()}",
                **record_data,
            )
            self.db.add(lineage)
            lineages.append(lineage)

        await self.db.commit()
        return lineages

    async def purge_old_lineage(
        self,
        days: int = 365,
        dry_run: bool = False,
    ) -> int:
        """
        清理旧血缘数据

        Args:
            days: 保留天数
            dry_run: 是否仅预览

        Returns:
            清理的记录数
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(func.count(DataLineage.id)).where(
                DataLineage.created_at < cutoff
            )
        )
        count = result.scalar()

        if not dry_run:
            await self.db.execute(
                text("DELETE FROM data_lineage WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            await self.db.commit()
            logger.info(f"Purged {count} old lineage records")

        return count

    async def get_lineage_statistics(
        self,
        space_id: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """获取血缘统计信息"""
        from_time = datetime.now(timezone.utc) - timedelta(days=days)

        # 基础查询
        base_query = select(DataLineage).where(DataLineage.created_at >= from_time)
        if space_id:
            base_query = base_query.where(DataLineage.space_id == space_id)

        # 按实体类型统计
        result = await self.db.execute(
            select(
                DataLineage.entity_type,
                func.count(DataLineage.id),
            ).where(
                DataLineage.created_at >= from_time
            ).group_by(DataLineage.entity_type)
        )
        by_type = {row[0].value: row[1] for row in result.all()}

        # 按关系类型统计
        result = await self.db.execute(
            select(
                DataLineage.relationship,
                func.count(DataLineage.id),
            ).where(
                DataLineage.created_at >= from_time
            ).group_by(DataLineage.relationship)
        )
        by_relationship = {row[0]: row[1] for row in result.all()}

        # 总记录数
        result = await self.db.execute(
            select(func.count(DataLineage.id)).where(
                DataLineage.created_at >= from_time
            )
        )
        total = result.scalar()

        # 平均置信度
        result = await self.db.execute(
            select(func.avg(DataLineage.confidence_score)).where(
                DataLineage.created_at >= from_time
            )
        )
        avg_confidence = result.scalar() or 0.0

        return {
            "period_days": days,
            "total_records": total,
            "by_entity_type": by_type,
            "by_relationship": by_relationship,
            "average_confidence": round(avg_confidence, 3),
        }


# ============================================================================
# 便捷函数
# ============================================================================

async def get_lineage_service(db: AsyncSession) -> LineageService:
    """获取血缘服务实例"""
    return LineageService(db)
