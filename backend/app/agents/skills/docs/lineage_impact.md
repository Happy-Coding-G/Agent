---
skill_id: lineage_impact
name: 血缘影响分析
capability_type: skill
description: 分析某资产变更对上下游的影响范围
executor: app.services.skills.lineage_skill:DataLineageSkill.analyze_impact
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产ID
  required:
    - asset_id
output_summary: 返回 upstream/downstream 数量、impact score 和 risk level
---

## 适用场景
- 变更影响分析
- 发布前风险评估
- 依赖梳理

## 工作流步骤
1. 扫描上下游依赖
2. 计算影响得分
3. 输出风险等级
