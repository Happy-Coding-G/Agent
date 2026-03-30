# Trade Multi-Agent Architecture

## 概述

基于 LangGraph 的多 Agent 分布式协商架构，实现了真正的 Agent 间通信和状态流转。

## 架构组件

### 1. Agent Nodes

```
┌─────────────────┐
│  Orchestrator   │  <- 协调器，控制流程和路由
│     Node        │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐  ┌────────┐
│ Seller │  │ Buyer  │  <- 买卖双方 Agent
│ Agent  │  │ Agent  │     (通过消息传递通信)
└────┬───┘  └───┬────┘
     │          │
     └────┬─────┘
          ▼
   ┌─────────────┐
   │  Settlement │  <- 结算节点
   │    Node     │
   └─────────────┘
```

### 2. 状态流转

```
[Init] -> [Orchestrator] -> [Seller] --消息--> [Buyer] --消息--> [Orchestrator]
                                    ↑                              │
                                    └──────────────────────────────┘
                                          (循环多轮协商)

当达成协议:
[Orchestrator] -> [Settlement] -> [End]
```

### 3. 消息传递机制

Agent 之间通过 `AgentMessage` 进行通信：

```python
@dataclass
class AgentMessage:
    msg_id: str
    msg_type: MessageType  # ANNOUNCE, BID, OFFER, COUNTER, ACCEPT, etc.
    from_agent: str
    to_agent: str
    payload: Dict[str, Any]
```

消息队列存储在 `TradeAgentState.message_queue` 中，由 Orchestrator 负责路由。

### 4. 三种市场机制

#### 4.1 Contract Net Protocol (合同网)

```
Seller Agent                    Buyer Agent(s)
    │                               │
    ├── [ANNOUNCE] 任务公告 ───────►│
    │                               │
    │◄──────────── [BID] 投标 ─────┤
    │                               │
    ├── [ACCEPT/REJECT] 授予 ─────►│
```

#### 4.2 Auction (拍卖)

```
Seller Agent                    Buyer Agent(s)
    │                               │
    ├── [ANNOUNCE] 拍卖启动 ───────►│
    │                               │
    │◄──────────── [BID] 出价 ─────┤ (多轮)
    │                               │
    ├── [ACCEPT] 成交 ────────────►│
```

#### 4.3 Bilateral Negotiation (双边协商)

```
Seller Agent                    Buyer Agent
    │                               │
    │◄─────────── [OFFER] 报价 ────┤
    │                               │
    ├── [COUNTER] 反报价 ─────────►│ (循环)
    │                               │
    │◄─────────── [OFFER] 出价 ────┤
    │                               │
    ├── [ACCEPT] 接受 ────────────►│
```

## 代码结构

```
backend/app/agents/
├── trade_graph.py              # LangGraph 状态图定义
│   ├── SellerAgentNode         # 卖方 Agent 节点
│   ├── BuyerAgentNode          # 买方 Agent 节点
│   ├── ExchangeOrchestratorNode # 协调器节点
│   ├── SettlementNode          # 结算节点
│   └── create_trade_graph()    # 图构建器
│
└── subagents/
    └── trade_agent.py          # TradeAgent 对外接口
        └── self.graph_service  # TradeGraphService 实例
```

## 使用示例

### 创建拍卖

```python
# API 调用
trade_agent = TradeAgent(db, llm_client)

# 启动多 Agent 协商
result = await trade_agent.create_auction(
    space_public_id="space_123",
    asset_id="asset_456",
    user=seller_user,
    auction_type="english",
    starting_price=100.0,
)

# 返回 negotiation_id 用于后续交互
negotiation_id = result["negotiation_id"]
```

### 买方出价

```python
# 买方 Agent 接收出价指令，发送 BID 消息
result = await trade_agent.place_auction_bid(
    lot_id=negotiation_id,
    user=buyer_user,
    amount=150.0,
)

# 消息流转:
# 1. API -> Buyer Agent
# 2. Buyer Agent 创建 BID 消息
# 3. Orchestrator 路由消息到 Seller Agent
# 4. Seller Agent 评估出价
# 5. 返回 ACCEPT/COUNTER
```

### 双边协商

```python
# 创建协商会话
result = await trade_agent.create_bilateral_negotiation(
    listing_id="listing_123",
    buyer=buyer_user,
    initial_offer=80.0,
    max_rounds=10,
)

# 卖方响应
result = await trade_agent.respond_to_negotiation_offer(
    session_id=result["session_id"],
    user=seller_user,
    response="counter",  # accept/reject/counter
    counter_price=90.0,
)

# 多轮循环直到达成协议或终止
```

## 与之前架构的区别

| 维度 | 旧架构 (函数调用) | 新架构 (LangGraph) |
|------|------------------|-------------------|
| Agent 通信 | 直接方法调用 | 消息传递 |
| 状态管理 | 内存字典 | LangGraph State |
| 循环交互 | 手动控制 | 图状态机自动流转 |
| 可观测性 | 有限 | 完整的状态历史 |
| 人工干预 | 难以实现 | 内置 `human_in_the_loop` |
| 持久化 | 内存 | 支持 Checkpoint |

## 待办事项

1. **数据库集成**: 将 negotiation_id 与 listing 关联存储
2. **LLM 决策**: 在 Seller/Buyer Agent 中集成 LLM 进行复杂决策
3. **并发控制**: 处理多个买方同时出价的情况
4. **人工干预**: 实现 `human_in_the_loop` 机制
5. **状态持久化**: 使用数据库存储 checkpoint 而非内存
