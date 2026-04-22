"""
MarketAnalysisSkill - 市场分析Skill

提供市场竞争分析、买方画像、资产推荐等能力。
无状态、只读的Skill，可被多个Agent复用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.db.models import DataAssets, DataRightsTransactions
from app.services.trade.kg_integration import (
    DataAssetKGIntegration,
    BuyerProfilingService,
    RecommendationEngine,
    NetworkValueMetrics,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketTrend:
    """市场趋势"""
    data_type: str
    transaction_count: int
    avg_price: float
    price_change_pct: float
    trend: str  # up, down, stable
    top_assets: List[Dict[str, Any]]


@dataclass
class CompetitorAnalysis:
    """竞争分析"""
    asset_id: str
    competitor_count: int
    market_position: str  # leader, follower, niche
    price_percentile: float  # 0-100
    quality_percentile: float  # 0-100
    differentiation_score: float  # 0-1


@dataclass
class BuyerPersona:
    """买方画像"""
    buyer_id: int
    segment: str  # enterprise, researcher, individual
    buying_power: float
    preferred_data_types: List[str]
    price_sensitivity: str  # high, medium, low
    reputation_score: float
    transaction_history: Dict[str, Any]


@dataclass
class AssetRecommendation:
    """资产推荐"""
    asset_id: str
    asset_name: str
    relevance_score: float
    price: float
    reason: str


class MarketAnalysisSkill:
    """
    市场分析Skill

    职责：
    1. 市场趋势分析
    2. 竞争情报
    3. 买方画像构建
    4. 资产推荐
    5. 网络价值评估

    使用示例：
        skill = MarketAnalysisSkill(db)

        # 市场趋势
        trend = await skill.get_market_trend("medical")

        # 竞争分析
        analysis = await skill.analyze_competition(asset_id)

        # 买方画像
        persona = await skill.get_buyer_persona(buyer_id)

        # 资产推荐
        recommendations = await skill.recommend_assets(buyer_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kg_integration = DataAssetKGIntegration(db)
        self.buyer_profiling = BuyerProfilingService(db)
        self.recommendation_engine = RecommendationEngine(db, self.kg_integration)

    # ========================================================================
    # 市场趋势API
    # ========================================================================

    async def get_market_trend(
        self,
        data_type: Optional[str] = None,
        days: int = 30,
    ) -> MarketTrend:
        """
        获取市场趋势

        分析特定数据类型的交易趋势。
        """
        try:
            since = datetime.now(timezone.utc) - timedelta(days=days)

            # 查询交易统计
            stmt = select(
                func.count(DataRightsTransactions.id).label("count"),
                func.avg(DataRightsTransactions.agreed_price).label("avg_price"),
            ).where(
                DataRightsTransactions.created_at >= since,
                DataRightsTransactions.status == "completed",
            )

            if data_type:
                # 通过asset_id关联过滤类型
                # 简化实现
                pass

            result = await self.db.execute(stmt)
            stats = result.one_or_none()

            transaction_count = stats.count if stats else 0
            avg_price = stats.avg_price if stats and stats.avg_price else 0.0

            # 获取热门资产
            top_assets = await self._get_top_assets(data_type, limit=5)

            # 简化趋势判断
            trend = "stable"
            price_change = 0.0

            return MarketTrend(
                data_type=data_type or "all",
                transaction_count=transaction_count,
                avg_price=round(avg_price, 2),
                price_change_pct=round(price_change, 2),
                trend=trend,
                top_assets=top_assets,
            )

        except Exception as e:
            logger.error(f"Failed to get market trend: {e}")
            return MarketTrend(
                data_type=data_type or "all",
                transaction_count=0,
                avg_price=0.0,
                price_change_pct=0.0,
                trend="unknown",
                top_assets=[],
            )

    async def get_market_overview(self) -> Dict[str, Any]:
        """
        获取市场概览

        整体市场状况摘要。
        """
        try:
            # 总交易量
            tx_stmt = select(func.count(DataRightsTransactions.id))
            tx_result = await self.db.execute(tx_stmt)
            total_transactions = tx_result.scalar() or 0

            # 活跃资产数
            asset_stmt = select(func.count(DataAssets.id)).where(
                DataAssets.is_active == True,
                DataAssets.is_available_for_trade == True,
            )
            asset_result = await self.db.execute(asset_stmt)
            active_assets = asset_result.scalar() or 0

            # 各类资产分布
            type_stmt = select(
                DataAssets.data_type,
                func.count(DataAssets.id).label("count"),
            ).where(
                DataAssets.is_active == True,
            ).group_by(DataAssets.data_type)

            type_result = await self.db.execute(type_stmt)
            type_distribution = [
                {"type": row[0], "count": row[1]}
                for row in type_result.all()
            ]

            return {
                "total_transactions": total_transactions,
                "active_assets": active_assets,
                "type_distribution": type_distribution,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to get market overview: {e}")
            return {
                "total_transactions": 0,
                "active_assets": 0,
                "type_distribution": [],
                "error": str(e),
            }

    # ========================================================================
    # 竞争分析API
    # ========================================================================

    async def analyze_competition(self, asset_id: str) -> CompetitorAnalysis:
        """
        分析资产竞争状况

        评估资产在市场中的竞争地位。
        """
        try:
            # 获取资产信息
            asset_stmt = select(DataAssets).where(
                DataAssets.asset_id == asset_id
            )
            asset_result = await self.db.execute(asset_stmt)
            asset = asset_result.scalar_one_or_none()

            if not asset:
                return CompetitorAnalysis(
                    asset_id=asset_id,
                    competitor_count=0,
                    market_position="unknown",
                    price_percentile=0.0,
                    quality_percentile=0.0,
                    differentiation_score=0.0,
                )

            # 查询同类资产
            competitor_stmt = select(DataAssets).where(
                DataAssets.data_type == asset.data_type,
                DataAssets.asset_id != asset_id,
                DataAssets.is_active == True,
            )
            competitor_result = await self.db.execute(competitor_stmt)
            competitors = competitor_result.scalars().all()
            competitor_count = len(competitors)

            # 计算价格分位数
            all_prices = [c.base_price for c in competitors if c.base_price]
            if asset.base_price and all_prices:
                all_prices.append(asset.base_price)
                all_prices.sort()
                price_rank = all_prices.index(asset.base_price)
                price_percentile = (price_rank / len(all_prices)) * 100
            else:
                price_percentile = 50.0

            # 计算质量分位数
            all_quality = [c.quality_overall_score for c in competitors if c.quality_overall_score > 0]
            if asset.quality_overall_score > 0 and all_quality:
                all_quality.append(asset.quality_overall_score)
                all_quality.sort()
                quality_rank = all_quality.index(asset.quality_overall_score)
                quality_percentile = (quality_rank / len(all_quality)) * 100
            else:
                quality_percentile = 50.0

            # 市场定位
            if quality_percentile >= 75 and price_percentile >= 75:
                market_position = "leader"
            elif quality_percentile >= 50:
                market_position = "follower"
            else:
                market_position = "niche"

            # 差异化分数（基于独特实体数量）
            related_entities = len(asset.related_entities or [])
            differentiation_score = min(1.0, related_entities / 20)

            return CompetitorAnalysis(
                asset_id=asset_id,
                competitor_count=competitor_count,
                market_position=market_position,
                price_percentile=round(price_percentile, 1),
                quality_percentile=round(quality_percentile, 1),
                differentiation_score=round(differentiation_score, 2),
            )

        except Exception as e:
            logger.error(f"Failed to analyze competition for {asset_id}: {e}")
            return CompetitorAnalysis(
                asset_id=asset_id,
                competitor_count=0,
                market_position="error",
                price_percentile=0.0,
                quality_percentile=0.0,
                differentiation_score=0.0,
            )

    async def get_network_value(self, asset_id: str) -> Dict[str, Any]:
        """
        获取资产网络价值

        基于知识图谱连接度评估。
        """
        try:
            metrics = await self.kg_integration.calculate_network_value(asset_id)

            return {
                "asset_id": asset_id,
                "network_value": round(metrics.network_value, 2),
                "entity_count": metrics.entity_count,
                "scarcity_score": round(metrics.scarcity_score, 2),
                "connection_density": round(metrics.connection_density, 2),
                "interpretation": self._interpret_network_value(metrics),
            }

        except Exception as e:
            logger.error(f"Failed to get network value for {asset_id}: {e}")
            return {
                "asset_id": asset_id,
                "network_value": 0.0,
                "error": str(e),
            }

    def _interpret_network_value(self, metrics: NetworkValueMetrics) -> str:
        """解读网络价值"""
        if metrics.network_value >= 50:
            return "高网络价值，与知识图谱深度关联"
        elif metrics.network_value >= 20:
            return "中等网络价值，有一定关联度"
        else:
            return "低网络价值，建议增强知识图谱关联"

    # ========================================================================
    # 买方画像API
    # ========================================================================

    async def get_buyer_persona(self, buyer_id: int) -> BuyerPersona:
        """
        构建买方画像

        分析买方交易行为和偏好。
        """
        try:
            profile = await self.buyer_profiling.build_buyer_profile(buyer_id)

            # 细分买方类型
            total_spent = profile.get("transaction_history", {}).get("total_spent", 0)
            tx_count = profile.get("transaction_history", {}).get("total_count", 0)

            if total_spent > 10000:
                segment = "enterprise"
                buying_power = 0.9
            elif total_spent > 1000:
                segment = "researcher"
                buying_power = 0.6
            else:
                segment = "individual"
                buying_power = 0.3

            # 价格敏感度
            if tx_count > 0:
                avg_price = total_spent / tx_count
                if avg_price > 500:
                    price_sensitivity = "low"
                elif avg_price > 100:
                    price_sensitivity = "medium"
                else:
                    price_sensitivity = "high"
            else:
                price_sensitivity = "unknown"

            return BuyerPersona(
                buyer_id=buyer_id,
                segment=segment,
                buying_power=buying_power,
                preferred_data_types=[],  # 需从交易历史提取
                price_sensitivity=price_sensitivity,
                reputation_score=profile.get("reputation_score", 0.5),
                transaction_history=profile.get("transaction_history", {}),
            )

        except Exception as e:
            logger.error(f"Failed to get buyer persona for {buyer_id}: {e}")
            return BuyerPersona(
                buyer_id=buyer_id,
                segment="unknown",
                buying_power=0.0,
                preferred_data_types=[],
                price_sensitivity="unknown",
                reputation_score=0.0,
                transaction_history={},
            )

    async def find_similar_buyers(
        self,
        buyer_id: int,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        查找相似买方

        用于协同推荐。
        """
        try:
            persona = await self.get_buyer_persona(buyer_id)

            # 查询同类型的其他买方
            stmt = select(
                DataRightsTransactions.buyer_id,
                func.count(DataRightsTransactions.id).label("tx_count"),
            ).where(
                DataRightsTransactions.buyer_id != buyer_id,
            ).group_by(
                DataRightsTransactions.buyer_id,
            ).order_by(
                desc("tx_count")
            ).limit(limit)

            result = await self.db.execute(stmt)
            similar_buyers = [
                {
                    "buyer_id": row[0],
                    "transaction_count": row[1],
                    "similarity": "based_on_behavior",
                }
                for row in result.all()
            ]

            return similar_buyers

        except Exception as e:
            logger.error(f"Failed to find similar buyers for {buyer_id}: {e}")
            return []

    # ========================================================================
    # 推荐API
    # ========================================================================

    async def recommend_assets(
        self,
        buyer_id: int,
        limit: int = 10,
    ) -> List[AssetRecommendation]:
        """
        推荐资产

        基于买方画像和市场趋势推荐。
        """
        try:
            recommendations = await self.recommendation_engine.recommend_assets(
                buyer_id=buyer_id,
                limit=limit,
            )

            return [
                AssetRecommendation(
                    asset_id=r["asset_id"],
                    asset_name=r["asset_name"],
                    relevance_score=r["quality_score"],  # 简化
                    price=0.0,  # 需查询
                    reason="高质量数据资产",
                )
                for r in recommendations
            ]

        except Exception as e:
            logger.error(f"Failed to recommend assets for {buyer_id}: {e}")
            return []

    async def recommend_pricing_strategy(
        self,
        asset_id: str,
    ) -> Dict[str, Any]:
        """
        推荐定价策略

        基于市场分析给出定价建议。
        """
        try:
            # 竞争分析
            competition = await self.analyze_competition(asset_id)

            # 网络价值
            network = await self.get_network_value(asset_id)

            # 市场趋势
            market = await self.get_market_trend()

            # 综合建议
            if competition.market_position == "leader":
                strategy = "premium"
                price_adjustment = 1.2
            elif competition.market_position == "follower":
                strategy = "competitive"
                price_adjustment = 1.0
            else:
                strategy = "penetration"
                price_adjustment = 0.85

            return {
                "asset_id": asset_id,
                "recommended_strategy": strategy,
                "price_adjustment": price_adjustment,
                "market_position": competition.market_position,
                "network_value_boost": network.get("network_value", 0) * 0.1,
                "market_trend": market.trend,
                "rationale": f"基于{competition.market_position}定位建议{strategy}定价策略",
            }

        except Exception as e:
            logger.error(f"Failed to recommend pricing for {asset_id}: {e}")
            return {
                "asset_id": asset_id,
                "recommended_strategy": "unknown",
                "error": str(e),
            }

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def _get_top_assets(
        self,
        data_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """获取热门资产"""
        stmt = select(DataAssets).where(
            DataAssets.is_active == True,
            DataAssets.is_available_for_trade == True,
        ).order_by(
            desc(DataAssets.quality_overall_score)
        ).limit(limit)

        if data_type:
            stmt = stmt.where(DataAssets.data_type == data_type)

        result = await self.db.execute(stmt)
        assets = result.scalars().all()

        return [
            {
                "asset_id": a.asset_id,
                "asset_name": a.asset_name,
                "quality_score": a.quality_overall_score,
            }
            for a in assets
        ]
