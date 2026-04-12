"""
用户级 Agent 配置服务

提供用户级 LLM 客户端创建和管理
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import UserAgentConfig, LLMProvider, Users
from app.core.config import settings
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


@dataclass
class UserAgentSettings:
    """用户 Agent 配置数据类"""
    provider: str
    model: str
    api_key: Optional[str]
    base_url: Optional[str]
    temperature: float
    max_tokens: int
    system_prompt: Optional[str]
    # 交易配置
    trade_auto_negotiate: bool
    trade_max_rounds: int
    trade_min_profit_margin: float
    trade_max_budget_ratio: float


class UserAgentService:
    """
    用户级 Agent 配置服务

    负责：
    1. 获取/创建用户 Agent 配置
    2. 创建用户级 LLM 客户端
    3. 加密/解密 API Key
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_config(
        self,
        user_id: int,
        create_default: bool = True
    ) -> Optional[UserAgentConfig]:
        """
        获取或创建用户 Agent 配置

        Args:
            user_id: 用户ID
            create_default: 如果不存在是否创建默认配置

        Returns:
            UserAgentConfig 或 None
        """
        result = await self.db.execute(
            select(UserAgentConfig)
            .where(UserAgentConfig.user_id == user_id)
            .where(UserAgentConfig.is_active == True)
        )
        config = result.scalar_one_or_none()

        if config is None and create_default:
            # 创建默认配置（使用系统设置）
            config = UserAgentConfig(
                user_id=user_id,
                provider=LLMProvider.DEEPSEEK,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.2,
                max_tokens=2048,
                is_active=True,
                is_default=True,
            )
            self.db.add(config)
            await self.db.commit()
            await self.db.refresh(config)
            logger.info(f"Created default agent config for user {user_id}")

        return config

    async def get_user_llm_client(
        self,
        user_id: int,
        temperature: Optional[float] = None,
        streaming: bool = False
    ) -> Any:
        """
        获取用户级 LLM 客户端

        Args:
            user_id: 用户ID
            temperature: 覆盖配置的温度参数
            streaming: 是否启用流式模式

        Returns:
            LangChain LLM 客户端
        """
        config = await self.get_or_create_config(user_id)

        if config is None:
            # 使用系统默认配置
            from app.services.base import get_llm_client
            return get_llm_client(temperature=temperature or 0.2)

        # 解密 API Key
        api_key = self._decrypt_api_key(config.api_key_encrypted)

        # 如果没有用户自定义 API Key，使用系统配置
        if not api_key:
            if config.provider == LLMProvider.DEEPSEEK:
                api_key = settings.DEEPSEEK_API_KEY
            elif config.provider == LLMProvider.QWEN:
                api_key = settings.QWEN_API_KEY

        # 确定 base_url
        base_url = config.base_url
        if not base_url:
            if config.provider == LLMProvider.DEEPSEEK:
                base_url = settings.DEEPSEEK_BASE_URL
            elif config.provider == LLMProvider.QWEN:
                base_url = settings.QWEN_BASE_URL

        # 创建客户端
        try:
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr

            client = ChatOpenAI(
                model=config.model,
                temperature=temperature or config.temperature,
                max_tokens=config.max_tokens,
                api_key=SecretStr(api_key) if api_key else None,
                base_url=base_url,
                streaming=streaming,
            )

            return client

        except Exception as e:
            logger.error(f"Failed to create user LLM client: {e}")
            # 回退到系统默认
            from app.services.base import get_llm_client
            return get_llm_client(temperature=temperature or 0.2)

    async def get_user_agent_settings(self, user_id: int) -> UserAgentSettings:
        """
        获取用户 Agent 完整配置

        Args:
            user_id: 用户ID

        Returns:
            UserAgentSettings
        """
        config = await self.get_or_create_config(user_id)

        if config is None:
            # 返回默认配置
            return UserAgentSettings(
                provider="deepseek",
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                temperature=0.2,
                max_tokens=2048,
                system_prompt=None,
                trade_auto_negotiate=False,
                trade_max_rounds=10,
                trade_min_profit_margin=0.1,
                trade_max_budget_ratio=0.9,
            )

        return UserAgentSettings(
            provider=config.provider.value,
            model=config.model,
            api_key=self._decrypt_api_key(config.api_key_encrypted),
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            system_prompt=config.system_prompt,
            trade_auto_negotiate=config.trade_auto_negotiate,
            trade_max_rounds=config.trade_max_rounds,
            trade_min_profit_margin=config.trade_min_profit_margin,
            trade_max_budget_ratio=config.trade_max_budget_ratio,
        )

    async def update_config(
        self,
        user_id: int,
        config_data: Dict[str, Any],
        skip_safety_check: bool = False
    ) -> UserAgentConfig:
        """
        更新用户 Agent 配置

        Args:
            user_id: 用户ID
            config_data: 配置数据字典
            skip_safety_check: 是否跳过安全审核（仅用于管理场景）

        Returns:
            更新后的 UserAgentConfig

        Raises:
            ServiceError: 如果安全审核未通过
        """
        from app.services.safety import PromptSafetyService

        config = await self.get_or_create_config(user_id)

        # 安全审核：检查 system_prompt
        if "system_prompt" in config_data and not skip_safety_check:
            system_prompt = config_data["system_prompt"]
            safety_service = PromptSafetyService(self.db)
            safety_result = await safety_service.validate_system_prompt(
                system_prompt,
                user_id=user_id
            )

            if not safety_result.passed:
                raise ServiceError(
                    400,
                    f"System prompt failed safety check: {safety_result.reason}",
                    details={
                        "risk_level": safety_result.risk_level.value,
                        "matched_patterns": safety_result.matched_patterns,
                        "suggestions": safety_result.suggestions,
                    }
                )

            # 记录安全审核日志
            if safety_result.risk_level.value not in ["safe", "low"]:
                logger.warning(
                    f"System prompt passed with risk level {safety_result.risk_level.value}: "
                    f"user={user_id}, patterns={safety_result.matched_patterns}"
                )

        # 更新允许的字段
        allowed_fields = [
            "provider", "model", "base_url", "temperature",
            "max_tokens", "system_prompt", "trade_auto_negotiate",
            "trade_max_rounds", "trade_min_profit_margin",
            "trade_max_budget_ratio", "is_active"
        ]

        for field in allowed_fields:
            if field in config_data:
                if field == "provider":
                    setattr(config, field, LLMProvider(config_data[field]))
                else:
                    setattr(config, field, config_data[field])

        # 特殊处理 API Key（需要加密）
        if "api_key" in config_data:
            config.api_key_encrypted = self._encrypt_api_key(config_data["api_key"])

        await self.db.commit()
        await self.db.refresh(config)

        logger.info(f"Updated agent config for user {user_id}")
        return config

    def _encrypt_api_key(self, api_key: Optional[str]) -> Optional[str]:
        """
        加密 API Key

        使用简单的 XOR 加密（实际生产应使用更安全的方案）
        """
        if not api_key:
            return None

        # 使用系统密钥进行 XOR 加密
        key = settings.SECRET_KEY.encode()[:32]
        encrypted = bytearray()

        for i, char in enumerate(api_key.encode()):
            encrypted.append(char ^ key[i % len(key)])

        return encrypted.hex()

    def _decrypt_api_key(self, encrypted_key: Optional[str]) -> Optional[str]:
        """
        解密 API Key
        """
        if not encrypted_key:
            return None

        try:
            key = settings.SECRET_KEY.encode()[:32]
            encrypted = bytes.fromhex(encrypted_key)
            decrypted = bytearray()

            for i, char in enumerate(encrypted):
                decrypted.append(char ^ key[i % len(key)])

            return decrypted.decode()

        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}")
            return None


# 便捷函数
async def get_user_llm_client(
    db: AsyncSession,
    user_id: int,
    temperature: Optional[float] = None
) -> Any:
    """
    便捷函数：获取用户级 LLM 客户端
    """
    service = UserAgentService(db)
    return await service.get_user_llm_client(user_id, temperature)
