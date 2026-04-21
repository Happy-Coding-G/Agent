"""
File Tools - 包装 query_files skill + SpaceFileService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class FileSearchInput(BaseModel):
    query: str = Field(description="自然语言查询，如'查找所有markdown文件'")


class FileManageInput(BaseModel):
    action: str = Field(description="操作类型: list_tree, create_folder, rename_folder")
    space_id: str = Field(description="空间public_id")
    folder_name: Optional[str] = Field(None, description="文件夹名称（创建/重命名时使用）")
    parent_id: Optional[int] = Field(None, description="父文件夹ID")
    folder_public_id: Optional[str] = Field(None, description="目标文件夹public_id（重命名时使用）")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user
    space_path = registry.space_path

    async def file_search(query: str) -> Dict[str, Any]:
        from app.agents.subagents.file_query_agent import query_files
        return await query_files(query=query, space_path=space_path or "/tmp/uploads")

    async def file_manage(
        action: str,
        space_id: str,
        folder_name: Optional[str] = None,
        parent_id: Optional[int] = None,
        folder_public_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.file.file_service import SpaceFileService
        service = SpaceFileService(db)

        try:
            if action == "list_tree":
                result = await service.get_space_tree(space_id, user)
                return {"success": True, "action": action, "tree": result}
            elif action == "create_folder":
                if not folder_name:
                    return {"success": False, "error": "folder_name is required"}
                result = await service.create_folder(space_id, parent_id, folder_name, user)
                return {"success": True, "action": action, "folder": {"id": result.id, "public_id": result.public_id, "name": result.name}}
            elif action == "rename_folder":
                if not folder_public_id or not folder_name:
                    return {"success": False, "error": "folder_public_id and folder_name are required"}
                result = await service.rename_folder(space_id, folder_public_id, folder_name, user)
                return {"success": True, "action": action, "result": result}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception(f"file_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="file_search",
            func=file_search,
            description="根据自然语言查询搜索空间内的文件内容",
            args_schema=FileSearchInput,
            coroutine=file_search,
        ),
        StructuredTool.from_function(
            name="file_manage",
            func=file_manage,
            description="管理空间文件和文件夹（列出目录树、创建文件夹、重命名文件夹）",
            args_schema=FileManageInput,
            coroutine=file_manage,
        ),
    ]
