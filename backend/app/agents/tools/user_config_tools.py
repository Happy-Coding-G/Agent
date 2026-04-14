"""
User Config Tools - 包装 UserAgentService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class UserConfigManageInput(BaseModel):
    action: str = Field(description="操作类型: get_config, update_llm, update_trade, reset_config, test_llm")
    provider: Optional[str] = Field(None, description="LLM提供商")
    model: Optional[str] = Field(None, description="模型名称")
    base_url: Optional[str] = Field(None, description="自定义Base URL")
    temperature: Optional[float] = Field(None, description="温度参数")
    max_tokens: Optional[int] = Field(None, description="最大Token数")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    auto_negotiate: Optional[bool] = Field(None, description="是否自动协商")
    max_rounds: Optional[int] = Field(None, description="最大协商轮数")
    min_profit_margin: Optional[float] = Field(None, description="最小利润率")
    max_budget_ratio: Optional[float] = Field(None, description="最大预算比例")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def user_config_manage(
        action: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        auto_negotiate: Optional[bool] = None,
        max_rounds: Optional[int] = None,
        min_profit_margin: Optional[float] = None,
        max_budget_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        from app.services.user_agent_service import UserAgentService
        from app.core.errors import ServiceError
        service = UserAgentService(db)

        try:
            if action == "get_config":
                config = await service.get_or_create_config(user.id, create_default=True)
                return {
                    "success": True,
                    "config": {
                        "provider": config.provider.value,
                        "model": config.model,
                        "temperature": config.temperature,
                        "max_tokens": config.max_tokens,
                        "trade_auto_negotiate": config.trade_auto_negotiate,
                    },
                }
            elif action == "update_llm":
                update_data = {}
                if provider is not None:
                    update_data["provider"] = provider
                if model is not None:
                    update_data["model"] = model
                if base_url is not None:
                    update_data["base_url"] = base_url
                if temperature is not None:
                    update_data["temperature"] = temperature
                if max_tokens is not None:
                    update_data["max_tokens"] = max_tokens
                if system_prompt is not None:
                    update_data["system_prompt"] = system_prompt
                config = await service.update_config(user.id, update_data)
                return {"success": True, "config": {"provider": config.provider.value, "model": config.model}}
            elif action == "update_trade":
                update_data = {}
                if auto_negotiate is not None:
                    update_data["trade_auto_negotiate"] = auto_negotiate
                if max_rounds is not None:
                    update_data["trade_max_rounds"] = max_rounds
                if min_profit_margin is not None:
                    update_data["trade_min_profit_margin"] = min_profit_margin
                if max_budget_ratio is not None:
                    update_data["trade_max_budget_ratio"] = max_budget_ratio
                config = await service.update_config(user.id, update_data)
                return {"success": True, "config": {"trade_auto_negotiate": config.trade_auto_negotiate}}
            elif action == "reset_config":
                config = await service.get_or_create_config(user.id, create_default=False)
                if config:
                    config.is_active = False
                    await db.commit()
                return {"success": True, "message": "已重置为系统默认配置"}
            elif action == "test_llm":
                import time
                start = time.time()
                llm = await service.get_user_llm_client(user.id, temperature=0.2)
                resp = await llm.ainvoke("Hello, this is a test message. Please respond with 'OK'.")
                latency = (time.time() - start) * 1000
                settings = await service.get_user_agent_settings(user.id)
                return {
                    "success": True,
                    "provider": settings.provider,
                    "model": settings.model,
                    "latency_ms": round(latency, 2),
                    "response": resp.content if hasattr(resp, "content") else str(resp),
                }
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail}
        except Exception as e:
            logger.exception(f"user_config_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="user_config_manage",
            func=user_config_manage,
            description="管理用户级Agent配置（LLM配置、交易协商策略）",
            args_schema=UserConfigManageInput,
            coroutine=user_config_manage,
        ),
    ]
