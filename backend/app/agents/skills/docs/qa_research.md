---
skill_id: qa_research
name: 知识检索问答
capability_type: subagent
description: 多步骤知识检索与溯源回答
executor: app.agents.subagents.qa_agent:QAAgent.run
input_schema:
  type: object
  properties:
    query:
      type: string
      description: 研究或问答请求
    space_id:
      type: string
      description: 空间public_id
    top_k:
      type: integer
      minimum: 1
      maximum: 20
      default: 5
      description: 检索条数
  required:
    - query
    - space_id
output_summary: 返回带有来源引用的可溯源回答
---

## 适用场景
- 复杂问答
- 研究型回答
- 需要来源追踪的解释

## 工作流步骤
1. 检索向量上下文
2. 检索图谱上下文
3. 混合合并
4. 生成可溯源回答
