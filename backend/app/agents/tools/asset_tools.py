"""
Asset Tools - 包装 AssetService + AssetOrganizeAgent
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class AssetManageInput(BaseModel):
    action: str = Field(description="操作类型: list, get, generate")
    space_id: str = Field(description="空间public_id")
    asset_id: Optional[str] = Field(None, description="资产ID（get时使用）")
    prompt: Optional[str] = Field(None, description="生成提示（generate时使用）")
    source_asset_ids: Optional[List[str]] = Field(None, description="来源资产ID列表（generate时使用）")


class AssetOrganizeInput(BaseModel):
    asset_ids: List[str] = Field(description="要整理的资产ID列表")
    space_id: str = Field(description="空间public_id")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def asset_manage(
        action: str,
        space_id: str,
        asset_id: Optional[str] = None,
        prompt: Optional[str] = None,
        source_asset_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        from app.services.asset_service import AssetService
        from app.core.errors import ServiceError
        service = AssetService(db)

        try:
            if action == "list":
                assets = await service.list_assets(space_id, user)
                return {"success": True, "assets": assets}
            elif action == "get":
                if not asset_id:
                    return {"success": False, "error": "asset_id is required"}
                asset = await service.get_asset(space_id, asset_id, user)
                return {"success": True, "asset": asset}
            elif action == "generate":
                record = await service.generate_asset(
                    space_public_id=space_id,
                    prompt=prompt,
                    user=user,
                    source_asset_ids=source_asset_ids,
                )
                return {"success": True, "asset": record}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"asset_manage failed: {e}")
            return {"success": False, "error": str(e)}

    async def asset_organize(asset_ids: List[str], space_id: str) -> Dict[str, Any]:
        from app.agents.subagents.asset_organize_agent import AssetOrganizeAgent
        agent = AssetOrganizeAgent(db)
        return await agent.run(asset_ids=asset_ids, space_id=space_id, user=user)

    return [
        StructuredTool.from_function(
            name="asset_manage",
            func=asset_manage,
            description="管理数字资产（列出、获取、生成资产）",
            args_schema=AssetManageInput,
            coroutine=asset_manage,
        ),
        StructuredTool.from_function(
            name="asset_organize",
            func=asset_organize,
            description="整理和聚类资产",
            args_schema=AssetOrganizeInput,
            coroutine=asset_organize,
        ),
    ]
