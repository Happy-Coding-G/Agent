"""
Review Tools - 包装 ReviewAgent
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class ReviewDocumentInput(BaseModel):
    doc_id: str = Field(description="要审查的文档UUID")
    review_type: str = Field(default="standard", description="审查类型: standard, strict")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db

    async def review_document(doc_id: str, review_type: str = "standard") -> Dict[str, Any]:
        from app.agents.subagents.review_agent import ReviewAgent
        agent = ReviewAgent(db)
        return await agent.run(doc_id=doc_id, review_type=review_type)

    return [
        StructuredTool.from_function(
            name="review_document",
            func=review_document,
            description="审查文档质量、合规性和完整性",
            args_schema=ReviewDocumentInput,
            coroutine=review_document,
        ),
    ]
