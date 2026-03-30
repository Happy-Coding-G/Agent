"""
外部服务熔断器配置

为LLM、Neo4j、MinIO等外部依赖提供熔断保护
"""

from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from app.core.rate_limit import (
    CircuitBreakerConfig,
    ServiceCircuitBreaker,
    circuit_breaker,
)
from app.core.errors import ServiceError

T = TypeVar("T")


# ============================================================================
# 服务级熔断器配置
# ============================================================================

# LLM API 熔断器配置
LLM_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,           # 5次失败触发熔断
    success_threshold=3,           # 3次成功恢复
    timeout_seconds=60.0,          # 熔断60秒
    half_open_max_calls=3,         # 半开状态试探3次
    slow_call_threshold_ms=10000.0,  # 10秒视为慢调用
    slow_call_rate_threshold=50.0,   # 50%慢调用率触发熔断
)

# Neo4j 熔断器配置
NEO4J_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=2,
    timeout_seconds=30.0,
    half_open_max_calls=2,
    slow_call_threshold_ms=5000.0,
    slow_call_rate_threshold=50.0,
)

# MinIO 熔断器配置
MINIO_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=3,
    timeout_seconds=30.0,
    half_open_max_calls=3,
    slow_call_threshold_ms=5000.0,
    slow_call_rate_threshold=60.0,
)

# Embedding 服务熔断器配置
EMBEDDING_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=3,
    timeout_seconds=60.0,
    half_open_max_calls=3,
    slow_call_threshold_ms=15000.0,
    slow_call_rate_threshold=40.0,
)

# Rerank 服务熔断器配置
RERANK_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=3,
    timeout_seconds=60.0,
    half_open_max_calls=3,
    slow_call_threshold_ms=15000.0,
    slow_call_rate_threshold=40.0,
)


# ============================================================================
# 熔断器装饰器便捷函数
# ============================================================================

def llm_circuit_breaker(fallback: Optional[Callable] = None):
    """LLM API 熔断器装饰器"""
    return circuit_breaker(
        service_name="llm_api",
        config=LLM_CIRCUIT_CONFIG,
        fallback=fallback,
    )


def neo4j_circuit_breaker(fallback: Optional[Callable] = None):
    """Neo4j 熔断器装饰器"""
    return circuit_breaker(
        service_name="neo4j",
        config=NEO4J_CIRCUIT_CONFIG,
        fallback=fallback,
    )


def minio_circuit_breaker(fallback: Optional[Callable] = None):
    """MinIO 熔断器装饰器"""
    return circuit_breaker(
        service_name="minio",
        config=MINIO_CIRCUIT_CONFIG,
        fallback=fallback,
    )


def embedding_circuit_breaker(fallback: Optional[Callable] = None):
    """Embedding 服务熔断器装饰器"""
    return circuit_breaker(
        service_name="embedding_service",
        config=EMBEDDING_CIRCUIT_CONFIG,
        fallback=fallback,
    )


def rerank_circuit_breaker(fallback: Optional[Callable] = None):
    """Rerank 服务熔断器装饰器"""
    return circuit_breaker(
        service_name="rerank_service",
        config=RERANK_CIRCUIT_CONFIG,
        fallback=fallback,
    )


# ============================================================================
# 降级函数
# ============================================================================

async def llm_fallback(prompt: str, **kwargs) -> str:
    """LLM 服务降级函数 - 返回友好提示"""
    raise ServiceError(
        503,
        "AI服务暂时不可用，请稍后重试。如果问题持续，请联系支持团队。"
    )


async def embedding_fallback(texts: list[str], **kwargs) -> tuple[list[list[float]], str]:
    """Embedding 服务降级函数 - 使用本地哈希嵌入"""
    import hashlib
    import math
    from typing import Iterable

    def _local_hash_embedding(text: str, dimensions: int = 1536) -> list[float]:
        vector = [0.0] * dimensions
        tokens = text.lower().split()
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if (digest[4] % 2 == 0) else -1.0
            weight = 1.0 + (digest[5] / 255.0)
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    vectors = [_local_hash_embedding(text) for text in texts]
    return vectors, "local-hash-fallback"


async def neo4j_fallback(query: str, **kwargs) -> list[dict]:
    """Neo4j 服务降级函数 - 返回空结果"""
    return []


# ============================================================================
# 带熔断的客户端包装
# ============================================================================

class CircuitBreakerMixin:
    """
    熔断器Mixin类

    为Service类提供熔断保护功能
    """

    async def _with_circuit_breaker(
        self,
        service_name: str,
        operation: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        在熔断器保护下执行操作

        Args:
            service_name: 服务名称
            operation: 要执行的操作
            *args, **kwargs: 操作参数

        Returns:
            操作结果

        Raises:
            ServiceError: 服务熔断时抛出
        """
        breaker = ServiceCircuitBreaker.get_breaker(service_name)

        can_execute, reason = await breaker.can_execute()
        if not can_execute:
            raise ServiceError(503, f"Service unavailable: {reason}")

        import time
        start_time = time.time()

        try:
            result = await operation(*args, **kwargs)
            await breaker.record_success()
            return result
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            config = CircuitBreakerConfig()  # 获取默认配置
            is_slow = latency_ms > config.slow_call_threshold_ms
            await breaker.record_failure(is_slow=is_slow)
            raise
