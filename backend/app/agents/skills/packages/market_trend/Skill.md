---
skill_id: market_trend
name: 市场趋势分析
capability_type: skill
description: 分析某类资产的市场趋势，返回交易趋势、均价、变化比例和热门资产。适用于趋势判断、价格解释、图表查询。
executor: app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_trend
model: deepseek-chat
color: cyan
tools: []
skills: []
input_schema:
  type: object
  properties:
    data_type:
      type: string
      description: 数据类型过滤，如 medical、financial、sensor。不传则统计全市场。
    days:
      type: integer
      minimum: 1
      maximum: 365
      default: 30
      description: 统计时间窗口（天）
  required: []
output_summary: 返回 trend、avg_price、price_change_pct、top_assets 和交易统计
examples:
  - input:
      data_type: "medical"
      days: 30
    output:
      data_type: "medical"
      transaction_count: 45
      avg_price: 2500.0
      price_change_pct: 0.0
      trend: "stable"
      top_assets:
        - asset_id: "med_001"
          asset_name: "医疗影像数据集A"
          quality_score: 0.92
  - input:
      days: 7
    output:
      data_type: "all"
      transaction_count: 120
      avg_price: 1800.0
      price_change_pct: 0.0
      trend: "stable"
      top_assets:
        - asset_id: "fin_001"
          asset_name: "金融行情数据"
          quality_score: 0.88
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: market
---

# 何时使用本 Skill

## 触发条件
- 用户想了解某类资产的价格走势
- 判断市场热度
- 交易前参考同类资产的交易情况
- 需要热门资产推荐

## 排除条件
- 不要用于整体市场统计（使用 market_overview skill）
- 不要用于特定资产的竞争分析
- 趋势判断基于历史数据，不构成投资建议

# 输入参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `data_type` | string | 否 | - | 数据类型过滤，如 medical、financial、sensor |
| `days` | integer | 否 | `30` | 统计时间窗口（天），范围 1-365 |

# 执行规则

1. 统计指定时间窗口内的交易数量和平均价格
2. 获取该类型下质量评分最高的热门资产
3. 趋势判断目前为简化实现，返回 "stable"，实际价格变化百分比需基于历史对比
4. 不传 `data_type` 时统计全市场数据

# 输出格式

```json
{
  "data_type": "medical",
  "transaction_count": 45,
  "avg_price": 2500.0,
  "price_change_pct": 0.0,
  "trend": "stable",
  "top_assets": [
    {
      "asset_id": "med_001",
      "asset_name": "医疗影像数据集A",
      "quality_score": 0.92
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `data_type` | string | 数据类型，未指定时为 "all" |
| `transaction_count` | integer | 时间窗口内交易数量 |
| `avg_price` | float | 平均成交价格 |
| `price_change_pct` | float | 价格变化百分比（当前为 0，需历史对比） |
| `trend` | string | 趋势判断：up/down/stable/unknown |
| `top_assets` | object[] | 热门资产列表，每项含 asset_id、asset_name、quality_score |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `transaction_count` 为 0 | 该类型近期无交易 | 扩大时间窗口或换类型查询 |
| `avg_price` 为 0 | 无成交记录 | 结合 market_overview 查看是否有活跃资产 |
| `trend` 始终为 "stable" | 简化实现 | 告知用户趋势功能正在完善 |
