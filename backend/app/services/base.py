"""
公共 Service 基类和工具函数
消除跨 service 的重复代码
"""

from __future__ import annotations

from typing import Optional, TypeVar, Callable, Any
from functools import wraps
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import cache_manager, NULL_SENTINEL
from app.core.config import settings
from app.core.errors import ServiceError
from app.core.circuit_breakers import llm_circuit_breaker, llm_fallback
from app.db.models import Users
from app.repositories.space_repo import SpaceRepository
import logging

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SpaceAwareService:
    """
    需要空间权限检查的 Service 基类
    提供统一的 _require_space 方法，支持缓存
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._spaces: Optional[SpaceRepository] = None

    @property
    def spaces(self) -> SpaceRepository:
        """懒加载 SpaceRepository"""
        if self._spaces is None:
            self._spaces = SpaceRepository(self.db)
        return self._spaces

    async def _require_space(self, space_public_id: str, user: Users) -> int:
        """检查空间权限，带缓存击穿防护"""
        cache_key = f"permission:{space_public_id}:{user.id}"

        # 尝试从缓存获取
        cached_space_id = await cache_manager.get_space_permission(
            space_public_id, user.id
        )
        if cached_space_id is not None:
            if cached_space_id == NULL_SENTINEL:
                raise ServiceError(404, "Space not found or permission denied")
            return cached_space_id

        # 获取 per-key 锁
        async with cache_manager._redis_cache._cache_miss_lock(cache_key):
            # 双重检查
            cached_space_id = await cache_manager.get_space_permission(
                space_public_id, user.id
            )
            if cached_space_id is not None:
                if cached_space_id == NULL_SENTINEL:
                    raise ServiceError(404, "Space not found or permission denied")
                return cached_space_id

            # 查询数据库
            space = await self.spaces.get_by_public_id_for_owner(space_public_id, user.id)
            if not space:
                # 缓存空值防止穿透
                await cache_manager.set_space_permission(
                    space_public_id, user.id, NULL_SENTINEL, ttl=30
                )
                raise ServiceError(404, "Space not found or permission denied")

            # 缓存结果
            await cache_manager.set_space_permission(space_public_id, user.id, space.id)
            return space.id


def extract_title_from_text(text: str, max_length: int = 255) -> Optional[str]:
    """
    从文本中提取标题
    优先查找 Markdown 标题，否则取第一行非空行

    Args:
        text: 输入文本
        max_length: 标题最大长度

    Returns:
        提取的标题或 None
    """
    if not text:
        return None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            return title[:max_length] if title else None
        return line[:max_length]

    return None


def get_llm_client(temperature: float = 0.2):
    """
    获取 LangChain LLM 客户端
    统一配置 DeepSeek API

    Args:
        temperature: 温度参数

    Returns:
        ChatOpenAI 实例

    Raises:
        ServiceError: 如果 langchain_openai 未安装
    """
    try:
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr
    except Exception as exc:
        raise ServiceError(500, "langchain_openai is required") from exc

    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        temperature=temperature,
        api_key=SecretStr(settings.DEEPSEEK_API_KEY)
        if settings.DEEPSEEK_API_KEY
        else None,
        base_url=settings.DEEPSEEK_BASE_URL,
    )


def preview_text(text: Optional[str], max_length: int = 240) -> str:
    """
    生成文本预览
    去除多余空白并截断

    Args:
        text: 输入文本
        max_length: 最大长度

    Returns:
        预览文本
    """
    if not text:
        return ""
    compact = " ".join(text.split())
    return compact[:max_length]


# ============================================================================
# 带熔断保护的 LLM 调用
# ============================================================================

async def call_llm_with_circuit_breaker(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    **kwargs
) -> str:
    """
    带熔断保护的 LLM 调用

    当 LLM 服务不可用时，会触发熔断并返回友好的错误提示

    Args:
        prompt: 输入提示
        temperature: 温度参数
        max_tokens: 最大token数
        **kwargs: 其他参数

    Returns:
        LLM 响应文本

    Raises:
        ServiceError: 服务熔断或调用失败时抛出
    """
    client = get_llm_client(temperature=temperature)

    try:
        response = await client.ainvoke(
            prompt,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.content
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise ServiceError(503, f"AI服务调用失败: {str(e)}")


# 应用熔断器装饰器
call_llm_with_circuit_breaker = llm_circuit_breaker(fallback=llm_fallback)(
    call_llm_with_circuit_breaker
)


def llm_with_circuit_breaker(func: Callable[..., T]) -> Callable[..., T]:
    """
    装饰器：为函数提供LLM熔断保护

    使用示例:
        @llm_with_circuit_breaker
        async def generate_summary(text: str) -> str:
            client = get_llm_client()
            return await client.ainvoke(f"总结: {text}")
    """
    return llm_circuit_breaker(fallback=llm_fallback)(func)
