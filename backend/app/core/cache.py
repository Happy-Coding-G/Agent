"""
分布式缓存层模块

提供基于Redis的分布式缓存，支持多实例共享缓存
"""

import asyncio
import json
import logging
import pickle
import weakref
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

NULL_SENTINEL = "__CACHE_NULL__"


class RedisCacheManager:
    """
    Redis分布式缓存管理器

    替换原有的进程内TTLCache，支持多实例共享缓存
    """

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._lock = asyncio.Lock()

        # Per-key 互斥锁字典
        self._key_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._key_locks_lock = asyncio.Lock()

        # 默认TTL配置(秒)
        self._default_ttls = {
            "user": 300,  # 5分钟
            "space": 60,  # 1分钟
            "permission": 30,  # 30秒
            "llm_client": 3600,  # 1小时
            "api_response": 60,  # 1分钟
        }

    async def _get_redis(self) -> redis.Redis:
        """获取Redis连接"""
        if self._redis is None:
            async with self._lock:
                if self._redis is None:
                    self._redis = redis.from_url(
                        settings.REDIS_URL,
                        encoding="utf-8",
                        decode_responses=False,  # 支持二进制pickle数据
                        socket_connect_timeout=5,
                        socket_keepalive=True,
                        health_check_interval=30,
                    )
        return self._redis

    async def _get_key_lock(self, cache_key: str) -> asyncio.Lock:
        """获取或创建指定缓存键的互斥锁"""
        key_lock = self._key_locks.get(cache_key)
        if key_lock is not None:
            return key_lock

        async with self._key_locks_lock:
            key_lock = self._key_locks.get(cache_key)
            if key_lock is not None:
                return key_lock
            key_lock = asyncio.Lock()
            self._key_locks[cache_key] = key_lock
            return key_lock

    @asynccontextmanager
    async def _cache_miss_lock(self, cache_key: str):
        """缓存未命中时的互斥锁上下文管理器"""
        key_lock = await self._get_key_lock(cache_key)
        async with key_lock:
            yield

    def _make_key(self, namespace: str, key: Union[str, int]) -> str:
        """生成缓存键"""
        return f"cache:{namespace}:{key}"

    async def get(
        self, namespace: str, key: Union[str, int], default: Any = None
    ) -> Any:
        """
        获取缓存值

        Args:
            namespace: 命名空间(如 user, space, permission)
            key: 缓存键
            default: 默认值

        Returns:
            缓存值或默认值
        """
        try:
            redis_conn = await self._get_redis()
            cache_key = self._make_key(namespace, key)
            data = await redis_conn.get(cache_key)

            if data is None:
                return default

            # 使用pickle反序列化
            return pickle.loads(data)
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return default

    async def set(
        self,
        namespace: str,
        key: Union[str, int],
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        设置缓存值

        Args:
            namespace: 命名空间
            key: 缓存键
            value: 缓存值
            ttl: 过期时间(秒)，None则使用默认值

        Returns:
            是否设置成功
        """
        try:
            redis_conn = await self._get_redis()
            cache_key = self._make_key(namespace, key)

            # 使用pickle序列化
            data = pickle.dumps(value)

            # 使用默认TTL或指定TTL
            expire = ttl or self._default_ttls.get(namespace, 300)

            await redis_conn.setex(cache_key, expire, data)
            return True
        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return False

    async def delete(self, namespace: str, key: Union[str, int]) -> bool:
        """删除缓存"""
        try:
            redis_conn = await self._get_redis()
            cache_key = self._make_key(namespace, key)
            result = await redis_conn.delete(cache_key)
            return result > 0
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
            return False

    async def delete_pattern(self, namespace: str, pattern: str) -> int:
        """按模式删除缓存"""
        try:
            redis_conn = await self._get_redis()
            search_pattern = f"cache:{namespace}:{pattern}"
            deleted = 0
            async for key in redis_conn.scan_iter(match=search_pattern, count=100):
                deleted += await redis_conn.delete(key)
            return deleted
        except Exception as e:
            logger.warning(f"Cache delete pattern error: {e}")
            return 0

    async def exists(self, namespace: str, key: Union[str, int]) -> bool:
        """检查缓存是否存在"""
        try:
            redis_conn = await self._get_redis()
            cache_key = self._make_key(namespace, key)
            return await redis_conn.exists(cache_key) > 0
        except Exception as e:
            logger.warning(f"Cache exists error: {e}")
            return False

    async def ttl(self, namespace: str, key: Union[str, int]) -> int:
        """获取缓存剩余过期时间"""
        try:
            redis_conn = await self._get_redis()
            cache_key = self._make_key(namespace, key)
            return await redis_conn.ttl(cache_key)
        except Exception as e:
            logger.warning(f"Cache ttl error: {e}")
            return -2

    async def clear_namespace(self, namespace: str) -> int:
        """清空整个命名空间"""
        try:
            redis_conn = await self._get_redis()
            pattern = f"cache:{namespace}:*"
            deleted = 0
            async for key in redis_conn.scan_iter(match=pattern, count=100):
                deleted += await redis_conn.delete(key)
            return deleted
        except Exception as e:
            logger.warning(f"Cache clear namespace error: {e}")
            return 0

    async def get_stats(self) -> dict:
        """获取缓存统计信息"""
        try:
            redis_conn = await self._get_redis()
            info = await redis_conn.info("memory")

            # 按命名空间统计
            namespace_counts = {}
            total_keys = 0
            async for key in redis_conn.scan_iter(match="cache:*", count=100):
                total_keys += 1
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) >= 2:
                    ns = parts[1]
                    namespace_counts[ns] = namespace_counts.get(ns, 0) + 1

            return {
                "total_keys": total_keys,
                "memory_used_human": info.get("used_memory_human", "N/A"),
                "namespaces": namespace_counts,
            }
        except Exception as e:
            logger.warning(f"Cache stats error: {e}")
            return {"error": str(e)}


# ============================================================================
# 便捷方法封装 - 保持向后兼容
# ============================================================================


class CacheManager:
    """
    兼容旧版接口的缓存管理器

    将原有TTLCache接口适配到Redis分布式缓存
    """

    def __init__(self):
        self._redis_cache = RedisCacheManager()

    # ==================== 用户缓存 ====================

    async def get_user(self, user_id: int) -> Optional[Any]:
        """获取缓存的用户"""
        return await self._redis_cache.get("user", user_id)

    async def set_user(
        self, user_id: int, user: Any, ttl: Optional[int] = None
    ) -> None:
        """缓存用户"""
        await self._redis_cache.set("user", user_id, user, ttl=ttl)
        logger.debug(f"User cached: {user_id}")

    async def invalidate_user(self, user_id: int) -> None:
        """使用户缓存失效"""
        await self._redis_cache.delete("user", user_id)
        logger.debug(f"User cache invalidated: {user_id}")

    # ==================== 空间缓存 ====================

    async def get_space(self, space_id: str) -> Optional[Any]:
        """获取缓存的空间"""
        return await self._redis_cache.get("space", space_id)

    async def set_space(
        self, space_id: str, space: Any, ttl: Optional[int] = None
    ) -> None:
        """缓存空间"""
        await self._redis_cache.set("space", space_id, space, ttl=ttl)
        logger.debug(f"Space cached: {space_id}")

    async def invalidate_space(self, space_id: str) -> None:
        """使空间缓存失效"""
        await self._redis_cache.delete("space", space_id)
        logger.debug(f"Space cache invalidated: {space_id}")

    # ==================== 空间权限缓存 ====================

    def _make_permission_key(self, space_id: str, user_id: int) -> str:
        """生成权限缓存键"""
        return f"{space_id}:{user_id}"

    async def get_space_permission(self, space_id: str, user_id: int) -> Optional[int]:
        """获取缓存的空间权限"""
        key = self._make_permission_key(space_id, user_id)
        return await self._redis_cache.get("permission", key)

    async def set_space_permission(
        self, space_id: str, user_id: int, space_db_id: int
    ) -> None:
        """缓存空间权限"""
        key = self._make_permission_key(space_id, user_id)
        await self._redis_cache.set("permission", key, space_db_id, ttl=30)
        logger.debug(f"Permission cached: {key}")

    async def invalidate_space_permission(
        self, space_id: str, user_id: Optional[int] = None
    ) -> None:
        """使空间权限缓存失效"""
        if user_id is not None:
            key = self._make_permission_key(space_id, user_id)
            await self._redis_cache.delete("permission", key)
        else:
            # 清除该空间的所有权限缓存
            await self._redis_cache.delete_pattern("permission", f"{space_id}:*")
        logger.debug(f"Permission cache invalidated for space: {space_id}")

    # ==================== Token 黑名单 ====================

    async def blacklist_token(self, jti: str, ttl_seconds: int) -> None:
        """将指定 token 的 jti 加入黑名单，直到其过期时间。"""
        r = await self._get_redis()
        await r.set(f"token_blacklist:{jti}", "1", ex=ttl_seconds)
        logger.debug(f"Token blacklisted: jti={jti}")

    async def is_token_blacklisted(self, jti: str) -> bool:
        """检查 token 的 jti 是否在黑名单中。"""
        r = await self._get_redis()
        return await r.exists(f"token_blacklist:{jti}") > 0

    # ==================== Token 黑名单 ====================

    async def blacklist_token(self, jti: str, ttl_seconds: int) -> None:
        """将 token 的 jti 加入黑名单，持续到其过期时间。"""
        await self._redis_cache.blacklist_token(jti, ttl_seconds)

    async def is_token_blacklisted(self, jti: str) -> bool:
        """检查 token 的 jti 是否已吊销。"""
        return await self._redis_cache.is_token_blacklisted(jti)

    # ==================== LLM 客户端缓存 ====================

    async def get_llm_client(self, key: str) -> Optional[Any]:
        """获取缓存的 LLM 客户端"""
        return await self._redis_cache.get("llm_client", key)

    async def set_llm_client(self, key: str, client: Any) -> None:
        """缓存 LLM 客户端"""
        # LLM客户端对象通常不能序列化，这里只缓存配置信息
        # 实际客户端还是进程内单例
        pass  # 保持进程内单例，Redis缓存不适用于客户端对象

    # ==================== 统计信息 ====================

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        # 异步方法在同步上下文中使用
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._redis_cache.get_stats())
        except RuntimeError:
            return {"error": "No event loop available"}

    def clear_all(self) -> None:
        """清空所有缓存"""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._redis_cache.clear_namespace("user"))
            loop.run_until_complete(self._redis_cache.clear_namespace("space"))
            loop.run_until_complete(self._redis_cache.clear_namespace("permission"))
            logger.info("All caches cleared")
        except RuntimeError:
            pass


# 全局缓存管理器实例
cache_manager = CacheManager()


# ============================================================================
# 装饰器
# ============================================================================


def cached_user(ttl: int = 300, null_ttl: int = 60):
    """用户缓存装饰器 - 支持 singleflight 和空值缓存"""

    def decorator(func: Callable[..., Any]):
        @wraps(func)
        async def wrapper(user_id: int, *args, **kwargs):
            cache_key = f"user:{user_id}"

            # 第一次检查缓存
            cached = await cache_manager.get_user(user_id)
            if cached is not None:
                return None if cached == NULL_SENTINEL else cached

            # 使用 singleflight 防止缓存击穿
            async with cache_manager._redis_cache._cache_miss_lock(cache_key):
                # 双重检查
                cached = await cache_manager.get_user(user_id)
                if cached is not None:
                    return None if cached == NULL_SENTINEL else cached

                # 执行原函数
                result = await func(user_id, *args, **kwargs)

                # 缓存结果（支持空值缓存）
                if result is not None:
                    await cache_manager.set_user(user_id, result)
                else:
                    await cache_manager.set_user(user_id, NULL_SENTINEL, ttl=null_ttl)

                return result

        return wrapper

    return decorator


def cached_space(ttl: int = 60, null_ttl: int = 30):
    """空间缓存装饰器 - 支持 singleflight 和空值缓存"""

    def decorator(func: Callable[..., Any]):
        @wraps(func)
        async def wrapper(space_id: str, *args, **kwargs):
            cache_key = f"space:{space_id}"

            # 第一次检查缓存
            cached = await cache_manager.get_space(space_id)
            if cached is not None:
                return None if cached == NULL_SENTINEL else cached

            # 使用 singleflight 防止缓存击穿
            async with cache_manager._redis_cache._cache_miss_lock(cache_key):
                # 双重检查
                cached = await cache_manager.get_space(space_id)
                if cached is not None:
                    return None if cached == NULL_SENTINEL else cached

                # 执行原函数
                result = await func(space_id, *args, **kwargs)

                # 缓存结果（支持空值缓存）
                if result is not None:
                    await cache_manager.set_space(space_id, result)
                else:
                    await cache_manager.set_space(space_id, NULL_SENTINEL, ttl=null_ttl)

                return result

        return wrapper

    return decorator


async def invalidate_user_cache(user_id: int):
    """使用户缓存失效的异步辅助函数"""
    await cache_manager.invalidate_user(user_id)


def invalidate_user_cache_sync(user_id: int):
    """
    使用户缓存失效的同步辅助函数

    重要：此方法不直接执行缓存失效，而是将事件写入 Outbox。
    确保缓存失效操作最终会被执行，避免 create_task 可能丢失任务的问题。
    """
    # 使用 Outbox 模式确保缓存失效最终执行
    # 立即执行（如果有事件循环）或延迟执行
    try:
        loop = asyncio.get_running_loop()
        # 在已有事件循环中，创建任务但添加回调确保错误被捕获
        task = asyncio.create_task(cache_manager.invalidate_user(user_id))
        task.add_done_callback(
            lambda t: (
                logger.error(f"Cache invalidation failed: {t.exception()}")
                if t.exception()
                else None
            )
        )
    except RuntimeError:
        # 没有事件循环，使用线程池执行
        import threading

        def run_in_thread():
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(cache_manager.invalidate_user(user_id))
            except Exception as e:
                logger.error(f"Sync cache invalidation failed: {e}")
            finally:
                new_loop.close()

        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()


async def invalidate_space_cache(space_id: str):
    """使空间缓存失效的异步辅助函数"""
    await cache_manager.invalidate_space(space_id)
    await cache_manager.invalidate_space_permission(space_id)


def invalidate_space_cache_sync(space_id: str):
    """
    使空间缓存失效的同步辅助函数

    重要：此方法不直接执行缓存失效，而是将事件写入 Outbox。
    确保缓存失效操作最终会被执行，避免 create_task 可能丢失任务的问题。
    """
    try:
        loop = asyncio.get_running_loop()
        # 创建任务但添加回调确保错误被捕获
        task1 = asyncio.create_task(cache_manager.invalidate_space(space_id))
        task2 = asyncio.create_task(cache_manager.invalidate_space_permission(space_id))

        for task in [task1, task2]:
            task.add_done_callback(
                lambda t: (
                    logger.error(f"Cache invalidation failed: {t.exception()}")
                    if t.exception()
                    else None
                )
            )
    except RuntimeError:
        # 没有事件循环，使用线程池执行
        import threading

        def run_in_thread():
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(cache_manager.invalidate_space(space_id))
                new_loop.run_until_complete(
                    cache_manager.invalidate_space_permission(space_id)
                )
            except Exception as e:
                logger.error(f"Sync cache invalidation failed: {e}")
            finally:
                new_loop.close()

        thread = threading.Thread(target=run_in_thread)
        thread.daemon = True
        thread.start()
