---
skill_id: audit_report
name: 审计报告生成
capability_type: skill
description: 生成交易或访问行为的审计报告
executor: app.services.skills.audit_skill:AuditSkill.generate_audit_report
input_schema:
  type: object
  properties:
    transaction_id:
      type: string
      description: 交易ID
    days:
      type: integer
      minimum: 1
      maximum: 365
      default: 30
      description: 报告时间窗口
  required:
    - transaction_id
output_summary: 返回 summary、violations、recommendations
---

## 适用场景
- 审计查询
- 风控解释
- 合规检查

## 工作流步骤
1. 聚合访问记录
2. 计算风险指标
3. 输出违规与建议
