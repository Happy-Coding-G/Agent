---
skill_id: dynamic_workflow
name: 动态工作流生成
capability_type: subagent
description: 为无法一次性解决的复杂任务动态生成 subagent 模板
tools:
  - memory_manage
executor: app.agents.subagents.template:DynamicWorkflowSubAgent.run
input_schema:
  type: object
  properties:
    task_name:
      type: string
      description: 动态 subagent 名称
    goal:
      type: string
      description: 复杂任务目标
    deliverable:
      type:
        - string
        - "null"
      default: null
      description: 预期交付物
    context:
      type: object
      default: {}
      description: 附加上下文
    suggested_steps:
      type:
        - array
        - "null"
      items:
        type: string
      default: null
      description: 建议步骤
  required:
    - task_name
    - goal
output_summary: 返回结构化的执行计划与后续执行入口
---

## 适用场景
- 开放式复杂任务
- 临时多阶段任务
- 跨能力协同任务

## 工作流步骤
1. 识别目标
2. 拆分阶段
3. 生成执行模板
4. 返回工作流壳
