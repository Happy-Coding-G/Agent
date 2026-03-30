# 跨用户Agent协商解决方案

## 问题背景

在多Agent交易协商中，买方Agent和卖方Agent来自**不同的用户**，运行在不同的会话中，需要解决以下问题：

1. **跨会话通信** - 用户A的Seller Agent如何与用户B的Buyer Agent通信？
2. **异步处理** - 买方出价时卖方可能不在线，如何处理？
3. **状态持久化** - 协商状态不能仅存在内存中
4. **并发控制** - 多个买方同时投标如何处理？

## 解决方案架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           数据库层 (PostgreSQL)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐ │
│  │ NegotiationSessions │    │ AgentMessageQueue   │    │ UserAgentConfig │ │
│  │ (协商会话表)         │    │ (Agent消息队列)      │    │ (Agent配置表)    │ │
│  ├─────────────────────┤    ├─────────────────────┤    ├─────────────────┤ │
│  │ - negotiation_id    │    │ - message_id        │    │ - user_id       │ │
│  │ - seller_user_id    │    │ - negotiation_id    │    │ - agent_role    │ │
│  │ - buyer_user_id     │    │ - from_agent_user_id│    │ - auto_accept   │ │
│  │ - status            │◄───┤ - to_agent_user_id  │    │ - max_rounds    │ │
│  │ - current_price     │    │ - msg_type          │    │ - webhook_url   │ │
│  │ - shared_board      │    │ - payload           │    │                 │ │
│  └─────────────────────┘    │ - status            │    └─────────────────┘ │
│                             └─────────────────────┘                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │
┌─────────────────────────────────────┼───────────────────────────────────────┐
│                        服务层 (FastAPI)                                      │
├─────────────────────────────────────┼───────────────────────────────────────┤
│                                     │                                       │
│  ┌──────────────────────────────────┴───────────────────────────────────┐   │
│  │                    TradeNegotiationService                            │   │
│  │                    (协商服务 - 持久化 + 消息队列)                        │   │
│  ├───────────────────────────────────────────────────────────────────────┤   │
│  │  create_negotiation() ──► 创建协商会话，写入数据库                       │   │
│  │  send_message() ────────► 发送消息到队列                                │   │
│  │  poll_messages() ───────► 轮询接收消息                                  │   │
│  │  seller_respond() ──────► 卖方响应                                      │   │
│  │  buyer_place_bid() ─────► 买方出价                                      │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │                    TradeAgentWorker (后台任务)                         │   │
│  │                    (定期轮询消息队列，自动执行Agent决策)                  │   │
│  ├───────────────────────────────────────────────────────────────────────┤   │
│  │  while running:                                                       │   │
│  │      messages = poll_pending_messages()                               │   │
│  │      for msg in messages:                                             │   │
│  │          config = get_user_agent_config(msg.to_user_id)               │   │
│  │          if config.auto_mode:                                         │   │
│  │              decision = agent_decide(msg, config)                     │   │
│  │              execute_action(decision)                                 │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ HTTP/WebSocket
┌─────────────────────────────────────┴───────────────────────────────────────┐
│                         客户端层 (不同用户的浏览器)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌───────────────────────┐              ┌───────────────────────┐         │
│   │     用户A (卖方)        │              │     用户B (买方)        │         │
│   │  ┌─────────────────┐  │              │  ┌─────────────────┐  │         │
│   │  │  Seller Agent   │  │◄────────────►│  │  Buyer Agent    │  │         │
│   │  │  (运行在用户A    │  │   消息队列    │  │  (运行在用户B    │  │         │
│   │  │   的会话中)      │  │   异步通信    │  │   的会话中)      │  │         │
│   │  └─────────────────┘  │              │  └─────────────────┘  │         │
│   └───────────────────────┘              └───────────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 核心组件说明

### 1. 数据库模型

#### NegotiationSessions (协商会话表)
存储协商的完整状态，支持买卖双方独立访问：

```python
class NegotiationSessions:
    negotiation_id: str      # 协商ID
    seller_user_id: int      # 卖方用户ID
    buyer_user_id: int       # 买方用户ID (可为空，表示公开协商)
    status: str              # pending/active/agreed/settled/cancelled
    current_price: int       # 当前价格
    current_round: int       # 当前轮次
    current_turn: str        # seller/buyer (轮到谁行动)
    shared_board: JSONB      # 共享状态板
    expires_at: datetime     # 过期时间
```

#### AgentMessageQueue (Agent消息队列)
实现跨用户异步通信：

```python
class AgentMessageQueue:
    message_id: str          # 消息ID
    negotiation_id: str      # 所属协商
    from_agent_user_id: int  # 发送方
    to_agent_user_id: int    # 接收方
    msg_type: str            # ANNOUNCE/BID/OFFER/COUNTER/ACCEPT/REJECT
    payload: JSONB           # 消息内容
    status: str              # pending/delivered/processed
```

#### UserAgentConfig (Agent配置表)
每个用户可以配置自己的Agent行为：

```python
class UserAgentConfig:
    user_id: int
    agent_role: str          # seller/buyer
    pricing_strategy: str    # fixed/negotiable/aggressive
    auto_accept_threshold: float  # 自动接受阈值
    max_auto_rounds: int     # 最大自动协商轮数
    webhook_url: str         # 通知回调URL
```

### 2. 通信流程示例

#### 场景1：拍卖 (英式)

```
时间线:

T1: 用户A创建拍卖
    ├─ API: POST /spaces/{id}/trade/auctions
    ├─ create_negotiation(seller_user_id=A)
    └─ Status: pending

T2: 用户A发布拍卖公告 (Seller Agent)
    ├─ API: POST /trade/auctions/{id}/announce
    ├─ seller_announce()
    ├─ UPDATE negotiation.status = "active"
    ├─ INSERT message_queue(to=B, type=ANNOUNCE)
    └─ Status: active, current_turn=buyer

T3: 用户B浏览市场，看到拍卖
    ├─ API: GET /trade/market
    └─ 决定参与

T4: 用户B出价 (Buyer Agent)
    ├─ API: POST /trade/auctions/bid
    ├─ buyer_place_bid(amount=150)
    ├─ UPDATE negotiation.current_price = 15000
    ├─ INSERT message_queue(to=A, type=BID)
    └─ Status: active, current_turn=seller

T5: TradeAgentWorker 处理消息
    ├─ 轮询到BID消息
    ├─ 获取用户A的Agent配置
    ├─ 如果auto_mode: 自动决策
    └─ 如果manual_mode: 等待用户操作

T6: 用户A收到通知 (如果在线)
    ├─ WebSocket: {event: "agent.bid", amount: 150}
    └─ 或者用户A登录后看到待处理消息

T7: 用户A接受出价 (Seller Agent)
    ├─ API: POST /trade/negotiations/respond
    ├─ seller_respond(response="accept")
    ├─ UPDATE negotiation.status = "agreed"
    ├─ INSERT message_queue(to=B, type=ACCEPT)
    └─ Status: agreed

T8: 结算
    ├─ finalize_settlement()
    ├─ UPDATE negotiation.status = "settled"
    └─ INSERT message_queue(to=A&B, type=SETTLE)
```

#### 场景2：双边协商 (多轮)

```
Round 1:
  Buyer ──OFFER(80)──► 消息队列 ──► Seller

Round 2:
  Seller 决策: COUNTER(90)
  Seller ──COUNTER(90)──► 消息队列 ──► Buyer

Round 3:
  Buyer 决策: OFFER(85)
  Buyer ──OFFER(85)──► 消息队列 ──► Seller

Round 4:
  Seller 决策: ACCEPT
  Seller ──ACCEPT──► 消息队列 ──► Buyer

协商完成!
```

### 3. Agent执行模式

#### 模式A: 全自动模式
```python
config.use_llm_decision = True
config.auto_accept_threshold = 0.95  # 达到95%自动接受

# Worker自动处理所有消息，无需人工干预
```

#### 模式B: 半自动模式
```python
config.use_llm_decision = True
config.auto_accept_threshold = 1.0  # 仅达到100%自动接受
config.auto_counter_threshold = 0.8  # 80%以上自动反报价

# 简单场景自动处理，复杂场景等待人工
```

#### 模式C: 人工模式
```python
config.use_llm_decision = False

# 所有消息等待用户手动处理
# 前端显示通知，用户点击后执行
```

## API设计

### 创建协商 (卖方发起)
```http
POST /api/v1/spaces/{space_id}/trade/negotiations
{
    "asset_id": "asset_123",
    "mechanism_type": "auction",  // auction/bilateral/contract_net
    "starting_price": 100,
    "reserve_price": 80,
    "max_rounds": 10
}

Response:
{
    "negotiation_id": "neg_abc123",
    "status": "pending",
    "message": "Waiting for seller to announce"
}
```

### 发布公告 (Seller Agent)
```http
POST /api/v1/trade/negotiations/{id}/announce
{
    "auction_type": "english",
    "duration_minutes": 60
}

Response:
{
    "success": true,
    "status": "active",
    "broadcasted_to": [user_B, user_C]  // 公开协商
}
```

### 买方出价 (Buyer Agent)
```http
POST /api/v1/trade/negotiations/{id}/bid
{
    "amount": 150,
    "qualifications": {"auto": false}
}

Response:
{
    "success": true,
    "bid_placed": true,
    "status": "pending_seller_response"
}
```

### 轮询消息 (Agent Worker)
```http
GET /api/v1/trade/messages/pending

Response:
{
    "messages": [
        {
            "message_id": "msg_123",
            "negotiation_id": "neg_abc",
            "from_user_id": 456,
            "msg_type": "BID",
            "payload": {"amount": 150, "round": 1},
            "created_at": "2024-01-01T12:00:00Z"
        }
    ]
}
```

### 响应出价 (Seller Agent)
```http
POST /api/v1/trade/negotiations/{id}/respond
{
    "response": "counter",  // accept/reject/counter
    "counter_amount": 140
}

Response:
{
    "success": true,
    "response": "counter",
    "status": "active"
}
```

## 并发控制

### 乐观锁机制
```python
# 出价时检查版本
UPDATE negotiation_sessions
SET current_price = 15000,
    current_round = current_round + 1,
    version = version + 1
WHERE negotiation_id = 'neg_abc'
  AND version = current_version  # 防止并发冲突
```

### 消息顺序保证
- 消息队列按 `priority DESC, created_at ASC` 排序
- 同一协商的消息串行处理

## 通知机制

### WebSocket (实时)
```javascript
// 用户建立WebSocket连接
ws = new WebSocket('wss://api.example.com/ws/agent')

// 收到新消息通知
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.event === 'agent.bid') {
        showNotification(`New bid: $${msg.payload.amount}`)
    }
}
```

### Webhook (异步)
```python
# 用户配置Webhook URL
config.webhook_url = "https://user-app.com/webhooks/agent"

# 有新消息时回调
POST https://user-app.com/webhooks/agent
{
    "event": "agent.bid",
    "negotiation_id": "neg_abc",
    "payload": {"amount": 150}
}
```

### 移动端推送
```python
# 集成FCM/APNs
if user.has_mobile_app:
    send_push_notification(
        token=user.device_token,
        title="New Offer",
        body="You received a counter offer of $140"
    )
```

## 部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Load Balancer                            │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  FastAPI      │    │  FastAPI      │    │  FastAPI      │
│  Instance 1   │    │  Instance 2   │    │  Instance 3   │
│               │    │               │    │               │
│ ┌───────────┐ │    │ ┌───────────┐ │    │ ┌───────────┐ │
│ │Agent      │ │    │ │Agent      │ │    │ │Agent      │ │
│ │Worker     │ │    │ │Worker     │ │    │ │Worker     │ │
│ └───────────┘ │    │ └───────────┘ │    │ └───────────┘ │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                  ┌─────────────────────┐
                  │   PostgreSQL        │
                  │   (主从复制)          │
                  └─────────────────────┘
```

## 总结

通过以下设计解决跨用户Agent协商问题：

1. **持久化存储** - 协商状态和消息队列存储在PostgreSQL
2. **异步通信** - 消息队列实现解耦，双方无需同时在线
3. **自动处理** - TradeAgentWorker后台自动处理消息
4. **灵活配置** - 支持全自动/半自动/人工三种模式
5. **实时通知** - WebSocket/Webhook/推送通知用户
