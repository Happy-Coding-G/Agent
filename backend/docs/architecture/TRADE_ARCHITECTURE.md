# Trade Architecture

## 概述

交易模块采用 **直接交易（Direct Trade）** 模式，所有交易统一走 listing -> purchase -> order -> wallet 路径。

协商（bilateral negotiation）和拍卖（auction）机制已移除，以简化系统复杂度。

## 架构组件

```
User Request
    |
    v
TradeWorkflow Agent (.md driven)
    |
    v
TradeToolRegistry
    |-- trade_normalize_goal    # 解析用户交易意图
    |-- trade_select_mechanism  # 统一返回 direct（简化决策）
    |-- trade_execute           # 执行交易动作
    |-- create_listing          # 资产上架
    |-- asset_manage            # 资产管理
    |
    v
TradeService / TradeRepository
    |-- create_listing          # 创建 TradeListings
    |-- purchase                # 创建 TradeOrders
    |-- get_wallet              # 查询 TradeWallets
    |
    v
PostgreSQL (TradeListings, TradeOrders, TradeWallets, TradeHoldings)
```

## 执行流程

### 1. 购买流程

```
用户: "我想购买 listing_123"
  |
  v
trade_normalize_goal -> {intent: BUY_ASSET, listing_id: "listing_123"}
  |
  v
trade_select_mechanism -> {mechanism_type: "direct", engine_type: "simple"}
  |
  v
trade_execute(action="purchase", listing_id="listing_123", buyer=user)
  |
  v
TradeService.purchase()
  - 验证 listing 存在且状态为 active
  - 检查买家余额
  - 扣减买家钱包，增加卖家钱包
  - 创建 TradeOrders 记录
  - 更新 TradeListings 状态为 sold
  |
  v
返回订单结果
```

### 2. 上架流程

```
用户: "我想上架这份报告，定价 200 积分"
  |
  v
trade_normalize_goal -> {intent: SELL_ASSET, asset_id: "asset_456", target_price: 200}
  |
  v
asset_manage(action="get", asset_id="asset_456")  # 确认资产存在
  |
  v
create_listing(asset_id="asset_456", price_credits=200, seller=user)
  |
  v
TradeService.create_listing()
  - 创建 TradeListings 记录
  - 状态设为 active
  |
  v
返回 listing_id
```

## 审批策略

高价值交易自动触发人工审批：

- 目标价格 > 10,000
- 预算上限 > 50,000
- 首次交易
- 用户手动模式（manual_step）

审批由 `ApprovalPolicyService` 统一决策，Agent 不可绕过。

## 代码结构

```
backend/app/
├── schemas/trade_goal.py              # TradeGoal, TradeConstraints, MechanismSelection
├── services/trade/
│   ├── trade_service.py               # 核心交易服务
│   ├── trade_action_service.py        # 交易动作处理
│   ├── unified_trade_service.py       # 统一入口（简化后仅委托 TradeService）
│   ├── mechanism_selection_policy.py  # 机制选择（始终返回 direct）
│   ├── approval_policy_service.py     # 审批策略
│   └── decision_log_service.py        # 决策日志
├── agents/subagents/docs/
│   └── trade_workflow.md              # Trade Agent 定义（ReAct 模式）
└── agents/tools/trade_tools.py        # 交易工具注册
```

## 数据库模型

| 表名 | 用途 |
|------|------|
| `trade_listings` | 上架记录 |
| `trade_orders` | 订单记录 |
| `trade_wallets` | 用户钱包 |
| `trade_holdings` | 资产持有 |
| `trade_transaction_logs` | 交易流水 |

> 注：`negotiation_sessions`、`agent_message_queue`、`escrow_records` 等协商/托管相关表已移除。
