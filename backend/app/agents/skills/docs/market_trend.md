---
skill_id: market_trend
name: 市场趋势分析
capability_type: skill
description: 分析某类资产的市场趋势
executor: app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_trend
input_schema:
  type: object
  properties:
    data_type:
      type:
        - string
        - "null"
      default: null
      description: 数据类型
    days:
      type: integer
      minimum: 1
      maximum: 365
      default: 30
      description: 统计天数
output_summary: 返回趋势、均价、变化比例和热门资产
---

## 适用场景
- 趋势判断
- 价格解释
- 图表查询

## 工作流步骤
1. 拉取时间窗口内统计
2. 计算均价和趋势
3. 输出热门资产
