---
skill_id: pricing_quick_quote
name: 快速定价建议
capability_type: skill
description: 对单个数据资产给出快速定价建议
executor: app.services.skills.pricing_skill:PricingSkill.calculate_quick_price
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产ID
    rights_types:
      type: array
      items:
        type: string
      default:
        - usage
        - analysis
      description: 权益类型列表
    duration_days:
      type: integer
      minimum: 1
      maximum: 3650
      default: 365
      description: 授权天数
  required:
    - asset_id
output_summary: 返回 fair_value、recommended price 和价格区间
---

## 适用场景
- 快速询价
- 交易前预估
- 价格区间判断

## 工作流步骤
1. 解析权益范围
2. 调用定价引擎
3. 输出价格区间和置信信息
