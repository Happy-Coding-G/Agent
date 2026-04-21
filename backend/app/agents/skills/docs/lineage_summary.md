---
skill_id: lineage_summary
name: 血缘摘要
capability_type: skill
description: 获取资产的血缘摘要和处理链概况，返回节点数量、质量评分、数据来源和处理步骤。适用于资产背景查询、数据来源追溯。
executor: app.services.skills.lineage_skill:DataLineageSkill.get_lineage_summary
model: deepseek-chat
color: green
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
output_summary: 返回 node_count、quality_score、data_source、processing_steps、integrity_verified
examples:
  - input:
      asset_id: "asset_123"
    output:
      asset_id: "asset_123"
      node_count: 5
      root_hash: "abc123..."
      integrity_verified: true
      quality_score: 0.85
      data_source: "sensor_data_stream"
      processing_steps:
        - "cleaning: clean_001"
        - "transformation: transform_002"
        - "aggregation: agg_003"
temperature: 0.2
max_rounds: 3
permission_mode: auto
memory:
  namespace: lineage
---

# 何时使用本 Skill

## 触发条件
- 用户想了解某个资产的数据来源
- 需要验证数据血缘链的完整性
- 资产背景调查，了解处理历程
- 质量评估前的预处理信息收集

## 排除条件
- 不要用于影响范围分析（使用 lineage_impact skill）
- 不要用于质量评分（本 skill 的 quality_score 为占位值，需单独调用 assess_quality）
- 不要用于血缘图可视化（使用 get_lineage_graph 接口）

# 输入参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `asset_id` | string | 是 | 目标资产唯一标识 |

# 执行规则

1. 扫描资产的完整血缘树，统计节点数量
2. 验证血缘链完整性（hash 校验）
3. 追溯最上游数据来源
4. 提取所有处理步骤（非原始节点）
5. `quality_score` 字段当前为占位值（0.0），如需真实评分请调用质量评估接口

# 输出格式

```json
{
  "asset_id": "asset_123",
  "node_count": 5,
  "root_hash": "abc123...",
  "integrity_verified": true,
  "quality_score": 0.0,
  "data_source": "sensor_data_stream",
  "processing_steps": [
    "cleaning: clean_001",
    "transformation: transform_002",
    "aggregation: agg_003"
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `asset_id` | string | 资产标识 |
| `node_count` | integer | 血缘树节点总数 |
| `root_hash` | string | 根节点哈希（可能为 null） |
| `integrity_verified` | boolean | 血缘链完整性是否通过验证 |
| `quality_score` | float | 质量评分（占位值，需单独评估） |
| `data_source` | string | 最上游数据来源名称 |
| `processing_steps` | string[] | 处理步骤列表，格式为 `{type}: {node_id}` |

# 常见错误与恢复

| 错误 / 现象 | 原因 | 恢复动作 |
|-------------|------|----------|
| `node_count` 为 0 | 资产无血缘记录 | 告知用户该资产可能为原始数据 |
| `integrity_verified` 为 false | 血缘链可能被篡改 | 警告用户数据可信度存疑，建议人工核查 |
| `data_source` 为 "unknown" | 无法追溯上游 | 可能是孤儿节点，建议检查数据导入流程 |
