---
skill_id: review_workflow
name: 文档审查工作流
capability_type: subagent
description: 执行完整的文档质量、合规与完整性审查工作流
executor: app.agents.subagents.review_agent:ReviewAgent.run
input_schema:
  type: object
  properties:
    doc_id:
      type: string
      description: 文档ID
    review_type:
      type: string
      default: standard
      description: 审查类型
  required:
    - doc_id
output_summary: 返回审查得分、通过状态、问题列表和整改建议
---

## 适用场景
- 发布前审查
- 质量门禁
- 合规检查

## 工作流步骤
1. 加载文档
2. 质量检查
3. 合规检查
4. 完整性检查
5. 决策与返工
