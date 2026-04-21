---
skill_id: asset_cluster_prompt
name: 资产聚类提示词
capability_type: prompt
description: 根据资产的特征将其分组聚类，并生成整理报告
executor: null
input_schema:
  type: object
  properties: {}
output_summary: 聚类策略配置和提示词模板
---

## 适用场景
- 批量资产整理
- 自动分组聚类
- 整理报告生成

## 工作流步骤
1. 提取资产特征（category, topic, entities, tags）
2. 应用 community_detection 聚类算法
3. 基于图谱关系增强聚类边界
4. 生成整理报告

## 提示词模板

你是一个资产整理助手。根据资产的特征将其分组聚类，并生成整理报告。

聚类策略：
- method: community_detection
- graph_based: True
- features: category, topic, entities, tags
- min_cluster_size: 2
- max_cluster_size: 50
