"""
Space Tools - 包装 SpaceService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class SpaceManageInput(BaseModel):
    action: str = Field(description="操作类型: list, create, delete, switch")
    name: Optional[str] = Field(None, description="空间名称（创建时使用）")
    space_public_id: Optional[str] = Field(None, description="目标空间public_id（删除/切换时使用）")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def space_manage(
        action: str,
        name: Optional[str] = None,
        space_public_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.space.space_service import SpaceService
        from app.core.errors import ServiceError
        service = SpaceService(db)

        try:
            if action == "list":
                spaces = await service.list_spaces(user, limit=50, offset=0)
                return {
                    "success": True,
                    "spaces": [
                        {"id": s.id, "public_id": s.public_id, "name": s.name, "owner_user_id": s.owner_user_id}
                        for s in spaces
                    ],
                }
            elif action == "create":
                if not name:
                    return {"success": False, "error": "name is required"}
                sp = await service.create_space(user, name)
                return {"success": True, "space": {"id": sp.id, "public_id": sp.public_id, "name": sp.name}}
            elif action == "delete":
                if not space_public_id:
                    return {"success": False, "error": "space_public_id is required"}
                await service.delete_space(user, space_public_id)
                return {"success": True, "message": "Space deleted"}
            elif action == "switch":
                if not space_public_id:
                    return {"success": False, "error": "space_public_id is required"}
                sp = await service.switch_space(user, space_public_id)
                return {"success": True, "space": {"id": sp.id, "public_id": sp.public_id, "name": sp.name}}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"space_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="space_manage",
            func=space_manage,
            description="管理用户空间（列出、创建、删除、切换空间）",
            args_schema=SpaceManageInput,
            coroutine=space_manage,
        ),
    ]
