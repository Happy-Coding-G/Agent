---
skill_id: privacy_protocol
name: 隐私计算协议协商
capability_type: skill
description: 根据敏感度和约束协商隐私计算协议
executor: app.services.skills.privacy_skill:PrivacyComputationSkill.negotiate_protocol
input_schema:
  type: object
  properties:
    asset_id:
      type: string
      description: 资产ID
    sensitivity:
      type: string
      description: "敏感度级别: low/medium/high/critical"
    requirements:
      type:
        - object
        - "null"
      default: null
      description: 隐私计算要求
  required:
    - asset_id
    - sensitivity
output_summary: 返回 protocol、constraints 和 reasoning
---

## 适用场景
- 隐私协作
- 联合计算协商
- 脱敏前方案选择

## 工作流步骤
1. 解析敏感度
2. 匹配可用协议
3. 输出约束与成本分摊
