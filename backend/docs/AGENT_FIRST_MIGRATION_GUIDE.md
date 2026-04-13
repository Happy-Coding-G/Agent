# Agent-First 架构迁移指南

本文档帮助开发者从旧版 API-Driven 架构迁移到新的 Agent-First 架构。

## 概述

在 Agent-First 架构中：
- **Agent 是唯一的业务编排者** - 所有交易都通过 Agent 提交和推进
- **API 退化为边界访问和观察** - API 只负责接收目标和返回状态
- **用户描述目标，而非实现** - 使用 `TradeGoal` 描述意图，而非直接操作协商

## 主要变更

### 旧架构（API-Driven）

```
前端 → 直接调用协商/拍卖/交易 API → 后端直接执行
```

### 新架构（Agent-First）

```
前端 → 提交 TradeGoal 到 Agent → Agent 自动决策和执行
                ↓
         查询任务状态
                ↓
         获取最终结果
```

## 端点迁移对照表

| 旧端点 | 新端点 | 说明 |
|--------|--------|------|
| `POST /api/v1/trade/execute` | `POST /api/v1/agent/trade/goal` | 提交交易目标 |
| `POST /api/v1/trade/buy` | `POST /api/v1/agent/trade/goal/buy` | 快速购买（简写） |
| `POST /api/v1/trade/sell` | `POST /api/v1/agent/trade/goal/sell` | 快速出售（简写） |
| `GET /api/v1/trade/status?task_id=xxx` | `GET /api/v1/agent/trade/task/{id}` | 查询任务状态 |
| `POST /api/v1/negotiations` | `POST /api/v1/agent/trade/goal` | 创建协商 |
| `POST /api/v1/negotiations/{id}/offer` | `POST /api/v1/negotiations/{id}/offer` | 人工报价（保留） |
| `POST /api/v1/negotiations/{id}/respond` | `POST /api/v1/negotiations/{id}/respond` | 人工响应（保留） |
| `POST /api/v1/hybrid-negotiations/bilateral` | `POST /api/v1/agent/trade/goal` | 创建双边协商 |
| `POST /api/v1/hybrid-negotiations/auctions` | `POST /api/v1/agent/trade/goal` | 创建拍卖 |

## 请求格式迁移

### 购买资产（旧格式）

```json
POST /api/v1/trade/execute
{
  "action": "initiate_negotiation",
  "params": {
    "listing_id": "listing_123",
    "max_budget": 1000.0,
    "initial_offer": 900.0
  }
}
```

### 购买资产（新格式）

```json
POST /api/v1/agent/trade/goal/buy
{
  "listing_id": "listing_123",
  "max_price": 1000.0,
  "target_price": 900.0
}
```

或者使用通用端点：

```json
POST /api/v1/agent/trade/goal
{
  "intent": "buy",
  "listing_id": "listing_123",
  "target_price": 900.0,
  "max_price": 1000.0,
  "asset_type": "general"
}
```

### 出售资产（旧格式）

```json
POST /api/v1/trade/execute
{
  "action": "create_listing",
  "params": {
    "asset_id": "asset_456",
    "reserve_price": 500.0,
    "target_price": 800.0
  }
}
```

### 出售资产（新格式）

```json
POST /api/v1/agent/trade/goal/sell
{
  "asset_id": "asset_456",
  "min_price": 500.0,
  "target_price": 800.0
}
```

## 任务状态查询

提交目标后，会返回 `task_id`。使用它查询执行状态：

```json
GET /api/v1/agent/trade/task/{task_id}

响应：
{
  "task_id": "task_xxx",
  "status": "running",  // pending/running/completed/failed
  "progress": 45,
  "goal_type": "buy",
  "mechanism": "bilateral",
  "session_id": "neg_xxx",
  "current_state": {
    "status": "active",
    "current_round": 2,
    "current_price": 850.0
  },
  "created_at": "2025-01-01T10:00:00Z",
  "updated_at": "2025-01-01T10:05:00Z"
}
```

## 状态流转

```
submit_goal
    ↓
pending ──→ Agent 启动执行
    ↓
running ──→ 协商进行中
    ↓
completed / failed / pending_approval
    ↓
查询最终结果
```

## 约束配置

新架构支持丰富的约束配置：

```json
{
  "goal": {
    "intent": "buy",
    "listing_id": "listing_123",
    "target_price": 900.0
  },
  "constraints": {
    "max_rounds": 5,
    "timeout_minutes": 60,
    "budget_limit": 1000.0,
    "autonomy_mode": "full_auto",
    "approval_policy": "price_threshold",
    "approval_threshold": 950.0
  }
}
```

### 自治模式

- `full_auto` - 完全自动，Agent 自主决策所有步骤
- `auto_with_approval` - 自动但需要审批
- `manual_step` - 每步需人工确认

### 审批策略

- `none` - 不需要审批
- `always` - 总是需要审批
- `price_threshold` - 超出阈值需审批
- `first_transaction` - 首次交易需审批

## 查询保留接口

以下调试/查询接口仍然可用：

```
# 获取协商详情
GET /api/v1/negotiations/{id}

# 获取完整审计日志
GET /api/v1/hybrid-negotiations/{id}/audit-log

# 获取架构对比信息
GET /api/v1/hybrid-negotiations/comparison

# 场景分析
POST /api/v1/hybrid-negotiations/analyze-scenario
```

## 人工兜底

如需人工干预，仍可使用以下接口：

```
# 提交报价
POST /api/v1/negotiations/{id}/offer

# 响应报价
POST /api/v1/negotiations/{id}/respond

# 撤回协商
POST /api/v1/negotiations/{id}/withdraw
```

注意：这些接口会直接操作协商状态，不会与 AgentTask 状态同步。

## 错误处理

新架构的错误响应：

```json
{
  "success": false,
  "task_id": "task_xxx",
  "status": "failed",
  "message": "Budget exceeded during negotiation",
  "error_details": {
    "code": "BUDGET_EXCEEDED",
    "current_price": 1100.0,
    "budget_limit": 1000.0
  }
}
```

## 最佳实践

1. **总是使用 Agent 入口** - 不要直接创建协商
2. **轮询任务状态** - 使用 `GET /api/v1/agent/trade/task/{id}` 查询进度
3. **设置合理约束** - 配置超时、轮数限制、审批阈值
4. **处理审批等待** - 注意 `pending_approval` 状态
5. **订阅事件（未来）** - 后续将支持 WebSocket 实时推送

## 示例：完整购买流程

### 步骤 1: 提交购买目标

```bash
curl -X POST http://api.example.com/api/v1/agent/trade/goal/buy \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "listing_id": "listing_123",
    "max_price": 1000.0,
    "target_price": 900.0
  }'
```

响应：
```json
{
  "success": true,
  "task_id": "task_abc123",
  "message": "Buy goal submitted to TradeAgent",
  "status": "pending"
}
```

### 步骤 2: 轮询任务状态

```bash
curl http://api.example.com/api/v1/agent/trade/task/task_abc123 \
  -H "Authorization: Bearer {token}"
```

响应（进行中）：
```json
{
  "task_id": "task_abc123",
  "status": "running",
  "progress": 50,
  "current_state": {
    "status": "active",
    "current_round": 2,
    "current_price": 920.0,
    "current_turn": "seller"
  }
}
```

### 步骤 3: 获取最终结果

响应（完成）：
```json
{
  "task_id": "task_abc123",
  "status": "completed",
  "progress": 100,
  "final_state": {
    "status": "accepted",
    "agreed_price": 910.0,
    "session_id": "neg_xyz789"
  },
  "settlement": {
    "status": "completed",
    "final_amount": 910.0
  }
}
```

## 回退策略

如果 Agent-First 流程遇到问题，可以：

1. 使用 `POST /api/v1/negotiations` 直接创建协商
2. 使用 `POST /api/v1/negotiations/{id}/offer` 手动出价
3. 联系管理员调整审批策略

## 支持

如有问题，请联系：
- 技术支持: support@example.com
- API 文档: https://docs.example.com/api
- 迁移问题: migration@example.com
