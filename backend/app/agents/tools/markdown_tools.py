"""
Markdown Tools - 包装 MarkdownDocumentService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class MarkdownManageInput(BaseModel):
    action: str = Field(description="操作类型: list, get")
    space_id: str = Field(description="空间public_id")
    doc_id: Optional[str] = Field(None, description="文档ID（get时使用）")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def markdown_manage(
        action: str,
        space_id: str,
        doc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.markdown_service import MarkdownDocumentService
        from app.core.errors import ServiceError
        service = MarkdownDocumentService(db)

        try:
            if action == "list":
                docs = await service.list_documents(space_id, user)
                return {"success": True, "documents": docs}
            elif action == "get":
                if not doc_id:
                    return {"success": False, "error": "doc_id is required"}
                doc = await service.get_document(space_id, doc_id, user)
                return {"success": True, "document": doc}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"markdown_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="markdown_manage",
            func=markdown_manage,
            description="管理Markdown文档（列出、读取）",
            args_schema=MarkdownManageInput,
            coroutine=markdown_manage,
        ),
    ]
