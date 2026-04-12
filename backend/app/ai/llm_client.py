"""
LLM Client with Token Usage Tracking

提供带Token用量追踪的LLM客户端封装
自动记录每次调用的Token消耗和功能边界
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Dict, Any, Callable, AsyncGenerator, Union
from functools import wraps

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import LLMProvider, FeatureType
from app.services.token_usage_service import record_token_usage

logger = logging.getLogger(__name__)


class TrackedLLMClient:
    """
    带Token用量追踪的LLM客户端

    自动记录：
    - Token消耗
    - 功能边界
    - 成本计算
    - 延迟统计
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        user_id: Optional[int] = None,
        feature_type: FeatureType = FeatureType.OTHER,
        feature_detail: Optional[str] = None,
        provider: LLMProvider = LLMProvider.DEEPSEEK,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        is_custom_api: bool = False,
    ):
        self.db = db
        self.user_id = user_id
        self.feature_type = feature_type
        self.feature_detail = feature_detail
        self.provider = provider
        self.model = model
        self.is_custom_api = is_custom_api
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 创建底层LLM客户端
        self._client = self._create_client(api_key, base_url)

    def _create_client(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ChatOpenAI:
        """创建LangChain LLM客户端"""
        # 确定API配置
        if self.provider == LLMProvider.DEEPSEEK:
            key = api_key or settings.DEEPSEEK_API_KEY
            url = base_url or settings.DEEPSEEK_BASE_URL
            model = self.model or "deepseek-chat"
        elif self.provider == LLMProvider.OPENAI:
            key = api_key or settings.OPENAI_API_KEY
            url = base_url or settings.OPENAI_BASE_URL
            model = self.model or "gpt-3.5-turbo"
        elif self.provider == LLMProvider.QWEN:
            key = api_key or settings.QWEN_API_KEY
            url = base_url or settings.QWEN_BASE_URL
            model = self.model or "qwen-turbo"
        else:
            # 自定义提供商
            key = api_key
            url = base_url
            model = self.model or "custom"

        return ChatOpenAI(
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            api_key=SecretStr(key) if key else None,
            base_url=url,
        )

    async def invoke(
        self,
        prompt: Union[str, list],
        **kwargs
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        调用LLM并追踪用量

        Returns:
            (response_text, usage_info)
        """
        if not self.db or not self.user_id:
            # 无追踪模式
            response = await self._client.ainvoke(prompt, **kwargs)
            return response.content, None

        start_time = time.time()
        request_id = f"req_{int(start_time * 1000)}"

        try:
            # 调用LLM
            response = await self._client.ainvoke(prompt, **kwargs)
            latency_ms = int((time.time() - start_time) * 1000)

            # 提取用量信息
            usage = self._extract_usage(response)

            # 记录用量
            await self._record_usage(
                request_id=request_id,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                status="success",
            )

            usage_info = {
                "request_id": request_id,
                "latency_ms": latency_ms,
                **usage,
            }

            return response.content, usage_info

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"LLM call failed: {e}")

            # 记录失败
            await self._record_usage(
                request_id=request_id,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_message=str(e)[:500],
            )

            raise

    async def stream(
        self,
        prompt: Union[str, list],
        **kwargs
    ) -> AsyncGenerator[tuple[str, Optional[Dict[str, Any]]], None]:
        """
        流式调用LLM并追踪用量

        Yields:
            (token_chunk, usage_info) 最后一次yield包含完整usage_info
        """
        if not self.db or not self.user_id:
            # 无追踪模式
            async for chunk in self._client.astream(prompt, **kwargs):
                yield chunk.content, None
            return

        start_time = time.time()
        request_id = f"stream_{int(start_time * 1000)}"

        full_response = []
        prompt_tokens = 0
        completion_tokens = 0

        try:
            async for chunk in self._client.astream(prompt, **kwargs):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                full_response.append(content)
                completion_tokens += 1  # 流式粗略估计

                # 每次yield进度信息
                yield content, {
                    "request_id": request_id,
                    "streaming": True,
                    "tokens_so_far": completion_tokens,
                }

            # 流结束，记录用量
            latency_ms = int((time.time() - start_time) * 1000)

            # 估算prompt tokens
            if isinstance(prompt, str):
                prompt_tokens = len(prompt) // 4  # 粗略估算
            else:
                prompt_tokens = sum(len(str(p)) for p in prompt) // 4

            await self._record_usage(
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                status="success",
                metadata={"streaming": True, "estimated": True},
            )

            # 最终yield包含完整信息
            yield "", {
                "request_id": request_id,
                "streaming": False,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "latency_ms": latency_ms,
                "estimated": True,
            }

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"LLM stream failed: {e}")

            await self._record_usage(
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                status="error",
                error_message=str(e)[:500],
                metadata={"streaming": True},
            )

            raise

    def _extract_usage(self, response: BaseMessage) -> Dict[str, int]:
        """从响应中提取用量信息"""
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # LangChain通常会在response_metadata中包含用量
        if hasattr(response, 'response_metadata') and response.response_metadata:
            metadata = response.response_metadata
            if 'token_usage' in metadata:
                token_usage = metadata['token_usage']
                usage['prompt_tokens'] = token_usage.get('prompt_tokens', 0)
                usage['completion_tokens'] = token_usage.get('completion_tokens', 0)
                usage['total_tokens'] = token_usage.get('total_tokens', 0)
            elif 'usage' in metadata:
                token_usage = metadata['usage']
                usage['prompt_tokens'] = token_usage.get('prompt_tokens', 0)
                usage['completion_tokens'] = token_usage.get('completion_tokens', 0)
                usage['total_tokens'] = token_usage.get('total_tokens', 0)

        return usage

    async def _record_usage(
        self,
        request_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        status: str,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """记录Token用量"""
        if not self.db or not self.user_id:
            return

        try:
            await record_token_usage(
                db=self.db,
                user_id=self.user_id,
                provider=self.provider.value,
                model=self.model,
                feature_type=self.feature_type.value,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                is_custom_api=self.is_custom_api,
                feature_detail=self.feature_detail,
                request_id=request_id,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
                metadata=metadata or {},
            )
        except Exception as e:
            logger.error(f"Failed to record token usage: {e}")
            # 记录失败不应影响主流程


# 便捷函数
def create_tracked_client(
    db: AsyncSession,
    user_id: int,
    feature_type: FeatureType,
    provider: LLMProvider = LLMProvider.DEEPSEEK,
    model: Optional[str] = None,
    **kwargs
) -> TrackedLLMClient:
    """
    创建带追踪的LLM客户端

    Args:
        db: 数据库会话
        user_id: 用户ID
        feature_type: 功能类型
        provider: LLM提供商
        model: 模型名称
        **kwargs: 其他参数

    Returns:
        TrackedLLMClient实例
    """
    return TrackedLLMClient(
        db=db,
        user_id=user_id,
        feature_type=feature_type,
        provider=provider,
        model=model or "deepseek-chat",
        **kwargs
    )


def with_token_tracking(
    feature_type: FeatureType,
    feature_detail: Optional[str] = None,
):
    """
    装饰器：为函数自动添加Token用量追踪

    使用示例:
        @with_token_tracking(FeatureType.CHAT, "RAG对话")
        async def chat_with_user(
            db: AsyncSession,
            user_id: int,
            message: str,
        ) -> str:
            client = create_tracked_client(db, user_id, FeatureType.CHAT)
            response, _ = await client.invoke(message)
            return response
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 尝试从参数中提取db和user_id
            db = kwargs.get('db') or kwargs.get('session')
            user_id = kwargs.get('user_id') or kwargs.get('current_user', {}).get('id')

            if db and user_id:
                # 注入追踪客户端
                tracked_client = create_tracked_client(
                    db=db,
                    user_id=user_id,
                    feature_type=feature_type,
                    feature_detail=feature_detail,
                )
                kwargs['_tracked_llm_client'] = tracked_client

            return await func(*args, **kwargs)
        return wrapper
    return decorator
