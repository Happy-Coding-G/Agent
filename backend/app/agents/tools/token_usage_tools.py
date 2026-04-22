"""
Token Usage Tools - 包装 TokenUsageService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class TokenUsageQueryInput(BaseModel):
    action: str = Field(description="操作类型: summary, daily, recent")
    days: int = Field(default=30, description="查询最近N天")
    feature: Optional[str] = Field(None, description="按功能类型筛选")
    limit: int = Field(default=50, description="返回记录数限制")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def token_usage_query(
        action: str,
        days: int = 30,
        feature: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        from app.services.token_usage_service import TokenUsageService
        from app.db.models import FeatureType
        from datetime import datetime, timezone, timedelta
        service = TokenUsageService(db)

        try:
            if action == "summary":
                start = datetime.now(timezone.utc) - timedelta(days=days)
                end = datetime.now(timezone.utc)
                result = await service.get_user_usage_summary(user.id, start_date=start, end_date=end)
                return {"success": True, "data": result}
            elif action == "daily":
                result = await service.get_user_daily_usage(user.id, days=days)
                return {"success": True, "data": result}
            elif action == "recent":
                if feature:
                    try:
                        ft = FeatureType(feature)
                        result = await service.get_feature_boundary_usage(user.id, feature_type=ft, limit=limit)
                    except ValueError:
                        result = []
                else:
                    result = await service.get_recent_usage(user.id, limit=limit)
                return {"success": True, "data": result}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception(f"token_usage_query failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="token_usage_query",
            func=token_usage_query,
            description="查询用户Token用量统计（汇总、每日趋势、最近明细）",
            args_schema=TokenUsageQueryInput,
            coroutine=token_usage_query,
        ),
    ]
