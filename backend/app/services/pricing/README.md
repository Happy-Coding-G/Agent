# Phase 2: 数据血缘驱动的动态定价系统

基于Phase 1的图嵌入能力，实现完整的血缘驱动动态定价系统。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    血缘驱动动态定价系统 (Phase 2)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐       │
│  │   图特征 (GNN)     │  │   血缘特征分析     │  │   质量/市场特征    │       │
│  │   128-dim emb     │  │   完整性/风险/价值 │  │   多维度评分      │       │
│  └─────────┬─────────┘  └─────────┬─────────┘  └─────────┬─────────┘       │
│            │                      │                      │                  │
│            └──────────────────────┼──────────────────────┘                  │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    DeepFM 多维度特征融合网络                           │   │
│  │                                                                     │   │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │   │
│  │   │   FM组件          │  │   Deep组件        │  │   多任务输出      │ │   │
│  │   │   低阶特征交互    │  │   高阶非线性学习  │  │   价格+置信度    │ │   │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘ │   │
│  │                                                                     │   │
│  │   输入: 173-dim (128+5+10+6+8+8+8)                                  │   │
│  │   输出: 基础价格 + 价格sigma + 成交概率分布 + 稀缺性 + 质量预测      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    三档价格阈值生成器                                  │   │
│  │                                                                     │   │
│  │   分布拟合: 对数正态 / Gamma / Weibull / 核密度估计                   │   │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │   │
│  │   │ 保守价 (P90)     │  │ 适中价 (P50)     │  │ 激进价 (P10)     │ │   │
│  │   │ ~10%成交概率     │  │ ~50%成交概率     │  │ ~90%成交概率     │ │   │
│  │   │ 卖方优势定价     │  │ 公允价值定价     │  │ 快速成交定价     │ │   │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    置信度加权选择器                                    │   │
│  │                                                                     │   │
│  │   输入: 三档价格 + 各维度置信度 + 风险偏好                            │   │
│  │   输出: 推荐价格 + 策略建议 + 博弈参数                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 模块说明

### 1. 血缘定价引擎 (`lineage/`)

**LineagePricingEngine**
- 血缘完整性评分
- 质量传播分析 (QualityPropagationModel)
- 风险评估 (RiskAssessmentModel)
- 稀缺性计算

**LineagePricingFeatures**
```python
features = LineagePricingFeatures(
    lineage_completeness=0.85,      # 血缘完整度
    upstream_quality_score=0.90,    # 上游质量
    overall_lineage_quality=0.82,   # 综合质量
    upstream_risk_score=0.20,       # 上游风险
    derivation_complexity=0.60,     # 派生复杂度
    lineage_uniqueness=0.75,        # 独特性
    alternative_source_availability=0.30,  # 替代源可用性
)
```

### 2. 特征融合网络 (`fusion/`)

**DeepFMFeatureFusion**
- FM组件：捕获特征间低阶交互
- Deep组件：DNN学习高阶非线性交互
- 输入维度：173-dim (128图 + 5拓扑 + 10血缘 + 6质量 + 16市场 + 8权益)

**MultiTaskPricingHead**
- 基础价格预测 (mu)
- 价格不确定性 (sigma)
- 成交概率分布 (P10/P50/P90概率)
- 稀缺性分类
- 质量评分预测

### 3. 价格阈值生成 (`thresholds/`)

**PriceDistributionEstimator**
- 支持多种分布：对数正态、Gamma、Weibull、正态
- 自动分布选择（基于AIC/BIC）
- 加权分位数计算

**ThreeTierPriceGenerator**
- 整合特征、可比交易、置信度
- 生成三档价格阈值
- 提供策略建议

### 4. 统一定价服务 (`pricing_service.py`)

**UnifiedPricingService**
- 端到端定价流程
- 批量定价支持
- 回退机制

### 5. 增强版Skill (`enhanced_pricing_skill.py`)

**EnhancedPricingSkill**
- 继承原PricingSkill
- 三档价格输出
- 置信度分解
- 基于三档价格的协商建议

## 使用示例

### 基础用法

```python
from app.services.pricing import LineagePricingEngine, ThreeTierPriceGenerator

# 1. 血缘分析
engine = LineagePricingEngine(db)
lineage_features = await engine.analyze_lineage_for_pricing("asset_001")

# 2. 计算调整
adjustment = engine.calculate_price_adjustment(lineage_features)
adjusted_price = base_price * adjustment["adjustment_factor"]

# 3. 三档价格生成
generator = ThreeTierPriceGenerator()
result = await generator.generate(
    asset_id="asset_001",
    comparable_transactions=transactions,
    confidence_scores={"graph": 0.85, "lineage": 0.80},
)
```

### 增强版Skill

```python
from app.services.pricing.enhanced_pricing_skill import EnhancedPricingSkill

skill = EnhancedPricingSkill(db)

# 获取增强版价格建议
suggestion = await skill.get_enhanced_price_suggestion("asset_001")

print(f"三档价格:")
print(f"  保守: ${suggestion.max_price}")
print(f"  适中: ${suggestion.recommended_price}")
print(f"  激进: ${suggestion.min_price}")

print(f"置信度分解:")
for dim, conf in suggestion.confidence_breakdown.items():
    print(f"  {dim}: {conf:.2f}")

# 协商建议
advice = await skill.advise_negotiation_with_tiers(
    asset_id="asset_001",
    current_offer=95.0,
    is_seller=True,
)
```

### 统一定价服务

```python
from app.services.pricing.pricing_service import get_pricing_service

service = get_pricing_service(db)
recommendation = await service.calculate_price("asset_001")

print(f"推荐价格: ${recommendation.recommended_price}")
print(f"策略: {recommendation.pricing_strategy}")
print(f"谈判策略: {recommendation.negotiation_strategy}")
```

## 配置参数

### DeepFM模型
```python
config = {
    "continuous_dim": 173,
    "embed_dim": 16,
    "mlp_dims": [256, 128, 64],
    "dropout": 0.3,
    "use_fm": True,
    "use_deep": True,
}
```

### 置信度阈值
```python
selector = ConfidenceBasedSelector(
    confidence_threshold_high=0.8,  # 高置信度阈值
    confidence_threshold_low=0.5,   # 低置信度阈值
)
```

## 特征维度

| 特征域 | 维度 | 说明 |
|--------|------|------|
| Graph Embedding | 128 | GNN图嵌入 |
| Graph Topology | 5 | 网络价值、稀缺性、中心性、密度、范数 |
| Lineage | 10 | 完整性、上游质量、衰减、溯源、风险等 |
| Quality | 6 | 完整性、准确性、时效性、一致性、唯一性、总体 |
| Market | 16 | 需求、竞争、趋势、波动、季节性等 |
| Rights | 8 | 使用、分析、衍生、转售、期限等 |
| **Total** | **173** | 融合输入维度 |

## 输出指标

### 价格相关
- **三档价格**: Conservative/Moderate/Aggressive
- **价格分布**: mu, sigma, 分布类型
- **置信区间**: 95% CI

### 概率相关
- **成交概率**: P10/P50/P90对应的成交概率
- **分布拟合度**: Goodness of fit

### 策略相关
- **定价策略**: premium/competitive/penetration/uncertain
- **谈判策略**: firm/cooperative/flexible
- **让步范围**: max/min/target

## 集成关系

```
EnhancedPricingSkill (新增)
    ├── PricingSkill (继承)
    ├── UnifiedPricingService
    │   ├── GNNPricingIntegration (Phase 1)
    │   ├── LineagePricingEngine
    │   ├── DeepFMFeatureFusion
    │   └── ThreeTierPriceGenerator
    └── LineagePricingEngine
```

## 下一步 (Phase 3)

1. **Agent博弈模块**: 强化学习协商策略
2. **让步曲线优化**: 基于时间压力和替代方案
3. **对手建模**: 在线学习买方行为模式
4. **实时定价**: 流式数据驱动的动态调价

## 参考

- DeepFM: [DeepFM: A Factorization-Machine based Neural Network for CTR Prediction](https://arxiv.org/abs/1703.04247)
- Price Optimization: [Dynamic Pricing in Competitive Markets](https://arxiv.org/abs/2001.00162)
