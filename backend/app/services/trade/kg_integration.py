"""
Knowledge Graph Integration - 与知识图谱和记忆图谱的集成

Phase 2: 实现数据权益服务与知识图谱、记忆图谱的深度集成
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.models import DataAssets, DataRightsTransactions

logger = logging.getLogger(__name__)


@dataclass
class NetworkValueMetrics:
    """网络价值指标"""
    entity_count: int
    total_importance: float
    connection_density: float
    scarcity_score: float
    network_value: float


class DataAssetKGIntegration:
    """
    数据资产与知识图谱集成服务
    """

    def __init__(self, db: AsyncSession, neo4j_driver=None):
        self.db = db
        self.neo4j_driver = neo4j_driver

    async def link_asset_to_entities(
        self,
        asset_id: str,
        entity_ids: List[str],
    ) -> None:
        """将数据资产关联到知识图谱实体"""
        # 简化实现：仅更新数据库
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        asset = result.scalar_one_or_none()

        if asset:
            existing = set(asset.related_entities or [])
            new = set(entity_ids)
            asset.related_entities = list(existing | new)
            await self.db.flush()
            logger.info(f"Linked asset {asset_id} to {len(entity_ids)} entities")

    async def calculate_network_value(self, asset_id: str) -> NetworkValueMetrics:
        """计算网络价值"""
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        asset = result.scalar_one_or_none()

        if not asset:
            return NetworkValueMetrics(0, 0, 0, 0, 0)

        entity_count = len(asset.related_entities or [])

        # 查询竞争数据源
        competitor_stmt = select(DataAssets).where(
            and_(
                DataAssets.data_type == asset.data_type,
                DataAssets.is_active == True,
                DataAssets.asset_id != asset_id,
            )
        )
        competitor_result = await self.db.execute(competitor_stmt)
        competitor_count = len(competitor_result.scalars().all())

        scarcity_score = 1.0 if competitor_count == 0 else 1.0 / (1 + competitor_count * 0.1)
        network_value = entity_count * 10 * scarcity_score

        return NetworkValueMetrics(
            entity_count=entity_count,
            total_importance=entity_count * 0.1,
            connection_density=0.5 if entity_count > 0 else 0,
            scarcity_score=scarcity_score,
            network_value=network_value,
        )


class BuyerProfilingService:
    """买方画像服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_buyer_profile(self, buyer_id: int) -> Dict[str, Any]:
        """构建买方画像"""
        # 查询交易历史
        tx_stmt = select(DataRightsTransactions).where(
            DataRightsTransactions.buyer_id == buyer_id
        ).order_by(DataRightsTransactions.created_at.desc()).limit(20)

        tx_result = await self.db.execute(tx_stmt)
        transactions = tx_result.scalars().all()

        profile = {
            "buyer_id": buyer_id,
            "transaction_history": {
                "total_count": len(transactions),
                "total_spent": sum(tx.agreed_price or 0 for tx in transactions),
            },
            "reputation_score": 0.8,  # 简化
        }

        return profile


class RecommendationEngine:
    """推荐引擎"""

    def __init__(self, db: AsyncSession, kg_integration: DataAssetKGIntegration):
        self.db = db
        self.kg_integration = kg_integration

    async def recommend_assets(
        self,
        buyer_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """推荐数据资产"""
        stmt = select(DataAssets).where(
            and_(
                DataAssets.is_active == True,
                DataAssets.is_available_for_trade == True,
            )
        ).order_by(DataAssets.quality_overall_score.desc()).limit(limit)

        result = await self.db.execute(stmt)
        assets = result.scalars().all()

        return [
            {
                "asset_id": asset.asset_id,
                "asset_name": asset.asset_name,
                "quality_score": asset.quality_overall_score,
            }
            for asset in assets
        ]