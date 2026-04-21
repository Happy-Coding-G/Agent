---
skill_id: lineage_impact
name: 血缘影响分析
capability_type: skill
description: 分析某资产变更对上下游的影响范围，返回上游/下游数量、影响得分和风险等级。适用于变更影响分析、发布前风险评估。
executor: app.services.skills.lineage_skill:DataLineageSkill.analyze_impact
model: deepseek-chat
color: orange
tools: []
skills: []
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产唯一标识
  required:
    - asset_id
output_summary: 返回 upstream_count、downstream_count、impact_score、risk_level 和 affected_assets 列表
examples:
  - input:
      asset_id: "asset_123"
    output:
      asset_id: "asset_123"
      upstream_count: 2
      downstream_count: 5
      total_impact_score: 0.8
      risk_level: "high"
      affected_assets:
        - asset_id: "asset_124"
          asset_name: "汇总报表A"
        - asset_id: "asset_125"
          asset_name: "预测模型B"
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: lineage
---

# 何时使用本 Skill

## 触发条件
- 计划修改某个资产前，评估影响范围
- 发布前风险评估
- 依赖梳理，了解资产的重要性
- 删除资产前确认是否有下游依赖

## 排除条件
- 不要用于血缘摘要查询（使用 lineage_summary skill）
- 不要用于质量评估
- 资产无下游时本 skill 仍然可用（risk_level 为 low）

# 输入参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asset_id` | string | 是 | 目标资产唯一标识 |

# 执行规则

1. 扫描资产的所有上游依赖（数据来源）和下游影响（依赖此数据的资产）
2. 根据下游数量计算影响得分和风险等级：
   - 0 个下游：`risk_level=low`, `impact_score=0.1`
   - 1-3 个下游：`risk_level=medium`, `impact_score=0.4`
   - 4+ 个下游：`risk_level=high`, `impact_score=0.8`
3. 返回所有受影响的下游资产列表
4. 如果扫描失败，返回全 0 值和 `risk_level="unknown"`

# 风险等级说明

| 风险等级 | 下游数量 | 建议动作 |
|----------|----------|----------|
| `low` | 0 | 变更影响可控 |
| `medium` | 1-3 | 需要通知相关方，评估兼容性 |
| `high` | 4+ | 必须进行兼容性测试，制定回滚方案 |

# 输出格式

```json
{
  "asset_id": "asset_123",
  "upstream_count": 2,
  "downstream_count": 5,
  "total_impact_score": 0.8,
  "risk_level": "high",
  "affected_assets": [
    {"asset_id": "asset_124", "name": "汇总报表A"},
    {"asset_id": "asset_125", "name": "预测模型B"}
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `asset_id` | string | 资产标识 |
| `upstream_count` | integer | 上游依赖数量 |
| `downstream_count` | integer | 下游影响数量 |
| `total_impact_score` | float | 影响得分，范围 0-1 |
| `risk_level` | string | 风险等级：low/medium/high/unknown |
| `affected_assets` | object[] | 受影响的下游资产列表 |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `risk_level` 为 "unknown" | 血缘扫描失败 | 检查资产是否存在，或手动评估影响 |
| `downstream_count` 远大于预期 | 资产被广泛使用 | 建议拆分资产或建立版本管理机制 |
| `affected_assets` 为空 | 无下游依赖 | 正常情况，说明资产为叶子节点 |
