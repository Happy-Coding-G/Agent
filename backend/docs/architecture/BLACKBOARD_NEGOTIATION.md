# Blackboard 模式协商架构

## 概述

Blackboard 模式是一种基于**完整上下文共享**的多 Agent 协商架构。买卖双方的 Agent 在各自底线价格的约束下进行多轮价格协商，整个协商过程作为完整上下文提供给双方 Agent 进行智能决策。

## 核心设计

### 1. 价格约束机制

```
┌─────────────────────────────────────────────────────────────┐
│                    价格区间示意图                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   卖方底线 (Floor)  ──────────  买方天花板 (Ceiling)          │
│        │                        │                            │
│        ▼                        ▼                            │
│   ┌────────┐            ┌────────────┐                     │
│   │ 最低   │    重叠区间   │   最高     │                     │
│   │ 可接受  │◄──────────►│  可接受    │                     │
│   │ 价格   │            │   价格     │                     │
│   └────────┘            └────────────┘                     │
│                                                              │
│   卖方期望价格 ────────●─────────────                       │
│                     │                                        │
│   买方期望价格 ────────────────────●                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2. 底线价格保护

- **卖方底线价格 (Floor Price)**: 卖方可接受的最低价格，系统强制不允许出价低于此价格
- **买方天花板价格 (Ceiling Price)**: 买方可接受的最高价格，系统强制不允许出价高于此价格
- **目标价格**: 用于 Agent 决策的参考价格

### 3. 完整上下文

每个 Agent 在做出决策时，都会获得完整的协商上下文：

```python
{
    "negotiation_id": "xxx",
    "status": "active",
    "current_round": 5,
    "max_rounds": 20,

    # 当前位置
    "current_price": 85.0,
    "starting_price": 100.0,

    # 我的约束（仅对自己可见）
    "my_floor_price": 60.0,      # 卖方：最低接受
    "my_ceiling_price": 120.0,   # 买方：最高接受

    # 对方约束（可见但不能突破）
    "opponent_floor_price": 60.0,
    "opponent_ceiling_price": 120.0,

    # 目标价格
    "my_target_price": 80.0,
    "opponent_target_price": 100.0,

    # 完整协商历史
    "negotiation_history": [
        {"round": 1, "by": "buyer", "price": 120, "message": "Initial offer"},
        {"round": 2, "by": "seller", "price": 90, "message": "Counter offer"},
        {"round": 3, "by": "buyer", "price": 85, "message": "Acceptable"},
        ...
    ],

    # 价格演变
    "price_evolution": [
        {"round": 1, "price": 120, "direction": "down"},
        {"round": 2, "price": 90, "direction": "down"},
    ],

    # 系统分析
    "analysis": {
        "deal_possible": True,
        "overlap_range": {"min": 60, "max": 120, "midpoint": 90},
        "recommendation": "Price is in favorable range",
        "risk_level": "medium"
    }
}
```

## 协商流程

### 1. 创建协商（卖方发起）

```python
# 卖方创建黑板协商
negotiation_id = await trade_agent.create_blackboard_negotiation(
    space_public_id="space_xxx",
    asset_id="asset_xxx",
    user=seller,
    floor_price=60.0,        # 最低接受价格
    target_price=80.0,       # 期望价格
    starting_price=100.0,    # 起始报价
)
```

### 2. 买方加入

```python
# 买方设置天花板价格并加入
await trade_agent.join_blackboard_negotiation(
    negotiation_id=negotiation_id,
    buyer=buyer,
    ceiling_price=120.0,     # 最高接受价格
    target_price=100.0,      # 期望价格
    initial_offer=120.0,     # 可选：初始出价
)
```

### 3. Agent 决策循环

```python
while negotiation.status == "active":
    # 获取完整上下文
    context = await trade_agent.get_blackboard_context(
        negotiation_id=negotiation_id,
        user=current_agent,
    )

    # Agent 基于上下文做出决策
    decision = await agent_decide(context)

    if decision.action == "accept":
        await trade_agent.accept_blackboard_offer(...)
    elif decision.action == "counter":
        await trade_agent.counter_blackboard_offer(
            negotiation_id=negotiation_id,
            user=current_agent,
            counter_price=decision.suggested_price,
            reason=decision.reasoning,
        )
```

### 4. 结算

```python
# 达成协议后，卖方完成结算
await trade_agent.settle_blackboard(
    negotiation_id=negotiation_id,
    user=seller,
)
```

## Agent 决策策略

### 基于上下文的智能决策

Agent 在决策时可以考虑：

1. **当前价格位置**:
   - 是否在重叠区间内
   - 是否接近对方底线

2. **协商历史趋势**:
   - 价格是否逐步收敛
   - 双方是否在接近

3. **剩余轮次**:
   - 时间压力
   - 退出成本

4. **系统建议**:
   - 风险等级
   - 建议价格

### 决策示例

```python
async def agent_decide(context):
    """
    基于黑板上下文进行决策
    """
    # 基础策略
    if context.current_price <= context.my_floor_price * 1.1:
        # 价格接近底线，考虑接受
        return {"action": "accept"}

    if context.remaining_time < 60:  # 少于1小时
        # 时间紧迫，加速决策
        if context.current_price <= context.opponent_target_price:
            return {"action": "accept"}

    # 正常协商
    if context.analysis["risk_level"] == "high":
        return {"action": "withdraw"}

    # 计算让步幅度
    concession_rate = calculate_concession(context)
    counter_price = suggest_counter_price(
        current=context.current_price,
        target=context.opponent_target_price,
        concession_rate=concession_rate,
    )

    return {
        "action": "counter",
        "suggested_price": counter_price,
        "reasoning": "Balanced counter offer"
    }
```

## 数据库模型

### NegotiationSessions 扩展字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `seller_floor_price` | BigInteger | 卖方最低接受价格（分） |
| `buyer_ceiling_price` | BigInteger | 买方最高接受价格（分） |
| `seller_target_price` | BigInteger | 卖方期望价格（分） |
| `buyer_target_price` | BigInteger | 买方期望价格（分） |
| `shared_board` | JSONB | 完整协商上下文 |

### shared_board 结构

```json
{
    "created_at": "2024-01-01T00:00:00Z",
    "negotiation_history": [
        {"round": 1, "by": "buyer", "price": 120, "reasoning": "..."}
    ],
    "price_evolution": [
        {"round": 1, "price": 120, "direction": "down"}
    ],
    "seller_strategy": {
        "floor_price": 60,
        "target_price": 80,
        "concessions": []
    },
    "buyer_strategy": {
        "ceiling_price": 120,
        "target_price": 100,
        "concessions": []
    },
    "public_notes": [],
    "analysis": {}
}
```

## 分层上下文管理 - 解决上下文窗口爆炸

### 问题

随着协商轮次增加，完整历史可能导致上下文窗口溢出：
- 20 轮协商 × 150 tokens/轮 = 3000 tokens
- 50 轮协商 × 150 tokens/轮 = 7500 tokens
- 100 轮协商 × 150 tokens/轮 = 15000 tokens

### 解决方案：分层上下文

```
┌─────────────────────────────────────────────────────────────────┐
│                    分层上下文架构                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Layer 1: 短期记忆 (最近 5 轮)                          │     │
│  │  ┌─────────────────────────────────────────────────┐   │     │
│  │  │ round 6: buyer → ¥85                           │   │     │
│  │  │ round 5: seller → ¥90, reason: "market price"   │   │     │
│  │  │ round 4: buyer → ¥92                           │   │     │
│  │  │ round 3: seller → ¥95, reason: "good quality"  │   │     │
│  │  │ round 2: buyer → ¥100                          │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  └─────────────────────────────────────────────────────────┘     │
│                              │                                     │
│                              ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  Layer 2: 历史摘要 (Round 1-5)                          │     │
│  │  ┌─────────────────────────────────────────────────┐   │     │
│  │  │ Summary: 买方出价2次，卖方出价3次                 │   │     │
│  │  │ Price: ¥120 → ¥95, 趋势: converging            │   │     │
│  │  │ 关键事件: [buyer_bid, seller_counter, ...]      │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  结构化状态 (与轮次无关)                                 │     │
│  │  ┌─────────────────────────────────────────────────┐   │     │
│  │  │ my_floor_price: ¥60                            │   │     │
│  │  │ my_ceiling_price: ¥120                        │   │     │
│  │  │ overlap_range: [¥60, ¥120]                    │   │     │
│  │  │ analysis: {deal_possible: true, risk: medium}  │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 配置

```python
CONTEXT_LAYERS = {
    "recent_rounds": 5,       # 最近 5 轮完整保留
    "summary_interval": 5,    # 每 5 轮生成一次摘要
    "max_token_estimate": 4000,  # 最大 token 限制
}
```

### API

```python
# 获取分层上下文（默认）
context = await negotiation_service.get_full_blackboard_context(
    negotiation_id=negotiation_id,
    for_user_id=user_id,
    use_hierarchical=True,  # 默认
)

# 获取完整分层结构
full_hierarchy = await negotiation_service.get_hierarchical_context(
    negotiation_id=negotiation_id,
    for_user_id=user_id,
)
```

### 数据库模型

```sql
-- 协商历史摘要表
CREATE TABLE negotiation_history_summaries (
    id BIGSERIAL PRIMARY KEY,
    summary_id VARCHAR(32) UNIQUE NOT NULL,
    negotiation_id VARCHAR(32) NOT NULL,
    layer INT DEFAULT 1,              -- 层级
    round_start INT NOT NULL,         -- 覆盖起始轮次
    round_end INT NOT NULL,           -- 覆盖结束轮次
    summary TEXT NOT NULL,            -- LLM 生成的摘要
    price_trajectory JSONB,           -- 价格轨迹
    key_events JSONB,                 -- 关键事件
    created_at TIMESTAMP DEFAULT now()
);
```

### 自动摘要触发

摘要会在以下条件满足时自动生成：
1. 当前轮次 > `recent_rounds`
2. `current_round % summary_interval == 0`

例如：
- 第 5 轮：保留完整 → 生成摘要
- 第 10 轮：生成摘要
- 第 15 轮：生成摘要
- ...

## 与传统模式的区别

| 特性 | 传统模式 | Blackboard 模式 |
|------|---------|----------------|
| 价格约束 | 事后验证 | 事前声明 + 强制执行 |
| 上下文可见性 | 有限 | 完整共享 |
| 协商历史 | 分散 | 集中存储 |
| Agent 决策 | 基于当前出价 | 基于完整历史 |
| 价格演变 | 不透明 | 透明可视化 |

## API 端点

```
POST   /api/v1/trade/blackboard/create     - 创建黑板协商
POST   /api/v1/trade/blackboard/join      - 买方加入
GET    /api/v1/trade/blackboard/{id}       - 获取完整上下文
POST   /api/v1/trade/blackboard/{id}/offer    - 提交出价
POST   /api/v1/trade/blackboard/{id}/accept   - 接受出价
POST   /api/v1/trade/blackboard/{id}/counter  - 反报价
POST   /api/v1/trade/blackboard/{id}/settle   - 完成结算
GET    /api/v1/trade/blackboard/           - 列出协商
```
