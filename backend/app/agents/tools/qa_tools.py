"""
QA Tools - 包装 QAAgent
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class QAAnswerInput(BaseModel):
    query: str = Field(description="用户问题")
    space_id: str = Field(description="空间public_id")
    top_k: int = Field(default=5, description="检索结果数量")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        default=None, description="多轮对话历史"
    )


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def qa_answer(
        query: str,
        space_id: str,
        top_k: int = 5,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        from app.agents.subagents.qa_agent import QAAgent
        agent = QAAgent(db)
        return await agent.run(
            query=query,
            space_public_id=space_id,
            user=user,
            top_k=top_k,
            conversation_history=conversation_history,
        )

    return [
        StructuredTool.from_function(
            name="qa_answer",
            func=qa_answer,
            description="基于知识库回答用户问题（RAG检索+知识图谱）",
            args_schema=QAAnswerInput,
            coroutine=qa_answer,
        ),
    ]
