# Trade 系统生产级部署指南

## 概述

已将 Trade 系统从 JSON 文件存储迁移到 PostgreSQL 数据库，解决了以下问题：

1. **并发访问问题** - 使用行级锁 (SELECT FOR UPDATE) 防止竞态条件
2. **缺乏事务支持** - 所有操作使用 ACID 事务
3. **浮点精度问题** - 金额使用整数（分/积分最小单位）存储
4. **审计追踪** - 完整的事务日志记录

## 架构变更

### 数据存储迁移

| 原存储 (JSON 文件) | 新存储 (PostgreSQL) | 说明 |
|-------------------|-------------------|------|
| `state/trade_market/global.json` | `trade_listings` 表 | 上架资产列表 |
| `state/trade_wallets/{user_id}.json` | `trade_wallets` 表 | 用户钱包 |
| `state/trade_orders/{user_id}.json` | `trade_orders` 表 | 订单记录 |
| `state/trade_holdings/{user_id}.json` | `trade_holdings` 表 | 用户持仓 |
| `state/trade_yield_journal/{user_id}.json` | `trade_yield_runs` 表 | 收益日志 |
| - | `trade_transaction_log` 表 | 新增：审计日志 |

### 关键改进

#### 1. 行级锁 (Row-Level Locking)
```python
# 获取钱包并锁定，防止并发修改
wallet = await self._repo.get_wallet(user_id, lock=True)

# 转账时按 ID 排序锁定，防止死锁
user_ids = sorted([from_user_id, to_user_id])
for uid in user_ids:
    wallet = await self.get_wallet(uid, lock=True)
```

#### 2. 乐观锁 (Optimistic Locking)
```python
# TradeWallets 表中的 version 字段
wallet.version += 1  # 每次更新递增

# 可用于检测并发冲突
```

#### 3. 原子操作
```python
# Purchase 流程在一个事务中完成：
# 1. 锁定 listing
# 2. 检查是否已购买
# 3. 锁定买家和卖家钱包
# 4. 扣减买家余额
# 5. 增加卖家余额
# 6. 创建订单
# 7. 创建持仓
# 8. 更新 listing 统计
# 全部成功或全部回滚
```

#### 4. 整数金额存储
```python
# 避免浮点精度问题
price_credits = 25.84  # 显示值
price_cents = 2584      # 存储值（整数）

# 转换函数
credits_to_cents(25.84)  # -> 2584
cents_to_credits(2584)   # -> 25.84
```

## 部署步骤

### 1. 数据库迁移

```bash
# 创建 Alembic 迁移
alembic revision --autogenerate -m "add_trade_tables"

# 或手动执行迁移
alembic upgrade add_trade_tables
```

### 2. 数据迁移（如需要保留现有数据）

```bash
cd backend
python -m scripts.migrate_trade_data
```

此脚本将：
- 读取 `state/` 目录下的 JSON 文件
- 转换数据格式（浮点 -> 整数）
- 写入 PostgreSQL 数据库
- 显示迁移摘要

### 3. 删除旧文件（可选）

数据迁移完成后，可以删除旧的 state 文件：

```bash
rm -rf backend/state/trade_*
```

## 新文件结构

```
backend/
├── app/
│   ├── db/
│   │   └── models.py              # 新增 Trade 相关模型
│   ├── repositories/
│   │   └── trade_repo.py          # 新增：Trade Repository
│   ├── services/
│   │   ├── trade_service.py       # 新增：核心业务逻辑
│   │   └── trade_agent_service.py # 修改：适配器模式
│   └── utils/
│       └── state_store.py         # 保留：其他模块可能使用
├── alembic/
│   └── versions/
│       └── add_trade_tables.py    # 数据库迁移脚本
└── scripts/
    └── migrate_trade_data.py      # 数据迁移脚本
```

## API 兼容性

所有现有 API 端点保持不变：

- `GET /spaces/{space_id}/trade/privacy-policy`
- `GET /spaces/{space_id}/trade/listings`
- `POST /spaces/{space_id}/trade/listings`
- `POST /spaces/{space_id}/trade/auto-yield/run`
- `GET /spaces/{space_id}/trade/yield-journal`
- `GET /trade/market`
- `GET /trade/market/{listing_id}`
- `POST /trade/market/{listing_id}/purchase`
- `GET /trade/orders`
- `GET /trade/orders/{order_id}/delivery`
- `GET /trade/wallet`

## 监控和运维

### 关键指标

```sql
-- 活跃 listing 数量
SELECT COUNT(*) FROM trade_listings WHERE status = 'active';

-- 总交易额
SELECT SUM(price_credits) / 100.0 as total_volume FROM trade_orders;

-- 平台手续费收入
SELECT SUM(platform_fee) / 100.0 as platform_revenue FROM trade_orders;

-- 钱包余额分布
SELECT
    CASE
        WHEN liquid_credits < 1000 THEN '< 10'
        WHEN liquid_credits < 10000 THEN '10-100'
        ELSE '> 100'
    END as balance_range,
    COUNT(*)
FROM trade_wallets
GROUP BY 1;
```

### 审计查询

```sql
-- 查询用户交易历史
SELECT * FROM trade_transaction_log
WHERE user_id = ?
ORDER BY created_at DESC;

-- 检测可疑活动（大额交易）
SELECT * FROM trade_orders
WHERE price_credits > 50000  -- > 500 credits
ORDER BY created_at DESC;

-- 收益发放记录
SELECT * FROM trade_yield_runs
WHERE user_id = ?
ORDER BY created_at DESC;
```

## 故障排除

### 问题：数据库连接失败

检查 `DATABASE_URL` 配置：
```python
# 确保使用异步驱动
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/dbname"
```

### 问题：迁移后数据缺失

1. 检查 JSON 文件是否可读
2. 查看迁移脚本输出日志
3. 手动验证数据：
```sql
SELECT COUNT(*) FROM trade_listings;
SELECT COUNT(*) FROM trade_wallets;
```

### 问题：并发错误

如果出现 `ConcurrentModificationError`，检查：
1. 是否正确使用了 `lock=True` 参数
2. 事务是否正确提交/回滚
3. 是否有长时间运行的事务

## 性能优化建议

1. **连接池配置**
```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
)
```

2. **索引优化**
已有索引：
- `trade_listings(status, seller_user_id, category)`
- `trade_orders(buyer_user_id, seller_user_id, listing_id)`
- `trade_wallets(user_id)`

3. **定期维护**
```sql
-- 清理旧日志（保留 1 年）
DELETE FROM trade_transaction_log
WHERE created_at < NOW() - INTERVAL '1 year';

-- 更新统计信息
ANALYZE trade_listings;
ANALYZE trade_orders;
```

## 安全考虑

1. **delivery_payload_encrypted** 字段已加密存储
2. 敏感信息在 listing 创建时已脱敏
3. 所有金额操作都有审计日志
4. 建议对 `trade_transaction_log` 表启用追加-only 模式或定期备份

## 回滚计划

如需回滚到文件存储：

1. 导出数据库数据到 JSON：
```bash
python -m scripts.export_trade_data  # 需自行实现
```

2. 恢复 `state/` 目录结构

3. 切换代码到旧版本

4. 注意：新创建的数据可能会丢失
