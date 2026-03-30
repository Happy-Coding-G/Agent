from datetime import timedelta
from io import BytesIO
from functools import lru_cache, wraps
from typing import Callable, TypeVar

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.circuit_breakers import minio_circuit_breaker, ServiceCircuitBreaker, CircuitBreakerConfig
from app.core.errors import ServiceError
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")

# MinIO 熔断器配置
MINIO_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=3,
    timeout_seconds=30.0,
    half_open_max_calls=3,
    slow_call_threshold_ms=5000.0,
    slow_call_rate_threshold=60.0,
)


def minio_circuit_breaker_decorator(func: Callable[..., T]) -> Callable[..., T]:
    """MinIO 操作的熔断器装饰器"""
    breaker = ServiceCircuitBreaker.get_breaker("minio", MINIO_CIRCUIT_CONFIG)

    @wraps(func)
    def wrapper(*args, **kwargs):
        import asyncio

        async def async_wrapper():
            can_execute, reason = await breaker.can_execute()
            if not can_execute:
                raise ServiceError(503, f"MinIO service unavailable: {reason}")

            import time
            start_time = time.time()

            try:
                # 检查是否是异步函数
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                await breaker.record_success()
                return result
            except S3Error as e:
                latency_ms = (time.time() - start_time) * 1000
                is_slow = latency_ms > MINIO_CIRCUIT_CONFIG.slow_call_threshold_ms
                await breaker.record_failure(is_slow=is_slow)
                logger.error(f"MinIO S3 error: {e}")
                raise ServiceError(503, f"存储服务错误: {e.message}")
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                is_slow = latency_ms > MINIO_CIRCUIT_CONFIG.slow_call_threshold_ms
                await breaker.record_failure(is_slow=is_slow)
                logger.error(f"MinIO error: {e}")
                raise ServiceError(503, f"存储服务暂时不可用")

        # 如果已经有事件循环，直接运行
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已运行的事件循环中使用 run_coroutine_threadsafe
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, async_wrapper())
                    return future.result()
            else:
                return loop.run_until_complete(async_wrapper())
        except RuntimeError:
            # 没有事件循环，创建新的
            return asyncio.run(async_wrapper())

    return wrapper


class MinioService:
    def __init__(self):
        self._client = None
        self.bucket = "bucket"

    @property
    def client(self) -> Minio:
        """延迟初始化 MinIO 客户端"""
        if self._client is None:
            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            # 验证连接并确保 bucket 存在
            try:
                if not self._client.bucket_exists(self.bucket):
                    self._client.make_bucket(self.bucket)
            except Exception as e:
                logger.error(f"MinIO initialization error: {e}")
                raise ServiceError(503, "存储服务初始化失败")
        return self._client

    @minio_circuit_breaker_decorator
    def get_upload_url(self, object_key: str):
        """Generate presigned upload URL (PUT)."""
        return self.client.presigned_put_object(
            self.bucket, object_key, expires=timedelta(minutes=30)
        )

    @minio_circuit_breaker_decorator
    def get_download_url(self, object_key: str):
        """Generate presigned download URL (GET)."""
        return self.client.presigned_get_object(
            self.bucket, object_key, expires=timedelta(hours=1)
        )

    @minio_circuit_breaker_decorator
    def upload_text(
        self,
        object_key: str,
        content: str,
        content_type: str = "text/markdown; charset=utf-8",
    ):
        data = content.encode("utf-8")
        self.client.put_object(
            self.bucket,
            object_key,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )


@lru_cache()
def get_minio_service() -> MinioService:
    """获取 MinIO 服务单例（带缓存）"""
    return MinioService()


# 延迟初始化的全局实例
minio_service = MinioService()
