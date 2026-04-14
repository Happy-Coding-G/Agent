---
skill_id: lineage_summary
name: 血缘摘要
capability_type: skill
description: 获取资产的血缘摘要和处理链概况
executor: app.services.skills.lineage_skill:DataLineageSkill.get_lineage_summary
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产ID
  required:
    - asset_id
output_summary: 返回 node_count、quality_score、data_source 和 processing_steps
---

## 适用场景
- 资产背景查询
- 数据来源追溯
- 质量背景解释

## 工作流步骤
1. 加载血缘树
2. 校验完整性
3. 汇总来源和处理步骤
