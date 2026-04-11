"""
Enhanced Pricing Skill - 增强版定价Skill

继承并扩展原PricingSkill，集成Phase 1和Phase 2的所有功能：
- GNN图嵌入
- 血缘驱动定价
- DeepFM特征融合
- 三档价格阈值
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skills.pricing_skill import PricingSkill, PriceSuggestion, MarketAnalysis
from app.services.pricing.pricing_service import (
    UnifiedPricingService,
    get_pricing_service,
    PricingRecommendation,
)
from app.services.pricing.lineage.lineage_pricing_engine import LineagePricingEngine

logger = logging.getLogger(__name__)


@dataclass
class EnhancedPriceSuggestion(PriceSuggestion):
    """增强版价格建议"""
    # 继承原字段

    # 新增字段
    three_tier_prices: Dict[str, float] = None  # conservative/moderate/aggressive
    selected_tier: str = "moderate"
    graph_features: Dict[str, Any] = None
    lineage_features: Dict[str, Any] = None
    confidence_breakdown: Dict[str, float] = None
    negotiation_strategy: Dict[str, Any] = None

    def __post_init__(self):
        if self.three_tier_prices is None:
            self.three_tier_prices = {
                "conservative": self.max_price,
                "moderate": self.recommended_price,
                "aggressive": self.min_price,
            }
        if self.confidence_breakdown is None:
            self.confidence_breakdown = {"overall": self.confidence}


class EnhancedPricingSkill(PricingSkill):
    """
    增强版定价Skill

    在原有功能基础上增加：
    1. 三档价格阈值（保守/适中/激进）
    2. 图嵌入特征
    3. 血缘质量分析
    4. 置信度分解
    5. 博弈策略建议
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

        # 新增模块
        self.pricing_service = get_pricing_service(db)
        self.lineage_engine = LineagePricingEngine(db)

        logger.info("EnhancedPricingSkill initialized")

    async def get_enhanced_price_suggestion(
        self,
        asset_id: str,
        rights_request: Optional[Dict[str, Any]] = None,
        market_conditions: Optional[Dict[str, Any]] = None,
        seller_preferences: Optional[Dict[str, Any]] = None,
    ) -> EnhancedPriceSuggestion:
        """
        获取增强版价格建议

        完整的血缘驱动动态定价流程
        """
        try:
            # 使用统一定价服务
            recommendation = await self.pricing_service.calculate_price(
                asset_id=asset_id,
                rights_request=rights_request,
                market_conditions=market_conditions,
                seller_preferences=seller_preferences,
            )

            # 转换为EnhancedPriceSuggestion
            suggestion = EnhancedPriceSuggestion(
                fair_value=recommendation.moderate_price,
                min_price=recommendation.aggressive_price,
                recommended_price=recommendation.recommended_price,
                max_price=recommendation.conservative_price,
                currency="CNY",
                factors={
                    "graph_network_value": recommendation.feature_summary.get("graph", {}).get("network_value"),
                    "lineage_quality": recommendation.feature_summary.get("lineage", {}).get("overall_quality"),
                    "quality_score": recommendation.feature_summary.get("quality", {}).get("overall"),
                },
                confidence=recommendation.overall_confidence,
                reasoning=recommendation.adjustment_reasoning,
                # 新增字段
                three_tier_prices={
                    "conservative": recommendation.conservative_price,
                    "moderate": recommendation.moderate_price,
                    "aggressive": recommendation.aggressive_price,
                },
                selected_tier=recommendation.recommended_tier,
                graph_features=recommendation.feature_summary.get("graph"),
                lineage_features=recommendation.feature_summary.get("lineage"),
                confidence_breakdown=recommendation.confidence_breakdown,
                negotiation_strategy=recommendation.negotiation_strategy,
            )

            return suggestion

        except Exception as e:
            logger.exception(f"Enhanced pricing failed for {asset_id}: {e}")
            # 回退到基础定价
            basic = await self.get_price_suggestion(asset_id, rights_request, market_conditions)
            return EnhancedPriceSuggestion(
                fair_value=basic.fair_value,
                min_price=basic.min_price,
                recommended_price=basic.recommended_price,
                max_price=basic.max_price,
                currency=basic.currency,
                factors=basic.factors,
                confidence=basic.confidence * 0.8,  # 降低置信度
                reasoning=f"{basic.reasoning} (使用基础定价模型)",
                three_tier_prices={
                    "conservative": basic.max_price,
                    "moderate": basic.recommended_price,
                    "aggressive": basic.min_price,
                },
                selected_tier="moderate",
            )

    async def get_lineage_adjusted_price(
        self,
        asset_id: str,
        base_price: float,
    ) -> Dict[str, Any]:
        """
        获取血缘调整后的价格

        基于血缘特征对基础价格进行调整
        """
        # 分析血缘
        lineage_features = await self.lineage_engine.analyze_lineage_for_pricing(asset_id)

        # 计算调整
        adjustment = self.lineage_engine.calculate_price_adjustment(lineage_features)

        adjusted_price = base_price * adjustment["adjustment_factor"]

        return {
            "original_price": base_price,
            "adjusted_price": round(adjusted_price, 2),
            "adjustment_factor": adjustment["adjustment_factor"],
            "breakdown": {
                "quality_premium": adjustment["quality_premium"],
                "scarcity_premium": adjustment["scarcity_premium"],
                "risk_discount": adjustment["risk_discount"],
                "complexity_premium": adjustment["complexity_premium"],
            },
            "reasoning": adjustment["reasoning"],
            "lineage_quality": lineage_features.quality_grade.value,
        }

    async def advise_negotiation_with_tiers(
        self,
        asset_id: str,
        current_offer: float,
        is_seller: bool,
        negotiation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        基于三档价格的协商建议

        根据当前报价和三档阈值给出策略建议
        """
        # 获取三档价格
        suggestion = await self.get_enhanced_price_suggestion(asset_id)
        tiers = suggestion.three_tier_prices

        # 分析报价位置
        if is_seller:
            return self._advise_seller_with_tiers(
                current_offer, tiers, suggestion.confidence, negotiation_context
            )
        else:
            return self._advise_buyer_with_tiers(
                current_offer, tiers, suggestion.confidence, negotiation_context
            )

    def _advise_seller_with_tiers(
        self,
        offer: float,
        tiers: Dict[str, float],
        confidence: float,
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """卖方建议（基于三档价格）"""
        conservative = tiers["conservative"]
        moderate = tiers["moderate"]
        aggressive = tiers["aggressive"]

        round_num = context.get("round", 1) if context else 1

        # 报价评估
        if offer >= conservative * 0.95:
            return {
                "action": "accept",
                "confidence": 0.9,
                "reasoning": f"报价{offer}接近保守价{conservative:.2f}，建议接受",
                "suggested_response": "接受报价",
            }

        elif offer >= moderate:
            if confidence > 0.7 and round_num <= 3:
                return {
                    "action": "counter",
                    "suggested_price": round(conservative * 0.98, 2),
                    "confidence": 0.75,
                    "reasoning": f"报价合理但可争取更高，建议反报价",
                }
            else:
                return {
                    "action": "accept",
                    "confidence": 0.8,
                    "reasoning": "报价在合理范围内，建议接受",
                }

        elif offer >= aggressive:
            return {
                "action": "counter",
                "suggested_price": round(moderate * 1.05, 2),
                "confidence": 0.7,
                "reasoning": "报价偏低，建议反报价至适中区间",
            }

        else:
            return {
                "action": "counter",
                "suggested_price": round(moderate, 2),
                "confidence": 0.6,
                "reasoning": f"报价过低({offer} < 激进价{aggressive:.2f})，强烈建议反报价",
            }

    def _advise_buyer_with_tiers(
        self,
        offer: float,
        tiers: Dict[str, float],
        confidence: float,
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """买方建议（基于三档价格）"""
        conservative = tiers["conservative"]
        moderate = tiers["moderate"]
        aggressive = tiers["aggressive"]

        # 报价评估
        if offer <= aggressive * 1.05:
            return {
                "action": "accept",
                "confidence": 0.85,
                "reasoning": f"报价{offer}接近激进价{aggressive:.2f}，建议接受",
            }

        elif offer <= moderate:
            return {
                "action": "accept",
                "confidence": 0.75,
                "reasoning": "报价在合理范围内",
            }

        elif offer <= conservative:
            return {
                "action": "counter",
                "suggested_price": round(moderate * 0.95, 2),
                "confidence": 0.7,
                "reasoning": "报价偏高，建议压低",
            }

        else:
            return {
                "action": "reject",
                "suggested_price": round(conservative * 0.9, 2),
                "confidence": 0.6,
                "reasoning": f"报价过高({offer} > 保守价{conservative:.2f})，建议重新报价",
            }


# 便捷函数
async def get_enhanced_price(
    db: AsyncSession,
    asset_id: str,
    **kwargs,
) -> EnhancedPriceSuggestion:
    """便捷函数：获取增强版价格建议"""
    skill = EnhancedPricingSkill(db)
    return await skill.get_enhanced_price_suggestion(asset_id, **kwargs)
