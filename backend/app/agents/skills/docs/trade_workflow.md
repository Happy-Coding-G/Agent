---
skill_id: trade_workflow
name: 交易协商工作流
capability_type: subagent
description: 执行交易目标、协商与结算相关工作流
executor: app.agents.subagents.trade.agent:TradeAgent.run
input_schema:
  type: object
  properties:
    action:
      type: string
      description: 交易动作
    space_id:
      type: string
      description: 空间public_id
    payload:
      type: object
      default: {}
      description: 额外参数
  required:
    - action
    - space_id
output_summary: 返回交易结果、协商状态和结算信息
---

## 适用场景
- 复杂交易任务
- 协商执行
- 多轮交易流程

## 工作流步骤
1. 标准化交易目标
2. 评估资产和市场
3. 选择机制
4. 推进协商
5. 发布结果
