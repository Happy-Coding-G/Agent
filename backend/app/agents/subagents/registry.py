"""Registry of agent-callable subagents backed by SKILL.md documents.

Subagent schema 从 SKILL.md 文档中读取，执行通过通用 executor dispatcher。
这样可以避免 MainAgent 在规划阶段就拉起全部工作流对象。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills.executor import execute_skill_md
from app.agents.skills.parser import SkillMDParser
from app.db.models import Users


class QAResearchInput(BaseModel):
    query: str = Field(description="研究或问答请求")
    space_id: str = Field(description="空间public_id")
    top_k: int = Field(default=5, ge=1, le=20, description="检索条数")


class ReviewWorkflowInput(BaseModel):
    doc_id: str = Field(description="文档ID")
    review_type: str = Field(default="standard", description="审查类型")


class AssetOrganizeWorkflowInput(BaseModel):
    asset_ids: List[str] = Field(description="资产ID列表")


class TradeWorkflowInput(BaseModel):
    action: str = Field(description="交易动作")
    space_id: str = Field(description="空间public_id")
    payload: Dict[str, Any] = Field(default_factory=dict, description="额外参数")


class DynamicWorkflowInput(BaseModel):
    task_name: str = Field(description="动态 subagent 名称")
    goal: str = Field(description="复杂任务目标")
    deliverable: Optional[str] = Field(default=None, description="预期交付物")
    context: Dict[str, Any] = Field(default_factory=dict, description="附加上下文")
    suggested_steps: Optional[List[str]] = Field(default=None, description="建议步骤")


class SubAgentRegistry:
    def __init__(
        self,
        db: AsyncSession,
        user: Users,
        llm_client=None,
        space_path: str | None = None,
        parser: SkillMDParser | None = None,
    ):
        self.db = db
        self.user = user
        self.llm_client = llm_client
        self.space_path = space_path
        self._parser = parser or SkillMDParser()

    def get_subagent_schemas(self) -> List[Dict[str, Any]]:
        return self._parser.get_schemas(capability_type="subagent")

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(arguments)

        if name == "qa_research":
            if "user" not in enriched:
                enriched["user"] = self.user
            if "space_id" in enriched and "space_public_id" not in enriched:
                enriched["space_public_id"] = enriched.pop("space_id")
            return await execute_skill_md(name, enriched, self.db, self._parser)

        if name == "trade_workflow":
            if "user" not in enriched:
                enriched["user"] = self.user
            if "space_id" in enriched and "space_public_id" not in enriched:
                enriched["space_public_id"] = enriched.pop("space_id")
            payload = enriched.pop("payload", {})
            return await execute_skill_md(name, {**enriched, **payload}, self.db, self._parser)

        return await execute_skill_md(name, enriched, self.db, self._parser)
