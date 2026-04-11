"""
Phase 2 Pricing Module Usage Example

展示如何使用新的定价模块
"""

import asyncio
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

# 导入新模块
from app.services.pricing import (
    LineagePricingEngine,
    DeepFMFeatureFusion,
    PricingPredictor,
    ThreeTierPriceGenerator,
    PriceThresholds,
)
from app.services.pricing.pricing_service import UnifiedPricingService, PricingRecommendation
from app.services.pricing.enhanced_pricing_skill import EnhancedPricingSkill, EnhancedPriceSuggestion


async def example_lineage_pricing(db: AsyncSession):
    """血缘驱动定价示例"""
    print("=" * 60)
    print("Lineage-Driven Pricing Example")
    print("=" * 60)

    # 1. 创建引擎
    engine = LineagePricingEngine(db)

    # 2. 分析血缘定价特征
    asset_id = "asset_001"
    # features = await engine.analyze_lineage_for_pricing(asset_id)

    # 模拟特征
    from app.services.pricing.lineage.lineage_pricing_engine import LineagePricingFeatures
    features = LineagePricingFeatures(
        lineage_depth=3,
        lineage_completeness=0.85,
        upstream_quality_score=0.9,
        overall_lineage_quality=0.82,
        derivation_complexity=0.6,
        lineage_uniqueness=0.75,
        alternative_source_availability=0.3,
    )

    print(f"\nLineage Features for {asset_id}:")
    print(f"  Depth: {features.lineage_depth}")
    print(f"  Completeness: {features.lineage_completeness:.2f}")
    print(f"  Quality: {features.overall_lineage_quality:.2f}")
    print(f"  Quality Grade: {features.quality_grade.value}")

    # 3. 计算价格调整
    adjustment = engine.calculate_price_adjustment(features)
    print(f"\nPrice Adjustment:")
    print(f"  Factor: {adjustment['adjustment_factor']:.2f}")
    print(f"  Quality Premium: {adjustment['quality_premium']:.2%}")
    print(f"  Scarcity Premium: {adjustment['scarcity_premium']:.2%}")
    print(f"  Reasoning: {adjustment['reasoning']}")

    # 4. 应用到基础价格
    base_price = 1000.0
    adjusted_price = base_price * adjustment['adjustment_factor']
    print(f"\n  Base Price: ${base_price:.2f}")
    print(f"  Adjusted Price: ${adjusted_price:.2f}")


async def example_deepfm_fusion():
    """DeepFM特征融合示例"""
    print("\n" + "=" * 60)
    print("DeepFM Feature Fusion Example")
    print("=" * 60)

    from app.services.pricing.fusion.deepfm_fusion import MultiDimensionalFeatures

    # 1. 构造多维度特征
    features = MultiDimensionalFeatures(
        graph_embedding=np.random.randn(128).astype(np.float32),
        graph_topology=np.array([0.8, 0.7, 0.6, 0.5, 0.9]),  # network, scarcity, centrality, density, norm
        lineage_features=np.array([0.85, 0.9, 0.1, 0.8, 0.2, 0.15, 0.6, 0.75, 0.3, 0.82]),
        quality_dimensions=np.array([0.85, 0.9, 0.8, 0.75, 0.9, 0.85]),
        market_dynamics=np.array([0.6, 0.4, 0.0, 0.2, 0.1, 0.3, 0.5, 0.6]),
        comparable_prices=np.array([0.8, 0.9, 0.85, 0.75, 0.9, 0.8, 0.85, 0.9]),
        rights_features=np.array([1.0, 0.5, 0.0, 0.0, 0.5, 0.5, 0.0, 0.0]),
    )

    print(f"\nFeature Dimensions:")
    for name, value in features.to_dict().items():
        print(f"  {name}: {len(value)}-dim")

    print(f"\nTotal fused dimension: {len(features.concat_all())}")

    # 2. 使用模型预测（简化示例，实际需要加载训练好的模型）
    print("\n  [Note: Actual prediction requires trained model]")


async def example_three_tier_prices():
    """三档价格阈值示例"""
    print("\n" + "=" * 60)
    print("Three-Tier Price Threshold Example")
    print("=" * 60)

    from app.services.pricing.thresholds.three_tier_generator import (
        PriceDistributionEstimator,
        ConfidenceBasedSelector,
    )

    # 1. 从历史交易拟合分布
    estimator = PriceDistributionEstimator()

    # 模拟历史交易
    historical_prices = [80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130, 140]

    thresholds = estimator.fit(historical_prices)

    print(f"\nPrice Distribution Fitted:")
    print(f"  Type: {thresholds.distribution_type.value}")
    print(f"  Sample Size: {thresholds.sample_size}")
    print(f"  Goodness of Fit: {thresholds.goodness_of_fit:.3f}")

    print(f"\nThree-Tier Thresholds:")
    print(f"  Conservative (P90): ${thresholds.conservative:.2f}")
    print(f"  Moderate (P50): ${thresholds.moderate:.2f}")
    print(f"  Aggressive (P10): ${thresholds.aggressive:.2f}")

    # 2. 基于置信度选择价格
    selector = ConfidenceBasedSelector()

    confidence_scores = {
        "graph": 0.85,
        "lineage": 0.80,
        "quality": 0.75,
        "market": 0.60,
    }

    overall_confidence = sum(confidence_scores.values()) / len(confidence_scores)

    selection = selector.select_price(
        thresholds,
        overall_confidence,
        confidence_scores,
        risk_tolerance="medium",
    )

    print(f"\nConfidence-Based Selection:")
    print(f"  Overall Confidence: {selection['confidence']:.2f}")
    print(f"  Selected Tier: {selection['selected_tier']}")
    print(f"  Selected Price: ${selection['selected_price']:.2f}")
    print(f"  Reasoning: {selection['reasoning']}")


async def example_unified_service(db: AsyncSession):
    """统一定价服务示例"""
    print("\n" + "=" * 60)
    print("Unified Pricing Service Example")
    print("=" * 60)

    # 创建服务
    service = UnifiedPricingService(db)

    # 模拟定价请求
    asset_id = "asset_001"

    print(f"\nCalculating price for {asset_id}...")

    # 模拟结果
    recommendation = PricingRecommendation(
        asset_id=asset_id,
        conservative_price=125.0,
        moderate_price=100.0,
        aggressive_price=75.0,
        recommended_price=100.0,
        recommended_tier="moderate",
        overall_confidence=0.82,
        confidence_breakdown={
            "graph": 0.85,
            "lineage": 0.80,
            "quality": 0.78,
            "market": 0.65,
        },
        price_adjustments={
            "lineage_premium": 0.05,
            "scarcity_premium": 0.08,
        },
        adjustment_reasoning="优秀血缘质量 + 高稀缺性",
        pricing_strategy="competitive",
        negotiation_strategy={
            "strategy": "cooperative",
            "walk_away_price": 70.0,
            "target_price": 100.0,
        },
        feature_summary={
            "graph": {"network_value": 75.0, "scarcity": 0.8},
            "lineage": {"quality": "A"},
        },
    )

    print(f"\nPricing Recommendation:")
    print(f"  Three-Tier Prices:")
    print(f"    Conservative: ${recommendation.conservative_price:.2f}")
    print(f"    Moderate: ${recommendation.moderate_price:.2f}")
    print(f"    Aggressive: ${recommendation.aggressive_price:.2f}")
    print(f"  Recommended: ${recommendation.recommended_price:.2f} ({recommendation.recommended_tier})")
    print(f"  Confidence: {recommendation.overall_confidence:.2f}")
    print(f"  Strategy: {recommendation.pricing_strategy}")


async def example_enhanced_skill(db: AsyncSession):
    """增强版PricingSkill示例"""
    print("\n" + "=" * 60)
    print("Enhanced Pricing Skill Example")
    print("=" * 60)

    skill = EnhancedPricingSkill(db)

    # 获取增强版价格建议
    # suggestion = await skill.get_enhanced_price_suggestion("asset_001")

    # 模拟结果
    suggestion = EnhancedPriceSuggestion(
        fair_value=100.0,
        min_price=75.0,
        recommended_price=100.0,
        max_price=125.0,
        currency="CNY",
        factors={},
        confidence=0.82,
        reasoning="优秀血缘质量 + 高网络价值",
        three_tier_prices={
            "conservative": 125.0,
            "moderate": 100.0,
            "aggressive": 75.0,
        },
        selected_tier="moderate",
        confidence_breakdown={
            "graph": 0.85,
            "lineage": 0.80,
            "quality": 0.78,
        },
    )

    print(f"\nEnhanced Price Suggestion:")
    print(f"  Conservative: ${suggestion.max_price:.2f}")
    print(f"  Moderate: ${suggestion.recommended_price:.2f}")
    print(f"  Aggressive: ${suggestion.min_price:.2f}")
    print(f"  Selected Tier: {suggestion.selected_tier}")
    print(f"  Confidence: {suggestion.confidence:.2f}")
    print(f"  Reasoning: {suggestion.reasoning}")

    # 协商建议
    print("\n  Negotiation Advice:")
    advice = skill._advise_seller_with_tiers(
        offer=95.0,
        tiers=suggestion.three_tier_prices,
        confidence=suggestion.confidence,
        context={"round": 2},
    )
    print(f"    Current Offer: $95.00")
    print(f"    Action: {advice['action']}")
    print(f"    Reasoning: {advice['reasoning']}")


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("Phase 2: Lineage-Driven Dynamic Pricing Examples")
    print("=" * 60)

    # 模拟数据库会话
    class MockDB:
        pass

    db = MockDB()

    await example_lineage_pricing(db)
    await example_deepfm_fusion()
    await example_three_tier_prices()
    await example_unified_service(db)
    await example_enhanced_skill(db)

    print("\n" + "=" * 60)
    print("All Phase 2 examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
