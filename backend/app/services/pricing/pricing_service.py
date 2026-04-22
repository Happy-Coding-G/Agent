"""
Unified Pricing Service - 统一定价服务

整合所有定价模块：
1. GNN图嵌入
2. 血缘分析
3. 特征融合（DeepFM）
4. 三档价格阈值生成
5. 博弈策略建议

提供端到端的定价决策支持
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
import numpy as np

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.gnn.pricing_integration import (
    GNNPricingIntegration,
    get_gnn_pricing_integration,
)
from app.services.pricing.lineage.lineage_pricing_engine import (
    LineagePricingEngine,
    LineagePricingFeatures,
)
from app.services.pricing.fusion.deepfm_fusion import (
    DeepFMFeatureFusion,
    MultiDimensionalFeatures,
    PricingPredictor,
    FeatureFusionPipeline,
)
from app.services.pricing.thresholds.three_tier_generator import (
    ThreeTierPriceGenerator,
    PriceThresholds,
)

logger = logging.getLogger(__name__)


@dataclass
class PricingRecommendation:
    """
    定价建议结果
    """
    asset_id: str

    # 三档价格
    conservative_price: float    # P10
    moderate_price: float        # P50
    aggressive_price: float      # P90

    # 推荐价格
    recommended_price: float
    recommended_tier: str

    # 置信度
    overall_confidence: float
    confidence_breakdown: Dict[str, float]

    # 调整说明
    price_adjustments: Dict[str, float]
    adjustment_reasoning: str

    # 策略建议
    pricing_strategy: str
    negotiation_strategy: Dict[str, Any]

    # 特征摘要
    feature_summary: Dict[str, Any]

    # 元数据
    generated_at: datetime = None
    model_version: str = "1.0.0"

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "asset_id": self.asset_id,
            "prices": {
                "conservative": round(self.conservative_price, 2),
                "moderate": round(self.moderate_price, 2),
                "aggressive": round(self.aggressive_price, 2),
                "recommended": round(self.recommended_price, 2),
                "tier": self.recommended_tier,
            },
            "confidence": {
                "overall": round(self.overall_confidence, 3),
                "breakdown": {
                    k: round(v, 3) for k, v in self.confidence_breakdown.items()
                },
            },
            "adjustments": self.price_adjustments,
            "reasoning": self.adjustment_reasoning,
            "strategy": self.pricing_strategy,
            "negotiation": self.negotiation_strategy,
            "features": self.feature_summary,
            "generated_at": self.generated_at.isoformat(),
            "model_version": self.model_version,
        }


class UnifiedPricingService:
    """
    统一定价服务

    整合Phase 1和Phase 2的所有模块
    """

    def __init__(
        self,
        db: AsyncSession,
        gnn_integration: Optional[GNNPricingIntegration] = None,
        lineage_engine: Optional[LineagePricingEngine] = None,
        price_generator: Optional[ThreeTierPriceGenerator] = None,
        feature_fusion: Optional[PricingPredictor] = None,
    ):
        self.db = db

        # 各模块初始化
        self.gnn_integration = gnn_integration or get_gnn_pricing_integration()
        self.lineage_engine = lineage_engine or LineagePricingEngine(db)
        self.price_generator = price_generator or ThreeTierPriceGenerator()
        self.feature_fusion = feature_fusion

        # 特征融合管道
        self.feature_pipeline = FeatureFusionPipeline(
            gnn_embedder=self.gnn_integration.embedder if self.gnn_integration else None,
            lineage_engine=self.lineage_engine,
        )

    async def calculate_price(
        self,
        asset_id: str,
        rights_request: Optional[Dict[str, Any]] = None,
        market_conditions: Optional[Dict[str, Any]] = None,
        seller_preferences: Optional[Dict[str, Any]] = None,
    ) -> PricingRecommendation:
        """
        计算资产价格

        完整的定价流程：
        1. 特征提取（图、血缘、质量、市场）
        2. 特征融合
        3. 价格分布估计
        4. 三档阈值生成
        5. 置信度加权选择
        6. 策略建议

        Args:
            asset_id: 资产ID
            rights_request: 权益请求（影响价格）
            market_conditions: 市场条件
            seller_preferences: 卖方偏好

        Returns:
            PricingRecommendation
        """
        try:
            # Step 1: 提取所有维度特征
            logger.info(f"Extracting features for asset {asset_id}")
            features = await self._extract_all_features(asset_id)

            # Step 2: 计算各维度置信度
            confidence_scores = self._calculate_confidence_scores(features)

            # Step 3: 获取可比交易
            comparable_tx = await self._get_comparable_transactions(asset_id)

            # Step 4: 生成三档价格
            price_result = await self.price_generator.generate(
                asset_id=asset_id,
                comparable_transactions=comparable_tx,
                confidence_scores=confidence_scores,
            )

            # Step 5: 基于特征融合的价格预测（如果有模型）
            if self.feature_fusion and features:
                ml_prediction = self.feature_fusion.predict_price_distribution(features)
                # 融合ML预测和统计阈值
                final_prices = self._fuse_predictions(
                    price_result["thresholds"],
                    ml_prediction,
                    confidence_scores,
                )
            else:
                final_prices = price_result["thresholds"]

            # Step 6: 计算价格调整
            adjustments = self._calculate_detailed_adjustments(
                features, price_result["adjustments"]
            )

            # Step 7: 生成策略建议
            strategy = self._recommend_pricing_strategy(features, price_result)
            negotiation = self._recommend_negotiation_strategy(
                final_prices, confidence_scores, seller_preferences
            )

            # Step 8: 组装结果
            recommendation = PricingRecommendation(
                asset_id=asset_id,
                conservative_price=final_prices.get("conservative", 0),
                moderate_price=final_prices.get("moderate", 0),
                aggressive_price=final_prices.get("aggressive", 0),
                recommended_price=price_result["selection"]["selected_price"],
                recommended_tier=price_result["selection"]["selected_tier"],
                overall_confidence=price_result["confidence"]["overall"],
                confidence_breakdown=confidence_scores,
                price_adjustments=adjustments["factors"],
                adjustment_reasoning=adjustments["reasoning"],
                pricing_strategy=strategy,
                negotiation_strategy=negotiation,
                feature_summary=self._summarize_features(features),
            )

            return recommendation

        except Exception as e:
            logger.exception(f"Failed to calculate price for {asset_id}: {e}")
            return self._fallback_recommendation(asset_id)

    async def _extract_all_features(
        self,
        asset_id: str,
    ) -> Optional[MultiDimensionalFeatures]:
        """提取所有维度特征"""
        return await self.feature_pipeline.extract_all_features(asset_id)

    def _calculate_confidence_scores(
        self,
        features: Optional[MultiDimensionalFeatures],
    ) -> Dict[str, float]:
        """计算各维度置信度"""
        if features is None:
            return {
                "graph": 0.3,
                "lineage": 0.3,
                "quality": 0.5,
                "market": 0.4,
                "rights": 0.5,
            }

        scores = {}

        # 图特征置信度（基于嵌入范数）
        graph_norm = np.linalg.norm(features.graph_embedding)
        scores["graph"] = min(1.0, graph_norm / 15)

        # 血缘特征置信度（基于完整性）
        scores["lineage"] = features.lineage_features[0]  # lineage_completeness

        # 质量特征置信度
        scores["quality"] = features.quality_dimensions[-1]  # overall quality

        # 市场特征置信度
        scores["market"] = 0.6  # 默认中等

        # 权益特征置信度
        scores["rights"] = 0.7  # 通常较高

        return scores

    async def _get_comparable_transactions(
        self,
        asset_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """获取可比交易"""
        # 这里简化处理，实际应该查询交易数据库
        # 返回模拟数据
        return [
            {"price": 100.0, "similarity": 0.8, "days_ago": 30},
            {"price": 120.0, "similarity": 0.75, "days_ago": 60},
            {"price": 90.0, "similarity": 0.7, "days_ago": 90},
        ]

    def _fuse_predictions(
        self,
        thresholds: Dict,
        ml_prediction: Dict[str, Any],
        confidence_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """融合统计阈值和ML预测"""
        # 根据ML置信度决定融合权重
        ml_confidence = confidence_scores.get("graph", 0.5) * 0.5 + \
                       confidence_scores.get("lineage", 0.5) * 0.5

        # 融合权重
        w_stat = 1 - ml_confidence
        w_ml = ml_confidence

        # 融合各档价格
        fused = {
            "conservative": (
                w_stat * thresholds.get("conservative", 0) +
                w_ml * ml_prediction.get("conservative_price", 0)
            ),
            "moderate": (
                w_stat * thresholds.get("moderate", 0) +
                w_ml * ml_prediction.get("moderate_price", 0)
            ),
            "aggressive": (
                w_stat * thresholds.get("aggressive", 0) +
                w_ml * ml_prediction.get("aggressive_price", 0)
            ),
        }

        return fused

    def _calculate_detailed_adjustments(
        self,
        features: Optional[MultiDimensionalFeatures],
        base_adjustments: Dict[str, float],
    ) -> Dict[str, Any]:
        """计算详细的价格调整"""
        factors = dict(base_adjustments)
        reasons = []

        if features is not None:
            # 图特征调整
            network_value = features.graph_topology[0]  # network_value / 100
            if network_value > 0.7:
                factors["network_value_premium"] = (network_value - 0.5) * 0.2
                reasons.append(f"高网络价值({network_value:.2f})带来溢价")

            # 血缘特征调整
            lineage_quality = features.lineage_features[9]  # overall_lineage_quality
            if lineage_quality > 0.8:
                factors["lineage_quality_premium"] = 0.05
                reasons.append("优秀的血缘质量")
            elif lineage_quality < 0.4:
                factors["lineage_quality_discount"] = -0.10
                reasons.append("血缘质量不足")

            # 质量特征调整
            overall_quality = features.quality_dimensions[-1]
            factors["quality_adjustment"] = (overall_quality - 0.7) * 0.2

        return {
            "factors": factors,
            "reasoning": "; ".join(reasons) if reasons else "标准定价",
        }

    def _recommend_pricing_strategy(
        self,
        features: Optional[MultiDimensionalFeatures],
        price_result: Dict[str, Any],
    ) -> str:
        """推荐定价策略"""
        thresholds = price_result["thresholds"]
        selection = price_result["selection"]

        # 分析价格离散度
        price_spread = (
            thresholds.get("conservative", 100) -
            thresholds.get("aggressive", 60)
        ) / thresholds.get("moderate", 80)

        if price_spread > 0.5:
            return "uncertain"  # 不确定性高
        elif selection["selected_tier"] == "conservative":
            return "premium"
        elif selection["selected_tier"] == "aggressive":
            return "penetration"
        else:
            return "competitive"

    def _recommend_negotiation_strategy(
        self,
        prices: Dict[str, float],
        confidence: Dict[str, float],
        preferences: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """推荐协商策略"""
        overall_conf = (
            confidence.get("graph", 0.5) * 0.3 +
            confidence.get("lineage", 0.5) * 0.3 +
            confidence.get("quality", 0.5) * 0.2 +
            confidence.get("market", 0.5) * 0.2
        )

        # 让步空间
        concession_range = {
            "max": prices.get("conservative", 0),
            "min": prices.get("aggressive", 0),
            "initial": prices.get("moderate", 0),
        }

        # 策略选择
        if overall_conf > 0.8:
            strategy = "firm"  # 坚定策略
            tactics = ["anchoring", "limited_authority"]
        elif overall_conf > 0.5:
            strategy = "cooperative"
            tactics = ["principled_negotiation", "package_deal"]
        else:
            strategy = "flexible"
            tactics = ["concession_trading", "trial_proposals"]

        return {
            "concession_range": concession_range,
            "strategy": strategy,
            "tactics": tactics,
            "walk_away_price": prices.get("aggressive", 0) * 0.9,
            "target_price": prices.get("moderate", 0),
        }

    def _summarize_features(
        self,
        features: Optional[MultiDimensionalFeatures],
    ) -> Dict[str, Any]:
        """摘要特征信息"""
        if features is None:
            return {"status": "unavailable"}

        return {
            "graph": {
                "embedding_norm": float(np.linalg.norm(features.graph_embedding)),
                "network_value": float(features.graph_topology[0]),
                "scarcity": float(features.graph_topology[1]),
            },
            "lineage": {
                "completeness": float(features.lineage_features[0]),
                "overall_quality": float(features.lineage_features[9]),
            },
            "quality": {
                "overall": float(features.quality_dimensions[-1]),
            },
        }

    def _fallback_recommendation(self, asset_id: str) -> PricingRecommendation:
        """回退推荐（当所有方法失败时）"""
        return PricingRecommendation(
            asset_id=asset_id,
            conservative_price=100.0,
            moderate_price=80.0,
            aggressive_price=60.0,
            recommended_price=80.0,
            recommended_tier="moderate",
            overall_confidence=0.3,
            confidence_breakdown={"fallback": 0.3},
            price_adjustments={},
            adjustment_reasoning="使用默认价格（特征提取失败）",
            pricing_strategy="conservative",
            negotiation_strategy={
                "strategy": "cautious",
                "walk_away_price": 50.0,
            },
            feature_summary={"status": "error"},
        )

    async def batch_calculate(
        self,
        asset_ids: List[str],
        batch_size: int = 32,
    ) -> Dict[str, PricingRecommendation]:
        """批量计算价格"""
        results = {}

        for i in range(0, len(asset_ids), batch_size):
            batch = asset_ids[i:i + batch_size]

            tasks = [self.calculate_price(aid) for aid in batch]
            batch_results = await asyncio.gather(*tasks)

            for aid, result in zip(batch, batch_results):
                results[aid] = result

        return results


import asyncio


# 全局服务实例
_pricing_service: Optional[UnifiedPricingService] = None


def get_pricing_service(db: AsyncSession) -> UnifiedPricingService:
    """获取全局定价服务实例"""
    global _pricing_service
    if _pricing_service is None:
        _pricing_service = UnifiedPricingService(db)
    return _pricing_service
