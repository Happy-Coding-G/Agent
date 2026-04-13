# Agent-First 架构总结文档

## 概述

本项目已完成从 API-Driven 到 Agent-First 架构的迁移。Agent-First 架构将 Agent 作为唯一的业务编排者，API 退化为边界访问和观察。

## 核心原则

1. **Agent 是唯一的业务编排者** - 所有交易逻辑通过 Agent 决策和执行
2. **用户描述目标，而非实现** - 使用 `TradeGoal` 描述交易意图
3. **机制选择是策略，不是参数** - 自动选择双边协商、拍卖或直接交易
4. **API 只处理边界访问** - 接收目标和返回状态

## 架构组件

### 1. 统一控制平面 (Phase 1)

**TradeGoal Schema** (`app/schemas/trade_goal.py`)
- `TradeGoal` - 交易目标定义
- `TradeConstraints` - 约束条件
- `MechanismSelection` - 机制选择结果
- `TradeExecutionPlan` - 执行计划
- `create_buy_goal()` / `create_sell_goal()` - 便捷函数

**机制选择策略** (`app/services/trade/mechanism_selection_policy.py`)
- 自动选择机制（双边/拍卖/合同网）
- 自动选择引擎（simple/event_sourced）
- 考虑并发需求、审计需求、用户偏好

**Agent API** (`app/api/v1/endpoints/agent.py`)
- `POST /api/v1/agent/trade/goal` - 提交交易目标（主入口）
- `POST /api/v1/agent/trade/goal/buy` - 快速购买（简写）
- `POST /api/v1/agent/trade/goal/sell` - 快速出售（简写）
- `GET /api/v1/agent/trade/task/{id}` - 查询任务状态

### 2. TradeAgent 执行图 (Phase 2)

**TradeState** (`app/agents/subagents/trade/state.py`)
- Agent-First 字段：goal_type, trade_goal, mechanism_selection
- 配置信息：user_config
- 会话关联：negotiation_session_id
- 执行追踪：execution_plan, task_id, current_step

**TradeAgent** (`app/agents/subagents/trade/agent.py`)
- `execute_trade_goal()` - 执行交易目标
- `run_goal()` - 运行目标入口

**执行图** (`app/agents/subagents/trade/graph.py`)
```
normalize_goal
    ↓
load_user_config
    ↓
select_mechanism
    ↓
evaluate_approval
    ↓
[需要审批?] ─是→ wait_for_approval → resume_after_approval
    ↓否
create_negotiation
    ↓
auto_negotiate (循环直到完成)
    ↓
finalize_trade
```

**Agent-First 节点** (`app/agents/subagents/trade/nodes/agent_first.py`)
- 11个新节点实现完整交易流程
- 每个节点职责单一，可测试

### 3. 统一协商内核 (Phase 3)

**领域结果类型** (`app/services/trade/result_types.py`)
- `NegotiationResult` - 协商会话结果
- `OfferResult` - 报价结果
- `BidResult` - 出价结果
- `SessionState` - 会话状态投影

**统一协商内核** (`app/services/trade/negotiation_kernel.py`)
- `_BilateralEngine` - 双边协商引擎
- `_AuctionEngine` - 拍卖引擎
- 统一接口：`create_session`, `get_state`, `submit_offer`, `submit_bid`, `accept_offer`
- 自动引擎路由
- 乐观锁版本控制

**协商服务增强**
- `SimpleNegotiationService` - 简化版服务（乐观锁支持）
- `TradeNegotiationService` - 完整版服务（事件溯源支持）
- 自动场景路由

### 4. 模型层与自治能力 (Phase 4)

**模型增强** (`app/db/models.py`)
```python
# NegotiationSessions 新增字段
- engine_type: 引擎类型 (simple/event_sourced)
- selection_reason: 选择原因
- autonomy_mode: 自治模式
- approval_status: 审批状态
- initiating_task_id: 关联任务ID
- expected_participants: 预期参与者
- requires_full_audit: 是否需要审计
- last_projection_version: 投影版本

# AgentTasks 新增字段
- negotiation_session_id: 关联协商会话
- trade_goal_type: 交易目标类型
- execution_plan_id: 执行计划ID
- progress_percentage: 进度百分比
- current_step: 当前步骤
```

**审批策略服务** (`app/services/trade/approval_policy_service.py`)
- 集中管理审批决策
- 支持多种策略：ALWAYS, NONE, FIRST_TRANSACTION, PRICE_THRESHOLD
- 高价值/高预算检查

**决策日志服务** (`app/services/trade/decision_log_service.py`)
- 记录 Agent 决策历史
- 支持审计和调试

**TradeAgent Worker** (`app/agents/trade/trade_agent_worker.py`)
- V3 自治执行器
- 轮询活跃任务
- 自动推进协商
- 审批等待和恢复
- 超时处理

### 5. 旧 API 收口 (Phase 5)

**trade_actions.py** - 兼容适配器
- 将旧动作格式转换为 TradeGoal
- 提交给 TradeAgent
- 标记为已弃用

**negotiations.py** - 人工兜底接口
- 直接操作协商（绕过 Agent）
- 乐观锁支持
- 标记为人工操作

**hybrid_negotiations.py** - 调试/查询接口
- 保留查询功能
- 写入操作标记为已弃用
- 架构对比和场景分析

## 数据流

```
用户提交 TradeGoal
        ↓
Agent API 接收并创建 AgentTask
        ↓
TradeAgent 加载并执行
        ↓
机制选择策略选择最优机制
        ↓
审批策略评估是否需要审批
        ↓
创建协商会话（NegotiationSession）
        ↓
TradeAgent Worker 自动推进
        ↓
协商完成 → 触发结算
        ↓
AgentTask 标记为完成
```

## API 端点分类

### 主入口（推荐）
```
POST /api/v1/agent/trade/goal       - 提交交易目标
GET  /api/v1/agent/trade/task/{id}  - 查询任务状态
```

### 兼容接口（已弃用）
```
POST /api/v1/trade/execute          - 转换为 TradeGoal
POST /api/v1/trade/buy              - 转换为 TradeGoal
POST /api/v1/trade/sell             - 转换为 TradeGoal
```

### 人工兜底（特殊场景）
```
POST /api/v1/negotiations           - 直接创建协商
POST /api/v1/negotiations/{id}/offer    - 人工报价
POST /api/v1/negotiations/{id}/respond  - 人工响应
```

### 调试/查询
```
GET /api/v1/hybrid-negotiations/mechanisms           - 机制类型
POST /api/v1/hybrid-negotiations/analyze-scenario    - 场景分析
GET /api/v1/hybrid-negotiations/{id}/state           - 获取状态
GET /api/v1/hybrid-negotiations/{id}/audit-log       - 审计日志
GET /api/v1/hybrid-negotiations/comparison           - 架构对比
```

## 测试覆盖

### 单元测试
- `test_mechanism_selection_policy.py` - 机制选择策略
- `test_approval_policy_service.py` - 审批策略
- `test_negotiation_kernel.py` - 协商内核

### 集成测试
- `test_agent_trade_goal.py` - Agent 交易目标

## 迁移路径

1. **新开发** - 直接使用 `POST /api/v1/agent/trade/goal`
2. **旧代码迁移** - 逐步替换旧端点调用
3. **参考指南** - 详见 `docs/AGENT_FIRST_MIGRATION_GUIDE.md`

## 优势

1. **简化前端** - 只需描述目标，无需了解实现细节
2. **灵活机制** - 自动选择最优协商机制
3. **自主执行** - Worker 自动推进，无需轮询
4. **完整审计** - 所有决策可追溯
5. **易于扩展** - 新增策略只需修改配置

## 未来扩展

1. **WebSocket 推送** - 实时状态更新
2. **批量交易** - 支持多个目标批量处理
3. **复杂策略** - 基于 ML 的机制选择
4. **多 Agent 协作** - 多个 Agent 协同交易
