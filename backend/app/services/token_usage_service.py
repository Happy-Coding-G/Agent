"""
Token Usage Service - Token用量统计服务

提供功能：
1. 记录Token使用情况
2. 查询用量统计
3. 成本计算
4. 功能边界标识
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any, Tuple
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.dialects.postgresql import insert

from app.db.models import TokenUsage, ModelPrice, FeatureType, LLMProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


# 默认模型定价 (每1K tokens的美元价格)
DEFAULT_MODEL_PRICES: Dict[str, Dict[str, float]] = {
    "deepseek-chat": {"prompt": 0.00014, "completion": 0.00028},
    "deepseek-coder": {"prompt": 0.00014, "completion": 0.00028},
    "gpt-4": {"prompt": 0.03, "completion": 0.06},
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
    "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
    "qwen-turbo": {"prompt": 0.0005, "completion": 0.001},
    "qwen-plus": {"prompt": 0.001, "completion": 0.002},
    "qwen-max": {"prompt": 0.003, "completion": 0.006},
}


class TokenUsageService:
    """Token用量统计服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_usage(
        self,
        user_id: int,
        provider: LLMProvider,
        model: str,
        feature_type: FeatureType,
        prompt_tokens: int,
        completion_tokens: int,
        is_custom_api: bool = False,
        feature_detail: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        latency_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TokenUsage:
        """
        记录一次Token使用情况

        Args:
            user_id: 用户ID
            provider: LLM提供商
            model: 模型名称
            feature_type: 功能类型
            prompt_tokens: 输入token数
            completion_tokens: 输出token数
            is_custom_api: 是否使用用户自己的API
            feature_detail: 详细功能描述
            request_id: 请求ID
            session_id: 会话ID
            latency_ms: 请求延迟(毫秒)
            status: 请求状态
            error_message: 错误信息
            metadata: 额外元数据

        Returns:
            创建的TokenUsage记录
        """
        # 计算成本
        prompt_cost, completion_cost, total_cost = await self._calculate_cost(
            provider, model, prompt_tokens, completion_tokens
        )

        usage = TokenUsage(
            user_id=user_id,
            provider=provider,
            model=model,
            is_custom_api=is_custom_api,
            feature_type=feature_type,
            feature_detail=feature_detail,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_cost=prompt_cost,
            completion_cost=completion_cost,
            total_cost=total_cost,
            request_id=request_id,
            session_id=session_id,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            metadata=metadata or {},
        )

        self.db.add(usage)
        await self.db.commit()
        await self.db.refresh(usage)

        logger.debug(
            f"Token usage recorded: user={user_id}, feature={feature_type.value}, "
            f"tokens={usage.total_tokens}, cost=${total_cost:.6f}"
        )

        return usage

    async def _calculate_cost(
        self,
        provider: LLMProvider,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Tuple[float, float, float]:
        """
        计算Token成本

        Returns:
            (prompt_cost, completion_cost, total_cost)
        """
        # 先从数据库查询定价
        result = await self.db.execute(
            select(ModelPrice).where(
                and_(
                    ModelPrice.provider == provider,
                    ModelPrice.model == model,
                    ModelPrice.is_active == True,
                )
            )
        )
        price = result.scalar_one_or_none()

        if price:
            return price.calculate_cost(prompt_tokens, completion_tokens)

        # 使用默认定价
        if model in DEFAULT_MODEL_PRICES:
            p = DEFAULT_MODEL_PRICES[model]
            prompt_cost = (prompt_tokens / 1000) * p["prompt"]
            completion_cost = (completion_tokens / 1000) * p["completion"]
            return prompt_cost, completion_cost, prompt_cost + completion_cost

        # 未知模型，返回0成本
        logger.warning(f"Unknown model for cost calculation: {model}")
        return 0.0, 0.0, 0.0

    async def get_user_usage_summary(
        self,
        user_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        获取用户用量汇总

        Args:
            user_id: 用户ID
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            用量汇总统计
        """
        start_date = start_date or datetime.now(timezone.utc) - timedelta(days=30)
        end_date = end_date or datetime.now(timezone.utc)

        # 基础统计
        result = await self.db.execute(
            select(
                func.count(TokenUsage.id).label("total_requests"),
                func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
                func.sum(TokenUsage.completion_tokens).label("total_completion_tokens"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.sum(TokenUsage.total_cost).label("total_cost"),
                func.avg(TokenUsage.latency_ms).label("avg_latency_ms"),
            ).where(
                and_(
                    TokenUsage.user_id == user_id,
                    TokenUsage.created_at >= start_date,
                    TokenUsage.created_at <= end_date,
                )
            )
        )
        row = result.one()

        # 按功能分类统计
        feature_stats = await self.db.execute(
            select(
                TokenUsage.feature_type,
                func.count(TokenUsage.id).label("requests"),
                func.sum(TokenUsage.total_tokens).label("tokens"),
                func.sum(TokenUsage.total_cost).label("cost"),
            ).where(
                and_(
                    TokenUsage.user_id == user_id,
                    TokenUsage.created_at >= start_date,
                    TokenUsage.created_at <= end_date,
                )
            ).group_by(TokenUsage.feature_type)
        )

        # 按模型分类统计
        model_stats = await self.db.execute(
            select(
                TokenUsage.model,
                func.count(TokenUsage.id).label("requests"),
                func.sum(TokenUsage.total_tokens).label("tokens"),
                func.sum(TokenUsage.total_cost).label("cost"),
            ).where(
                and_(
                    TokenUsage.user_id == user_id,
                    TokenUsage.created_at >= start_date,
                    TokenUsage.created_at <= end_date,
                )
            ).group_by(TokenUsage.model)
        )

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "summary": {
                "total_requests": row.total_requests or 0,
                "total_prompt_tokens": row.total_prompt_tokens or 0,
                "total_completion_tokens": row.total_completion_tokens or 0,
                "total_tokens": row.total_tokens or 0,
                "total_cost": round(row.total_cost or 0, 6),
                "avg_latency_ms": round(row.avg_latency_ms or 0, 2),
            },
            "by_feature": [
                {
                    "feature_type": f[0].value if f[0] else "unknown",
                    "requests": f[1],
                    "tokens": f[2] or 0,
                    "cost": round(f[3] or 0, 6),
                }
                for f in feature_stats.all()
            ],
            "by_model": [
                {
                    "model": m[0],
                    "requests": m[1],
                    "tokens": m[2] or 0,
                    "cost": round(m[3] or 0, 6),
                }
                for m in model_stats.all()
            ],
        }

    async def get_user_daily_usage(
        self,
        user_id: int,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        获取用户每日用量

        Args:
            user_id: 用户ID
            days: 查询天数

        Returns:
            每日用量列表
        """
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                func.date(TokenUsage.created_at).label("date"),
                func.count(TokenUsage.id).label("requests"),
                func.sum(TokenUsage.total_tokens).label("tokens"),
                func.sum(TokenUsage.total_cost).label("cost"),
            ).where(
                and_(
                    TokenUsage.user_id == user_id,
                    TokenUsage.created_at >= start_date,
                )
            ).group_by(
                func.date(TokenUsage.created_at)
            ).order_by(
                func.date(TokenUsage.created_at)
            )
        )

        return [
            {
                "date": row.date.isoformat() if row.date else None,
                "requests": row.requests,
                "tokens": row.tokens or 0,
                "cost": round(row.cost or 0, 6),
            }
            for row in result.all()
        ]

    async def get_feature_boundary_usage(
        self,
        user_id: int,
        feature_type: FeatureType,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        获取特定功能的详细使用记录

        Args:
            user_id: 用户ID
            feature_type: 功能类型
            limit: 返回记录数

        Returns:
            使用记录列表
        """
        result = await self.db.execute(
            select(TokenUsage).where(
                and_(
                    TokenUsage.user_id == user_id,
                    TokenUsage.feature_type == feature_type,
                )
            ).order_by(
                desc(TokenUsage.created_at)
            ).limit(limit)
        )

        return [usage.to_dict() for usage in result.scalars().all()]

    async def get_recent_usage(
        self,
        user_id: int,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        获取用户最近的Token使用记录

        Args:
            user_id: 用户ID
            limit: 返回记录数

        Returns:
            使用记录列表
        """
        result = await self.db.execute(
            select(TokenUsage).where(
                TokenUsage.user_id == user_id
            ).order_by(
                desc(TokenUsage.created_at)
            ).limit(limit)
        )

        return [usage.to_dict() for usage in result.scalars().all()]

    async def initialize_model_prices(self):
        """初始化模型定价数据"""
        for model, prices in DEFAULT_MODEL_PRICES.items():
            # 确定提供商
            if model.startswith("deepseek"):
                provider = LLMProvider.DEEPSEEK
            elif model.startswith("gpt"):
                provider = LLMProvider.OPENAI
            elif model.startswith("qwen"):
                provider = LLMProvider.QWEN
            else:
                provider = LLMProvider.CUSTOM

            # 检查是否已存在
            result = await self.db.execute(
                select(ModelPrice).where(
                    and_(
                        ModelPrice.provider == provider,
                        ModelPrice.model == model,
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # 更新定价
                existing.prompt_price_per_1k = prices["prompt"]
                existing.completion_price_per_1k = prices["completion"]
                existing.is_active = True
            else:
                # 创建新定价
                price = ModelPrice(
                    provider=provider,
                    model=model,
                    prompt_price_per_1k=prices["prompt"],
                    completion_price_per_1k=prices["completion"],
                )
                self.db.add(price)

        await self.db.commit()
        logger.info("Model prices initialized")


# 便捷函数
async def record_token_usage(
    db: AsyncSession,
    user_id: int,
    provider: str,
    model: str,
    feature_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    **kwargs,
) -> TokenUsage:
    """
    便捷函数：记录Token使用

    用于在LLM客户端中快速记录用量
    """
    service = TokenUsageService(db)

    # 转换枚举
    try:
        provider_enum = LLMProvider(provider)
    except ValueError:
        provider_enum = LLMProvider.CUSTOM

    try:
        feature_enum = FeatureType(feature_type)
    except ValueError:
        feature_enum = FeatureType.OTHER

    return await service.record_usage(
        user_id=user_id,
        provider=provider_enum,
        model=model,
        feature_type=feature_enum,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        **kwargs,
    )
