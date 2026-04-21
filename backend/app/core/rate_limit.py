"""
分布式限流与熔断系统

提供生产级的流量控制能力：
- Redis分布式限流（令牌桶 + 滑动窗口）
- 熔断器模式（Circuit Breaker）
- 自适应限流
- 用户等级限流

架构：
    RedisRateLimiter (基类)
    ├── TokenBucketRateLimiter (令牌桶算法)
    ├── SlidingWindowRateLimiter (滑动窗口算法)
    └── AdaptiveRateLimiter (自适应限流)

    CircuitBreaker (熔断器)
    └── ServiceCircuitBreaker (服务级熔断)

    TieredRateLimiter (用户等级限流)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

import redis.asyncio as redis
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ============================================================================
# Redis 连接管理
# ============================================================================

class RedisManager:
    """Redis连接管理器（支持跨 event loop 自动重建连接）"""

    _instance: Optional[RedisManager] = None
    _redis: Optional[redis.Redis] = None
    _loop_id: Optional[int] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_redis(self) -> redis.Redis:
        """获取Redis连接，自动检测 event loop 变化并重建"""
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)

        if self._redis is None or self._loop_id != current_loop_id:
            async with self._lock:
                if self._redis is None or self._loop_id != current_loop_id:
                    # 关闭旧连接（如果存在）
                    if self._redis is not None:
                        try:
                            await self._redis.close()
                        except Exception:
                            pass
                    # 创建新连接绑定到当前 loop
                    self._redis = redis.from_url(
                        settings.REDIS_URL,
                        encoding="utf-8",
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_keepalive=True,
                        health_check_interval=30,
                    )
                    self._loop_id = current_loop_id
        return self._redis

    async def close(self):
        """关闭Redis连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._loop_id = None


redis_manager = RedisManager()


# ============================================================================
# 限流算法实现
# ============================================================================

class RateLimitAlgorithm(str, Enum):
    """限流算法枚举"""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """限流配置"""
    max_requests: int = 60
    window_seconds: int = 60
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    burst_size: int = 10  # 令牌桶突发容量
    key_prefix: str = "rate_limit"

    # 自适应限流配置
    adaptive_enabled: bool = False
    target_cpu_percent: float = 70.0
    target_latency_ms: float = 500.0
    scale_up_factor: float = 1.1
    scale_down_factor: float = 0.9
    min_rate: int = 10
    max_rate: int = 1000


class BaseRedisRateLimiter:
    """Redis分布式限流基类"""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._redis: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        # 不缓存连接，每次从 RedisManager 获取（自动处理跨 event loop）
        return await redis_manager.get_redis()

    def _make_key(self, identifier: str) -> str:
        """生成Redis键"""
        return f"{self.config.key_prefix}:{identifier}"

    async def is_allowed(self, identifier: str, cost: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """
        检查是否允许请求

        Returns:
            (是否允许, 元数据字典)
        """
        raise NotImplementedError

    async def get_current_state(self, identifier: str) -> Dict[str, Any]:
        """获取当前限流状态"""
        raise NotImplementedError

    async def reset(self, identifier: str):
        """重置限流状态"""
        redis_conn = await self._get_redis()
        key = self._make_key(identifier)
        await redis_conn.delete(key)


class TokenBucketRateLimiter(BaseRedisRateLimiter):
    """
    令牌桶限流器

    优点：
    - 允许突发流量
    - 平滑限流
    - 适合需要应对突发请求的场景

    Redis数据结构：
    - Hash: {tokens: float, last_update: timestamp}
    """

    # Lua脚本确保原子性
    TOKEN_BUCKET_SCRIPT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local rate = tonumber(ARGV[2])  -- 每秒生成令牌数
    local capacity = tonumber(ARGV[3])  -- 桶容量
    local cost = tonumber(ARGV[4])  -- 请求消耗令牌数

    local bucket = redis.call('HMGET', key, 'tokens', 'last_update')
    local tokens = tonumber(bucket[1])
    local last_update = tonumber(bucket[2])

    if tokens == nil then
        tokens = capacity
        last_update = now
    end

    -- 计算新增令牌
    local elapsed = now - last_update
    local new_tokens = math.min(capacity, tokens + elapsed * rate)

    -- 检查是否足够
    local allowed = new_tokens >= cost

    if allowed then
        new_tokens = new_tokens - cost
    end

    -- 更新桶状态
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_update', now)
    redis.call('EXPIRE', key, 60)  -- 60秒过期

    return {allowed and 1 or 0, math.floor(new_tokens)}
    """

    _script_sha: Optional[str] = None

    async def _get_script_sha(self) -> str:
        if self._script_sha is None:
            redis_conn = await self._get_redis()
            self._script_sha = await redis_conn.script_load(self.TOKEN_BUCKET_SCRIPT)
        return self._script_sha

    async def is_allowed(self, identifier: str, cost: int = 1) -> Tuple[bool, Dict[str, Any]]:
        redis_conn = await self._get_redis()
        key = self._make_key(identifier)
        now = time.time()

        rate = self.config.max_requests / self.config.window_seconds
        capacity = min(self.config.burst_size, self.config.max_requests)

        try:
            sha = await self._get_script_sha()
            result = await redis_conn.evalsha(
                sha, 1, key, now, rate, capacity, cost
            )
        except redis.NoScriptError:
            # 脚本不存在，重新加载
            result = await redis_conn.eval(
                self.TOKEN_BUCKET_SCRIPT, 1, key, now, rate, capacity, cost
            )

        allowed = bool(result[0])
        remaining = result[1]

        metadata = {
            "allowed": allowed,
            "remaining": remaining,
            "limit": capacity,
            "reset_after": self.config.window_seconds,
        }

        return allowed, metadata

    async def get_current_state(self, identifier: str) -> Dict[str, Any]:
        redis_conn = await self._get_redis()
        key = self._make_key(identifier)

        bucket = await redis_conn.hmget(key, "tokens", "last_update")
        tokens = float(bucket[0]) if bucket[0] else self.config.burst_size

        return {
            "tokens": tokens,
            "capacity": self.config.burst_size,
            "rate": self.config.max_requests / self.config.window_seconds,
        }


class SlidingWindowRateLimiter(BaseRedisRateLimiter):
    """
    滑动窗口限流器

    优点：
    - 精确的请求计数
    - 防止窗口边缘突发
    - 适合需要精确控制的场景

    Redis数据结构：
    - Sorted Set: {score: timestamp, member: unique_request_id}
    """

    # Lua脚本确保原子性
    SLIDING_WINDOW_SCRIPT = """
    local key = KEYS[1]
    local window_start = tonumber(ARGV[1])
    local now = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local request_id = ARGV[4]
    local window_seconds = tonumber(ARGV[5])

    -- 清理过期请求
    redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

    -- 获取当前请求数
    local current = redis.call('ZCARD', key)

    -- 检查是否允许
    local allowed = current < max_requests

    if allowed then
        redis.call('ZADD', key, now, request_id)
    end

    redis.call('EXPIRE', key, window_seconds + 1)

    local remaining = math.max(0, max_requests - current - (allowed and 1 or 0))
    local reset_after = window_seconds

    -- 获取最早请求的过期时间
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if #oldest > 0 then
        reset_after = math.ceil(tonumber(oldest[2]) + window_seconds - now)
    end

    return {allowed and 1 or 0, remaining, reset_after}
    """

    _script_sha: Optional[str] = None

    async def _get_script_sha(self) -> str:
        if self._script_sha is None:
            redis_conn = await self._get_redis()
            self._script_sha = await redis_conn.script_load(self.SLIDING_WINDOW_SCRIPT)
        return self._script_sha

    async def is_allowed(self, identifier: str, cost: int = 1) -> Tuple[bool, Dict[str, Any]]:
        redis_conn = await self._get_redis()
        key = self._make_key(identifier)
        now = time.time()
        window_start = now - self.config.window_seconds
        request_id = f"{now}:{random.randint(1000, 9999)}"

        try:
            sha = await self._get_script_sha()
            result = await redis_conn.evalsha(
                sha, 1, key, window_start, now,
                self.config.max_requests, request_id,
                self.config.window_seconds
            )
        except redis.NoScriptError:
            result = await redis_conn.eval(
                self.SLIDING_WINDOW_SCRIPT, 1, key, window_start, now,
                self.config.max_requests, request_id,
                self.config.window_seconds
            )

        allowed = bool(result[0])
        remaining = result[1]
        reset_after = result[2]

        metadata = {
            "allowed": allowed,
            "remaining": remaining,
            "limit": self.config.max_requests,
            "reset_after": reset_after,
        }

        return allowed, metadata

    async def get_current_state(self, identifier: str) -> Dict[str, Any]:
        redis_conn = await self._get_redis()
        key = self._make_key(identifier)
        now = time.time()
        window_start = now - self.config.window_seconds

        # 清理并计数
        pipe = redis_conn.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        _, current = await pipe.execute()

        return {
            "current_requests": current,
            "max_requests": self.config.max_requests,
            "window_seconds": self.config.window_seconds,
        }


class AdaptiveRateLimiter(BaseRedisRateLimiter):
    """
    自适应限流器

    根据系统负载动态调整限流阈值：
    - CPU使用率过高 -> 降低限流阈值
    - 延迟过高 -> 降低限流阈值
    - 系统空闲 -> 提高限流阈值

    Redis数据结构：
    - Hash: {current_limit: int, last_update: timestamp, metrics: json}
    """

    def __init__(self, config: RateLimitConfig):
        super().__init__(config)
        if not config.adaptive_enabled:
            raise ValueError("Adaptive rate limiter requires adaptive_enabled=True")
        self._current_limit = config.max_requests

    async def is_allowed(self, identifier: str, cost: int = 1) -> Tuple[bool, Dict[str, Any]]:
        # 先更新限流阈值
        await self._adapt_rate(identifier)

        # 使用滑动窗口检查
        limiter = SlidingWindowRateLimiter(RateLimitConfig(
            max_requests=self._current_limit,
            window_seconds=self.config.window_seconds,
            key_prefix=f"{self.config.key_prefix}:adaptive",
        ))

        allowed, metadata = await limiter.is_allowed(identifier, cost)
        metadata["adaptive_limit"] = self._current_limit
        metadata["base_limit"] = self.config.max_requests

        return allowed, metadata

    async def _adapt_rate(self, identifier: str):
        """根据系统指标调整限流速率"""
        redis_conn = await self._get_redis()
        key = f"{self.config.key_prefix}:adaptive:{identifier}:metrics"

        # 获取当前指标（实际应用中应从监控系统获取）
        metrics_json = await redis_conn.get(key)
        if metrics_json:
            metrics = json.loads(metrics_json)
            cpu_percent = metrics.get("cpu_percent", 50.0)
            latency_ms = metrics.get("latency_ms", 100.0)
        else:
            # 默认指标
            cpu_percent = 50.0
            latency_ms = 100.0

        # 计算调整因子
        old_limit = self._current_limit

        if cpu_percent > self.config.target_cpu_percent or latency_ms > self.config.target_latency_ms:
            # 系统过载，降低限流
            self._current_limit = int(self._current_limit * self.config.scale_down_factor)
        else:
            # 系统空闲，提高限流
            self._current_limit = int(self._current_limit * self.config.scale_up_factor)

        # 边界限制
        self._current_limit = max(
            self.config.min_rate,
            min(self.config.max_rate, self._current_limit)
        )

        if old_limit != self._current_limit:
            logger.info(
                f"Adaptive rate adjusted: {old_limit} -> {self._current_limit} "
                f"(CPU: {cpu_percent:.1f}%, Latency: {latency_ms:.1f}ms)"
            )

    async def report_metrics(self, identifier: str, cpu_percent: float, latency_ms: float):
        """报告系统指标"""
        redis_conn = await self._get_redis()
        key = f"{self.config.key_prefix}:adaptive:{identifier}:metrics"

        metrics = {
            "cpu_percent": cpu_percent,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }

        await redis_conn.setex(key, 60, json.dumps(metrics))

    async def get_current_state(self, identifier: str) -> Dict[str, Any]:
        return {
            "current_limit": self._current_limit,
            "base_limit": self.config.max_requests,
            "min_rate": self.config.min_rate,
            "max_rate": self.config.max_rate,
        }


# ============================================================================
# 熔断器实现
# ============================================================================

class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态，允许请求
    OPEN = "open"          # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，试探性允许请求


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5           # 触发熔断的失败次数
    success_threshold: int = 3           # 半开状态恢复所需的成功次数
    timeout_seconds: float = 30.0        # 熔断持续时间
    half_open_max_calls: int = 3         # 半开状态最大试探请求数
    slow_call_threshold_ms: float = 1000.0  # 慢调用阈值
    slow_call_rate_threshold: float = 50.0  # 慢调用比例阈值（百分比）


class CircuitBreaker:
    """
    熔断器模式实现

    状态流转：
    CLOSED -> OPEN: 失败次数达到阈值
    OPEN -> HALF_OPEN: 熔断超时
    HALF_OPEN -> CLOSED: 成功次数达到阈值
    HALF_OPEN -> OPEN: 再次失败
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig,
    ):
        self.name = name
        self.config = config
        self._redis: Optional[redis.Redis] = None
        self._key_prefix = f"circuit_breaker:{name}"

    async def _get_redis(self) -> redis.Redis:
        # 不缓存连接，每次从 RedisManager 获取（自动处理跨 event loop）
        return await redis_manager.get_redis()

    def _get_state_key(self) -> str:
        return f"{self._key_prefix}:state"

    def _get_metrics_key(self) -> str:
        return f"{self._key_prefix}:metrics"

    async def get_state(self) -> CircuitState:
        """获取当前熔断状态"""
        redis_conn = await self._get_redis()
        state_str = await redis_conn.get(self._get_state_key())

        if state_str:
            return CircuitState(state_str)
        return CircuitState.CLOSED

    async def _set_state(self, state: CircuitState):
        """设置熔断状态"""
        redis_conn = await self._get_redis()
        await redis_conn.set(self._get_state_key(), state.value)
        logger.info(f"Circuit breaker '{self.name}' state changed to {state.value}")

    async def can_execute(self) -> Tuple[bool, Optional[str]]:
        """
        检查是否可以执行请求

        Returns:
            (是否允许, 拒绝原因)
        """
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True, None

        if state == CircuitState.OPEN:
            # 检查是否超时
            redis_conn = await self._get_redis()
            opened_at = await redis_conn.get(f"{self._key_prefix}:opened_at")

            if opened_at:
                elapsed = time.time() - float(opened_at)
                if elapsed >= self.config.timeout_seconds:
                    # 超时，进入半开状态
                    await self._set_state(CircuitState.HALF_OPEN)
                    await redis_conn.set(
                        f"{self._key_prefix}:half_open_calls", 0
                    )
                    return True, None

            return False, f"Circuit breaker is OPEN (retry after {self.config.timeout_seconds}s)"

        if state == CircuitState.HALF_OPEN:
            # 检查半开状态请求数
            redis_conn = await self._get_redis()
            calls = await redis_conn.get(f"{self._key_prefix}:half_open_calls")

            if calls and int(calls) >= self.config.half_open_max_calls:
                return False, "Circuit breaker HALF_OPEN: max calls reached"

            # 增加计数
            await redis_conn.incr(f"{self._key_prefix}:half_open_calls")
            return True, None

        return True, None

    async def record_success(self):
        """记录成功"""
        redis_conn = await self._get_redis()
        state = await self.get_state()

        # 重置失败计数
        await redis_conn.delete(f"{self._key_prefix}:failures")

        if state == CircuitState.HALF_OPEN:
            # 增加成功计数
            successes = await redis_conn.incr(f"{self._key_prefix}:successes")

            if successes >= self.config.success_threshold:
                # 恢复关闭状态
                await self._set_state(CircuitState.CLOSED)
                await redis_conn.delete(f"{self._key_prefix}:successes")
                await redis_conn.delete(f"{self._key_prefix}:half_open_calls")

    async def record_failure(self, is_slow: bool = False):
        """记录失败"""
        redis_conn = await self._get_redis()
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            # 半开状态再次失败，重新熔断
            await self._set_state(CircuitState.OPEN)
            await redis_conn.set(f"{self._key_prefix}:opened_at", time.time())
            await redis_conn.delete(f"{self._key_prefix}:successes")
            await redis_conn.delete(f"{self._key_prefix}:half_open_calls")
            return

        # 增加失败计数
        failures = await redis_conn.incr(f"{self._key_prefix}:failures")

        # 检查是否达到阈值
        if failures >= self.config.failure_threshold:
            await self._set_state(CircuitState.OPEN)
            await redis_conn.set(f"{self._key_prefix}:opened_at", time.time())

    async def record_slow_call(self):
        """记录慢调用"""
        redis_conn = await self._get_redis()
        await redis_conn.incr(f"{self._key_prefix}:slow_calls")

        # 检查慢调用比例
        total = int(await redis_conn.get(f"{self._key_prefix}:total_calls") or 0)
        slow = int(await redis_conn.get(f"{self._key_prefix}:slow_calls") or 0)

        if total > 10:  # 至少10个样本
            slow_rate = (slow / total) * 100
            if slow_rate >= self.config.slow_call_rate_threshold:
                await self._set_state(CircuitState.OPEN)
                await redis_conn.set(f"{self._key_prefix}:opened_at", time.time())

    async def get_metrics(self) -> Dict[str, Any]:
        """获取熔断器指标"""
        redis_conn = await self._get_redis()

        state = await self.get_state()
        failures = int(await redis_conn.get(f"{self._key_prefix}:failures") or 0)
        successes = int(await redis_conn.get(f"{self._key_prefix}:successes") or 0)

        opened_at = await redis_conn.get(f"{self._key_prefix}:opened_at")
        time_until_retry = None
        if opened_at and state == CircuitState.OPEN:
            elapsed = time.time() - float(opened_at)
            time_until_retry = max(0, self.config.timeout_seconds - elapsed)

        return {
            "name": self.name,
            "state": state.value,
            "failures": failures,
            "successes": successes,
            "failure_threshold": self.config.failure_threshold,
            "success_threshold": self.config.success_threshold,
            "timeout_seconds": self.config.timeout_seconds,
            "time_until_retry": time_until_retry,
        }

    async def reset(self):
        """重置熔断器"""
        redis_conn = await self._get_redis()

        pattern = f"{self._key_prefix}:*"
        keys = await redis_conn.keys(pattern)
        if keys:
            await redis_conn.delete(*keys)

        await self._set_state(CircuitState.CLOSED)


class ServiceCircuitBreaker:
    """
    服务级熔断器管理

    为不同服务提供独立的熔断保护
    """

    _breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get_breaker(
        cls,
        service_name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """获取或创建熔断器"""
        if service_name not in cls._breakers:
            cls._breakers[service_name] = CircuitBreaker(
                name=service_name,
                config=config or CircuitBreakerConfig(),
            )
        return cls._breakers[service_name]

    @classmethod
    async def reset_all(cls):
        """重置所有熔断器"""
        for breaker in cls._breakers.values():
            await breaker.reset()


# ============================================================================
# 用户等级限流
# ============================================================================

class UserTier(str, Enum):
    """用户等级"""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    INTERNAL = "internal"


# 各等级默认限流配置
TIER_RATE_LIMITS: Dict[UserTier, Dict[str, RateLimitConfig]] = {
    UserTier.FREE: {
        "default": RateLimitConfig(max_requests=100, window_seconds=60),
        "chat": RateLimitConfig(max_requests=30, window_seconds=60),
        "upload": RateLimitConfig(max_requests=50, window_seconds=60),
        "api": RateLimitConfig(max_requests=200, window_seconds=60),
    },
    UserTier.PRO: {
        "default": RateLimitConfig(max_requests=120, window_seconds=60),
        "chat": RateLimitConfig(max_requests=60, window_seconds=60),
        "upload": RateLimitConfig(max_requests=20, window_seconds=60),
        "api": RateLimitConfig(max_requests=500, window_seconds=60),
    },
    UserTier.ENTERPRISE: {
        "default": RateLimitConfig(max_requests=600, window_seconds=60),
        "chat": RateLimitConfig(max_requests=300, window_seconds=60),
        "upload": RateLimitConfig(max_requests=100, window_seconds=60),
        "api": RateLimitConfig(max_requests=2000, window_seconds=60),
    },
    UserTier.INTERNAL: {
        "default": RateLimitConfig(max_requests=1000, window_seconds=60),
        "chat": RateLimitConfig(max_requests=500, window_seconds=60),
        "upload": RateLimitConfig(max_requests=200, window_seconds=60),
        "api": RateLimitConfig(max_requests=5000, window_seconds=60),
    },
}


class TieredRateLimiter:
    """
    用户等级限流器

    根据用户等级应用不同的限流策略
    """

    def __init__(self):
        self._limiters: Dict[Tuple[UserTier, str], BaseRedisRateLimiter] = {}

    def _get_limiter(
        self,
        tier: UserTier,
        endpoint_type: str = "default",
        algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW,
    ) -> BaseRedisRateLimiter:
        """获取对应等级的限流器"""
        key = (tier, endpoint_type)

        if key not in self._limiters:
            config = TIER_RATE_LIMITS.get(tier, {}).get(
                endpoint_type,
                TIER_RATE_LIMITS[tier]["default"]
            )
            config.algorithm = algorithm

            if algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                limiter = TokenBucketRateLimiter(config)
            else:
                limiter = SlidingWindowRateLimiter(config)

            self._limiters[key] = limiter

        return self._limiters[key]

    async def is_allowed(
        self,
        user_id: str,
        tier: UserTier,
        endpoint_type: str = "default",
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        检查用户请求是否允许

        Args:
            user_id: 用户ID
            tier: 用户等级
            endpoint_type: 端点类型 (default/chat/upload/api)

        Returns:
            (是否允许, 元数据)
        """
        limiter = self._get_limiter(tier, endpoint_type)
        allowed, metadata = await limiter.is_allowed(f"{tier.value}:{user_id}")

        metadata["tier"] = tier.value
        metadata["endpoint_type"] = endpoint_type

        return allowed, metadata

    def get_tier_limits(self, tier: UserTier) -> Dict[str, Dict[str, Any]]:
        """获取等级的限流配置"""
        limits = TIER_RATE_LIMITS.get(tier, TIER_RATE_LIMITS[UserTier.FREE])
        return {
            endpoint: {
                "max_requests": config.max_requests,
                "window_seconds": config.window_seconds,
                "algorithm": config.algorithm.value,
            }
            for endpoint, config in limits.items()
        }


# 全局用户等级限流器实例
tiered_limiter = TieredRateLimiter()


# ============================================================================
# 便捷限流器实例
# ============================================================================

# 认证端点限流（严格）
auth_limiter = SlidingWindowRateLimiter(RateLimitConfig(
    max_requests=5,
    window_seconds=60,
    key_prefix="rate_limit:auth",
))

# API通用限流
api_limiter = SlidingWindowRateLimiter(RateLimitConfig(
    max_requests=60,
    window_seconds=60,
    key_prefix="rate_limit:api",
))

# 聊天端点限流
chat_limiter = SlidingWindowRateLimiter(RateLimitConfig(
    max_requests=30,
    window_seconds=60,
    key_prefix="rate_limit:chat",
))

# 上传端点限流
upload_limiter = TokenBucketRateLimiter(RateLimitConfig(
    max_requests=10,
    window_seconds=60,
    burst_size=5,
    key_prefix="rate_limit:upload",
))

# 自适应限流器（用于高负载端点）
adaptive_limiter = AdaptiveRateLimiter(RateLimitConfig(
    max_requests=100,
    window_seconds=60,
    adaptive_enabled=True,
    min_rate=20,
    max_rate=200,
    key_prefix="rate_limit:adaptive",
))


# ============================================================================
# 装饰器和中间件
# ============================================================================

def circuit_breaker(
    service_name: str,
    config: Optional[CircuitBreakerConfig] = None,
    fallback: Optional[Callable] = None,
):
    """
    熔断器装饰器

    示例：
        @circuit_breaker("deepseek_api", fallback=local_llm_fallback)
        async def call_deepseek(prompt: str) -> str:
            ...
    """
    breaker = ServiceCircuitBreaker.get_breaker(service_name, config)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            can_execute, reason = await breaker.can_execute()

            if not can_execute:
                if fallback:
                    return await fallback(*args, **kwargs)
                raise ServiceError(503, f"Service unavailable: {reason}")

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                await breaker.record_success()
                return result
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                is_slow = latency_ms > (config.slow_call_threshold_ms if config else 1000)
                await breaker.record_failure(is_slow=is_slow)
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # 同步函数需要使用asyncio运行
            return asyncio.run(async_wrapper(*args, **kwargs))

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def rate_limit(
    max_requests: int = 60,
    window_seconds: int = 60,
    key_func: Optional[Callable[[Request], str]] = None,
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW,
    tier_based: bool = False,
    endpoint_type: str = "default",
):
    """
    限流装饰器

    示例：
        @router.post("/login")
        @rate_limit(max_requests=5, window_seconds=60)
        async def login(request: Request, ...):
            ...
    """
    config = RateLimitConfig(
        max_requests=max_requests,
        window_seconds=window_seconds,
        algorithm=algorithm,
    )

    if algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
        limiter = TokenBucketRateLimiter(config)
    else:
        limiter = SlidingWindowRateLimiter(config)

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            request = None

            # 从参数中查找Request对象
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                request = kwargs.get("request")

            if request:
                if key_func:
                    identifier = key_func(request)
                else:
                    client = request.client
                    identifier = client.host if client else "unknown"

                # 如果启用了等级限流，尝试获取用户等级
                if tier_based:
                    tier = getattr(request.state, "user_tier", UserTier.FREE)
                    allowed, metadata = await tiered_limiter.is_allowed(
                        identifier, tier, endpoint_type
                    )
                else:
                    allowed, metadata = await limiter.is_allowed(identifier)

                if not allowed:
                    retry_after = metadata.get("reset_after", window_seconds)
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "Too many requests",
                            "retry_after": retry_after,
                            "limit": metadata.get("limit"),
                        },
                        headers={"Retry-After": str(retry_after)},
                    )

                # 将限流信息存入请求状态
                request.state.rate_limit = metadata

            return await func(*args, **kwargs)

        return async_wrapper

    return decorator


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    限流中间件

    提供全站级别的限流保护
    """

    def __init__(
        self,
        app,
        exempt_paths: Optional[List[str]] = None,
        enable_tier_based: bool = True,
    ):
        super().__init__(app)
        self.exempt_paths = exempt_paths or ["/healthz", "/api/v1/healthz"]
        self.enable_tier_based = enable_tier_based
        self.tiered_limiter = TieredRateLimiter()

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        if request.client:
            return request.client.host

        return "unknown"

    def _get_endpoint_type(self, path: str) -> str:
        """根据路径判断端点类型"""
        if "/auth/" in path or path.endswith("/login") or path.endswith("/register"):
            return "auth"
        elif "/chat" in path:
            return "chat"
        elif "/upload" in path or "/files" in path:
            return "upload"
        elif "/api/" in path:
            return "api"
        return "default"

    async def dispatch(self, request: Request, call_next):
        # 跳过豁免路径
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        endpoint_type = self._get_endpoint_type(request.url.path)

        # 尝试获取用户等级
        tier = UserTier.FREE
        if self.enable_tier_based and hasattr(request.state, "user_tier"):
            tier = request.state.user_tier
        else:
            # 中间件在 auth 依赖之前执行，通过 Authorization 头判断已登录用户并放宽限制
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                tier = UserTier.INTERNAL

        # 检查限流
        allowed, metadata = await self.tiered_limiter.is_allowed(
            client_ip, tier, endpoint_type
        )

        if not allowed:
            retry_after = metadata.get("reset_after", 60)
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.url.path} "
                f"(tier: {tier.value})"
            )

            return Response(
                status_code=429,
                content=json.dumps({
                    "error": "Too many requests",
                    "retry_after": retry_after,
                    "tier": tier.value,
                }),
                headers={
                    "Content-Type": "application/json",
                    "X-RateLimit-Limit": str(metadata.get("limit", 60)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                    "Retry-After": str(retry_after),
                },
            )

        # 执行请求
        response = await call_next(request)

        # 添加限流响应头
        response.headers["X-RateLimit-Limit"] = str(metadata.get("limit", 60))
        response.headers["X-RateLimit-Remaining"] = str(metadata.get("remaining", 0))
        response.headers["X-RateLimit-Tier"] = tier.value

        return response


# ============================================================================
# 管理API工具函数
# ============================================================================

async def get_rate_limit_status(identifier: Optional[str] = None) -> Dict[str, Any]:
    """获取限流状态"""
    redis_conn = await redis_manager.get_redis()

    if identifier:
        # 获取特定标识符的状态
        pattern = f"rate_limit:*:{identifier}"
    else:
        # 获取所有状态
        pattern = "rate_limit:*"

    keys = await redis_conn.keys(pattern)
    status = {}

    for key in keys:
        key_type = await redis_conn.type(key)
        key_str = key.decode() if isinstance(key, bytes) else key

        if key_type == "hash":
            data = await redis_conn.hgetall(key)
            status[key_str] = {k.decode() if isinstance(k, bytes) else k:
                              v.decode() if isinstance(v, bytes) else v
                              for k, v in data.items()}
        elif key_type == "zset":
            count = await redis_conn.zcard(key)
            status[key_str] = {"count": count}

    return status


async def reset_rate_limit(identifier: str):
    """重置限流状态"""
    redis_conn = await redis_manager.get_redis()
    pattern = f"rate_limit:*:{identifier}"
    keys = await redis_conn.keys(pattern)

    if keys:
        await redis_conn.delete(*keys)
        return True
    return False


async def get_circuit_breaker_status() -> Dict[str, Any]:
    """获取所有熔断器状态"""
    breaker_names = list(ServiceCircuitBreaker._breakers.keys())
    status = {}

    for name in breaker_names:
        breaker = ServiceCircuitBreaker.get_breaker(name)
        status[name] = await breaker.get_metrics()

    return status


# ============================================================================
# 兼容旧版API（保持向后兼容）
# ============================================================================

class RateLimiter:
    """
    兼容旧版内存限流器

    已弃用：请使用Redis分布式限流器
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._delegate = SlidingWindowRateLimiter(RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
            key_prefix="rate_limit:legacy",
        ))
        logger.warning("RateLimiter is deprecated, use Redis-based limiters instead")

    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """同步接口（已弃用）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            allowed, metadata = loop.run_until_complete(
                self._delegate.is_allowed(identifier)
            )
            return allowed, metadata.get("remaining", 0)
        except RuntimeError:
            # 没有事件循环，创建新的
            return asyncio.run(self._delegate.is_allowed(identifier))[0], 0

    def get_retry_after(self, identifier: str) -> int:
        """获取重试时间"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            metadata = loop.run_until_complete(
                self._delegate.get_current_state(identifier)
            )
            return self.window_seconds
        except RuntimeError:
            return self.window_seconds

    def cleanup(self):
        """清理（无需操作）"""
        pass