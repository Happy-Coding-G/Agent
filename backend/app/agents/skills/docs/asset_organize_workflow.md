---
skill_id: asset_organize_workflow
name: 资产整理工作流
capability_type: subagent
description: 执行资产聚类、摘要和发布准备工作流
executor: app.agents.subagents.asset_organize_agent:AssetOrganizeAgent.run
input_schema:
  type: object
  properties:
    asset_ids:
      type: array
      items:
        type: string
      description: 资产ID列表
  required:
    - asset_ids
output_summary: 返回聚类结果、整理报告和发布准备状态
---

## 适用场景
- 批量资产整理
- 聚类归档
- 发布前准备

## 工作流步骤
1. 加载资产
2. 特征提取
3. 聚类
4. 图谱更新
5. 发布准备
