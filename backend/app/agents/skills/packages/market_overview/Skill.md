---
skill_id: market_overview
name: 市场概览
capability_type: skill
description: 返回整体市场概览统计，包括总交易量、活跃资产数和类型分布。适用于运营汇总、市场总览、图表前置数据获取。
executor: app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview
model: deepseek-chat
color: purple
tools: []
skills: []
input_schema:
  type: object
  properties: {}
output_summary: 返回 total_transactions、active_assets、type_distribution 和生成时间
examples:
  - input: {}
    output:
      total_transactions: 1280
      active_assets: 450
      type_distribution:
        - type: "medical"
          count: 120
        - type: "financial"
          count: 85
        - type: "sensor"
          count: 245
      generated_at: "2026-04-21T10:00:00Z"
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: market
---

# 何时使用本 Skill

## 触发条件
- 用户询问市场整体情况
- 需要运营汇总数据
- 仪表盘/图表需要市场概览数据
- 交易前了解市场活跃度

## 排除条件
- 不要用于特定资产的分析（使用 pricing_quick_quote 或 market_trend）
- 不要用于竞争分析（使用 analyze_competition 接口）
- 不要用于买方画像（使用 get_buyer_persona 接口）

# 输入参数说明

本 skill 无需输入参数，直接调用即可获取全局市场统计。

# 执行规则

1. 统计所有已完成交易的数量
2. 统计当前可交易的活跃资产数量
3. 按 `data_type` 分组统计资产类型分布
4. 返回结果包含 `generated_at` 时间戳

# 输出格式

```json
{
  "total_transactions": 1280,
  "active_assets": 450,
  "type_distribution": [
    {"type": "medical", "count": 120},
    {"type": "financial", "count": 85},
    {"type": "sensor", "count": 245}
  ],
  "generated_at": "2026-04-21T10:00:00Z"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_transactions` | integer | 历史总交易数（已完成状态） |
| `active_assets` | integer | 当前可交易的活跃资产数 |
| `type_distribution` | object[] | 资产类型分布，每项包含 `type` 和 `count` |
| `generated_at` | string | 数据生成时间（ISO 8601 格式） |
| `error` | string | 错误信息（查询失败时出现） |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `active_assets` 为 0 | 无可交易资产 | 检查资产上架状态 |
| `type_distribution` 为空 | 资产无类型标签 | 建议完善资产元数据 |
| 查询失败返回 error | 数据库异常 | 稍后重试或联系管理员 |
