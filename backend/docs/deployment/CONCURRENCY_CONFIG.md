# 并发控制配置指南

本文档说明项目中的并发控制机制和配置选项。

## 概述

项目实现了以下并发控制能力：

1. **分布式限流** - 基于 Redis 的令牌桶/滑动窗口限流
2. **用户等级限流** - FREE/PRO/ENTERPRISE/INTERNAL 四级限流
3. **熔断器模式** - LLM、Neo4j、MinIO、Embedding 服务的熔断保护
4. **分布式缓存** - 基于 Redis 的跨实例共享缓存
5. **数据库连接池** - 可配置的连接池大小
6. **聊天队列削峰** - Celery 异步处理高并发聊天

## 配置项

### 1. 数据库连接池配置

```env
# 连接池大小（根据并发量调整）
DB_POOL_SIZE=20

# 最大溢出连接数
DB_MAX_OVERFLOW=40

# 连接池超时（秒）
DB_POOL_TIMEOUT=30

# 连接回收时间（秒）
DB_POOL_RECYCLE=3600

# 只读副本 URL（可选，用于读写分离）
READ_REPLICA_URL=postgresql://user:pass@readonly-host:5432/db
```

### 2. 限流配置

```env
# 限流通过 app/core/rate_limit.py 中的 TIER_RATE_LIMITS 配置
# 环境变量可通过代码中的默认值使用
```

**默认等级限流配置：**

| 等级 | 默认请求/min | 聊天/min | 上传/min |
|------|------------|---------|---------|
| FREE | 30 | 10 | 5 |
| PRO | 120 | 60 | 20 |
| ENTERPRISE | 600 | 300 | 100 |
| INTERNAL | 1000 | 500 | 200 |

### 3. 熔断器配置

熔断器自动管理，无需手动配置。服务状态可通过 API 查询：

```python
from app.core.rate_limit import get_circuit_breaker_status

status = await get_circuit_breaker_status()
# 返回各服务的熔断状态
```

**熔断阈值（代码中配置）：**

| 服务 | 失败阈值 | 恢复成功数 | 熔断超时 |
|------|---------|----------|---------|
| LLM | 5 | 3 | 60s |
| Neo4j | 3 | 2 | 30s |
| MinIO | 5 | 3 | 30s |
| Embedding | 5 | 3 | 60s |

### 4. 缓存配置

缓存使用 Redis，无需额外配置：

```env
REDIS_URL=redis://localhost:6379/0
```

### 5. 文档摄取配置

```env
# 默认 False，使用 Celery 异步处理
# 设置为 True 可在开发环境同步处理
SYNC_INGEST=false
```

### 6. 聊天队列配置

```env
# 是否启用队列模式
CHAT_QUEUE_ENABLED=false

# 模式：sync（同步）或 queue（异步）
CHAT_QUEUE_MODE=sync

# 轮询间隔和最大轮询次数
CHAT_QUEUE_POLL_INTERVAL=0.5
CHAT_QUEUE_MAX_POLLS=120
```

## 高并发部署建议

### 1. Gunicorn/Uvicorn 配置

```python
# gunicorn.conf.py
workers = 4  # 2-4 x CPU核心数
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
```

### 2. Celery Worker 配置

```bash
# 启动多个 worker
celery -A app.celery_worker.celery_app worker \
    --loglevel=info \
    --queues=celery,ingest,chat \
    --concurrency=4
```

### 3. 数据库连接池

| 部署规模 | DB_POOL_SIZE | DB_MAX_OVERFLOW |
|---------|--------------|----------------|
| 小型 (2核4G) | 10 | 20 |
| 中型 (4核8G) | 20 | 40 |
| 大型 (8核16G+) | 40 | 80 |

### 4. Redis 配置

```env
# 生产环境建议使用 Redis Cluster 或 Sentinel
REDIS_URL=redis://redis-cluster:6379/0
```

## 监控和调试

### 查看限流状态

```python
from app.core.rate_limit import get_rate_limit_status

status = await get_rate_limit_status(identifier="user_123")
```

### 查看熔断器状态

```python
from app.core.rate_limit import get_circuit_breaker_status

status = await get_circuit_breaker_status()
# {"llm_api": {"state": "closed", "failures": 0, ...}, ...}
```

### 查看缓存统计

```python
from app.core.cache import cache_manager

stats = cache_manager.get_stats()
# {"total_keys": 100, "namespaces": {"user": 50, "space": 30}}
```

## 常见问题

### Q: 如何启用聊天队列模式？

A: 设置环境变量：
```env
CHAT_QUEUE_ENABLED=true
CHAT_QUEUE_MODE=queue
```

### Q: 熔断后如何恢复？

A: 熔断器自动恢复，无需手动操作。超时后会自动进入半开状态，试探性放行请求。

### Q: 如何调整用户限流阈值？

A: 修改 `app/core/rate_limit.py` 中的 `TIER_RATE_LIMITS` 字典。

### Q: 数据库连接池满了怎么办？

A: 1. 增加 `DB_POOL_SIZE` 和 `DB_MAX_OVERFLOW`
   2. 检查是否有慢查询
   3. 增加 Gunicorn worker 数量分担压力
