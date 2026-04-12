"""
用户级 Agent 配置 API

提供用户管理自己 Agent 配置的接口：
1. 查看当前配置
2. 更新 LLM 配置（API Key、模型等）
3. 更新交易协商策略
4. 测试连接
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user, get_db
from app.db.models import Users
from app.services.user_agent_service import UserAgentService
from app.services.safety import PromptSafetyService
from app.core.errors import ServiceError

router = APIRouter(prefix="/user/agent", tags=["user-agent"])


class LLMConfigSchema(BaseModel):
    """LLM 配置模式"""
    provider: str = Field(default="deepseek", description="LLM提供商: deepseek/openai/qwen/custom")
    model: str = Field(default="deepseek-chat", description="模型名称")
    api_key: Optional[SecretStr] = Field(default=None, description="API Key（加密存储）")
    base_url: Optional[str] = Field(default=None, description="自定义Base URL")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=2048, ge=100, le=8192, description="最大Token数")
    system_prompt: Optional[str] = Field(default=None, description="自定义系统提示词")


class TradeConfigSchema(BaseModel):
    """交易协商配置模式"""
    auto_negotiate: bool = Field(default=False, description="是否启用自动协商")
    max_rounds: int = Field(default=10, ge=1, le=50, description="最大协商轮数")
    min_profit_margin: float = Field(
        default=0.1, ge=0.0, le=1.0,
        description="卖方最小利润率（0-1）"
    )
    max_budget_ratio: float = Field(
        default=0.9, ge=0.0, le=1.0,
        description="买方最大预算比例（0-1）"
    )


class UserAgentConfigResponse(BaseModel):
    """用户 Agent 配置响应"""
    provider: str
    model: str
    base_url: Optional[str]
    temperature: float
    max_tokens: int
    has_custom_api_key: bool  # 不返回真实 key，只返回是否有配置
    system_prompt: Optional[str]
    trade_auto_negotiate: bool
    trade_max_rounds: int
    trade_min_profit_margin: float
    trade_max_budget_ratio: float
    is_active: bool


class TestLLMResponse(BaseModel):
    """测试 LLM 连接响应"""
    success: bool
    provider: str
    model: str
    message: str
    latency_ms: Optional[float] = None


@router.get("/config", response_model=UserAgentConfigResponse)
async def get_user_agent_config(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的 Agent 配置

    返回用户级 LLM 配置和交易协商策略（不包含加密的 API Key）
    """
    service = UserAgentService(db)
    config = await service.get_or_create_config(current_user.id, create_default=True)

    return UserAgentConfigResponse(
        provider=config.provider.value,
        model=config.model,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        has_custom_api_key=config.api_key_encrypted is not None,
        system_prompt=config.system_prompt,
        trade_auto_negotiate=config.trade_auto_negotiate,
        trade_max_rounds=config.trade_max_rounds,
        trade_min_profit_margin=config.trade_min_profit_margin,
        trade_max_budget_ratio=config.trade_max_budget_ratio,
        is_active=config.is_active,
    )


@router.put("/config/llm", response_model=UserAgentConfigResponse)
async def update_llm_config(
    config_data: LLMConfigSchema,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    更新用户的 LLM 配置

    包括：
    - 自定义 API Key（加密存储）
    - 选择模型和提供商
    - 调整温度参数和最大 Token
    - 自定义系统提示词
    """
    service = UserAgentService(db)

    try:
        update_data = {
            "provider": config_data.provider,
            "model": config_data.model,
            "base_url": config_data.base_url,
            "temperature": config_data.temperature,
            "max_tokens": config_data.max_tokens,
            "system_prompt": config_data.system_prompt,
        }

        # 处理 API Key（如果提供了）
        if config_data.api_key:
            update_data["api_key"] = config_data.api_key.get_secret_value()

        config = await service.update_config(current_user.id, update_data)

        return UserAgentConfigResponse(
            provider=config.provider.value,
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            has_custom_api_key=config.api_key_encrypted is not None,
            system_prompt=config.system_prompt,
            trade_auto_negotiate=config.trade_auto_negotiate,
            trade_max_rounds=config.trade_max_rounds,
            trade_min_profit_margin=config.trade_min_profit_margin,
            trade_max_budget_ratio=config.trade_max_budget_ratio,
            is_active=config.is_active,
        )

    except ServiceError as e:
        # 处理业务逻辑错误（如安全审核失败）
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message": str(e),
                "details": e.details if hasattr(e, 'details') else None,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/config/trade", response_model=UserAgentConfigResponse)
async def update_trade_config(
    config_data: TradeConfigSchema,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    更新用户的交易协商策略

    包括：
    - 自动/手动协商模式
    - 利润率/预算约束
    - 最大协商轮数
    """
    service = UserAgentService(db)

    try:
        update_data = {
            "trade_auto_negotiate": config_data.auto_negotiate,
            "trade_max_rounds": config_data.max_rounds,
            "trade_min_profit_margin": config_data.min_profit_margin,
            "trade_max_budget_ratio": config_data.max_budget_ratio,
        }

        config = await service.update_config(current_user.id, update_data)

        return UserAgentConfigResponse(
            provider=config.provider.value,
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            has_custom_api_key=config.api_key_encrypted is not None,
            system_prompt=config.system_prompt,
            trade_auto_negotiate=config.trade_auto_negotiate,
            trade_max_rounds=config.trade_max_rounds,
            trade_min_profit_margin=config.trade_min_profit_margin,
            trade_max_budget_ratio=config.trade_max_budget_ratio,
            is_active=config.is_active,
        )

    except ServiceError as e:
        # 处理业务逻辑错误（如安全审核失败）
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message": str(e),
                "details": e.details if hasattr(e, 'details') else None,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test-llm", response_model=TestLLMResponse)
async def test_llm_connection(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    测试用户的 LLM 连接

    使用用户配置的 API Key 发送测试请求，验证连接是否正常
    """
    import time

    service = UserAgentService(db)

    try:
        start_time = time.time()

        # 获取用户级 LLM 客户端
        llm = await service.get_user_llm_client(current_user.id, temperature=0.2)

        # 发送测试请求
        response = await llm.ainvoke("Hello, this is a test message. Please respond with 'OK'.")

        latency_ms = (time.time() - start_time) * 1000

        # 获取配置信息
        settings = await service.get_user_agent_settings(current_user.id)

        return TestLLMResponse(
            success=True,
            provider=settings.provider,
            model=settings.model,
            message="LLM 连接测试成功",
            latency_ms=round(latency_ms, 2),
        )

    except Exception as e:
        return TestLLMResponse(
            success=False,
            provider="unknown",
            model="unknown",
            message=f"LLM 连接测试失败: {str(e)}",
            latency_ms=None,
        )


@router.delete("/config")
async def reset_agent_config(
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    重置用户 Agent 配置为系统默认值

    删除用户自定义配置，恢复使用系统默认的 LLM API
    """
    service = UserAgentService(db)

    try:
        config = await service.get_or_create_config(current_user.id, create_default=False)

        if config:
            # 标记为非活跃，使用系统默认
            config.is_active = False
            await db.commit()

        return {"success": True, "message": "已重置为系统默认配置"}

    except ServiceError as e:
        # 处理业务逻辑错误（如安全审核失败）
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "message": str(e),
                "details": e.details if hasattr(e, 'details') else None,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/safety/guidelines")
async def get_safety_guidelines(
    current_user: Users = Depends(get_current_user),
):
    """
    获取 System Prompt 安全指南

    返回安全编写 System Prompt 的最佳实践和禁止事项
    """
    service = PromptSafetyService()
    return {
        "success": True,
        "data": service.get_safety_guidelines()
    }


@router.post("/safety/validate-prompt")
async def validate_prompt_safety(
    prompt: str,
    current_user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    验证 System Prompt 安全性（预检接口）

    在实际保存前，先验证 Prompt 是否安全
    """
    service = PromptSafetyService(db)
    result = await service.validate_system_prompt(prompt, user_id=current_user.id)

    return {
        "success": True,
        "data": {
            "passed": result.passed,
            "risk_level": result.risk_level.value,
            "reason": result.reason,
            "matched_patterns": result.matched_patterns,
            "suggestions": result.suggestions,
        }
    }
