"""
Advanced Pricing Module - Phase 2: Lineage-Driven Dynamic Pricing

数据血缘驱动的动态定价系统

提供：
1. 血缘特征提取与建模
2. 多维度特征融合 (DeepFM)
3. 三档价格阈值生成
4. 置信度评估机制
5. Agent博弈策略支持
"""

from app.services.pricing.lineage.lineage_pricing_engine import (
    LineagePricingEngine,
    LineagePricingFeatures,
    QualityPropagationModel,
)
from app.services.pricing.fusion.deepfm_fusion import (
    DeepFMFeatureFusion,
    MultiDimensionalFeatures,
    PricingPredictor,
)
from app.services.pricing.thresholds.three_tier_generator import (
    ThreeTierPriceGenerator,
    PriceThresholds,
    PriceDistributionEstimator,
)

__all__ = [
    # Lineage
    "LineagePricingEngine",
    "LineagePricingFeatures",
    "QualityPropagationModel",
    # Fusion
    "DeepFMFeatureFusion",
    "MultiDimensionalFeatures",
    "PricingPredictor",
    # Thresholds
    "ThreeTierPriceGenerator",
    "PriceThresholds",
    "PriceDistributionEstimator",
]
