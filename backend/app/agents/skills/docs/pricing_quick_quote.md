---
skill_id: pricing_quick_quote
name: 快速定价建议
capability_type: skill
description: 对单个数据资产给出快速定价建议，返回公允价值、推荐价格及价格区间。适用于交易前预估、快速询价等场景。
executor: app.services.skills.pricing_skill:PricingSkill.calculate_quick_price
model: deepseek-chat
color: blue
tools: []
skills: []
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产唯一标识
    rights_types:
      type: array
      items:
        type: string
        enum: [usage, analysis, derivative, sub_license]
      default:
        - usage
        - analysis
      description: 权益类型列表，决定定价范围
    duration_days:
      type: integer
      minimum: 1
      maximum: 3650
      default: 365
      description: 授权使用天数
  required:
    - asset_id
output_summary: 返回 fair_value（公允价值）、recommended（推荐价格）、price_range（价格区间）和定价因子摘要
examples:
  - input:
      asset_id: "asset_123"
      rights_types: ["usage", "analysis"]
      duration_days: 365
    output:
      fair_value: 1500.0
      price_range:
        min: 1200.0
        recommended: 1500.0
        max: 1950.0
      currency: "CNY"
      factors_summary:
        base_value: 1000.0
        quality_multiplier: 1.5
        scarcity_multiplier: 1.2
  - input:
      asset_id: "asset_456"
      rights_types: ["usage"]
    output:
      fair_value: 500.0
      price_range:
        min: 400.0
        recommended: 500.0
        max: 650.0
      currency: "CNY"
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: pricing
---

# 何时使用本 Skill

## 触发条件
- 用户询问某个数据资产的价格
- 交易前需要价格预估
- 需要快速了解资产价值区间
- 买方想判断报价是否合理

## 排除条件
- 不要用于批量资产组合定价（超过 10 个资产应使用批量接口）
- 不要用于最终交易定价（最终结果需人工确认）
- 不要用于非数据资产的定价

# 输入参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `asset_id` | string | 是 | - | 目标资产唯一标识 |
| `rights_types` | string[] | 否 | `["usage", "analysis"]` | 权益类型，影响价格倍数 |
| `duration_days` | integer | 否 | `365` | 授权期限（天），范围 1-3650 |

### 权益类型说明

| 类型 | 含义 | 价格影响 |
|------|------|----------|
| `usage` | 基础使用权 | 基准价格 |
| `analysis` | 分析权 | +20%~50% |
| `derivative` | 衍生权 | +50%~100% |
| `sub_license` | 再许可权 | +100%~200% |

# 执行规则

1. 必须提供有效的 `asset_id`，找不到资产时返回估算值并标记 `is_estimate`
2. 定价基于动态定价引擎，考虑质量、稀缺性、网络价值、市场需求等因子
3. 返回的价格区间中，`recommended` 是最适合作为谈判起点的价格
4. 如果引擎计算失败，返回兜底价格（fair_value=100, price_range 80-130）并包含 `error` 字段

# 输出格式

```json
{
  "fair_value": 1500.0,
  "price_range": {
    "min": 1200.0,
    "recommended": 1500.0,
    "max": 1950.0
  },
  "currency": "CNY",
  "factors_summary": {
    "base_value": 1000.0,
    "quality_multiplier": 1.5,
    "scarcity_multiplier": 1.2
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `fair_value` | float | 公允价值（核心参考价） |
| `price_range.min` | float | 最低可接受价 |
| `price_range.recommended` | float | 推荐谈判起点 |
| `price_range.max` | float | 最高可接受价 |
| `currency` | string | 货币单位，固定为 CNY |
| `factors_summary` | object | 定价因子摘要 |
| `is_estimate` | boolean | 是否为估算值（引擎失败时出现） |
| `error` | string | 错误信息（失败时出现） |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `ServiceError: Asset not found` | 资产 ID 不存在 | 检查 asset_id 是否正确，或返回兜底价格 |
| `fair_value` 为 100（兜底值） | 定价引擎异常 | 告知用户价格为估算值，建议人工复核 |
| `price_range` 异常宽 | 数据质量或稀缺性因子极端 | 结合 `factors_summary` 解释原因 |
