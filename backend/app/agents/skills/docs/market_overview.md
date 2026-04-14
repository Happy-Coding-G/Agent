---
skill_id: market_overview
name: 市场概览
capability_type: skill
description: 返回整体市场概览统计
executor: app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview
input_schema:
  type: object
  properties: {}
output_summary: 返回总交易量、活跃资产数和类型分布
---

## 适用场景
- 市场总览
- 运营汇总
- 图表前置数据获取

## 工作流步骤
1. 聚合交易统计
2. 汇总活跃资产
3. 生成整体市场快照
