"""
Data Process Tools - 包装 DataProcessAgent / 摄取流程
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class ProcessDocumentInput(BaseModel):
    source_type: str = Field(description="源类型: minio, url, text, file")
    source_path: str = Field(description="源路径或内容")
    space_id: str = Field(description="空间public_id（用于解析数据库ID）")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def process_document(source_type: str, source_path: str, space_id: str) -> Dict[str, Any]:
        from app.agents.subagents.data_process_agent import DataProcessAgent
        from app.repositories.space_repo import SpaceRepository

        try:
            space_repo = SpaceRepository(db)
            space = await space_repo.get_by_public_id(space_id)
            if not space:
                return {"success": False, "error": "Space not found"}

            agent = DataProcessAgent(db)
            result = await agent.run(
                source_type=source_type,
                source_path=source_path,
                space_id=space.id,
                user_id=user.id,
            )
            return result
        except Exception as e:
            logger.exception(f"process_document failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="process_document",
            func=process_document,
            description="处理文档并建立向量索引和知识图谱（支持minio/url/text/file）",
            args_schema=ProcessDocumentInput,
            coroutine=process_document,
        ),
    ]
