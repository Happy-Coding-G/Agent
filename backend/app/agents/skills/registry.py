"""Agent-layer skill registry.

Skill schema 从 SKILL.md 文档中读取，skill 执行通过通用 executor dispatcher。
这样可以避免在规划阶段就触发重型依赖链，同时让工作流定义可文档化、可维护。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills.parser import SkillMDParser


async def execute_skill_md(name: str, arguments: Dict[str, Any], db: AsyncSession, parser: SkillMDParser) -> Dict[str, Any]:
    """Skill 执行占位（ReAct 架构中 skill 已通过工具注册表直接调用）。"""
    return {
        "skill": name,
        "success": False,
        "result": None,
        "error": f"Skill '{name}' execution via SkillRegistry is deprecated. Use AgentToolRegistry instead.",
    }


class MarketOverviewInput(BaseModel):
    pass


class MarketTrendInput(BaseModel):
    data_type: Optional[str] = Field(default=None, description="数据类型")
    days: int = Field(default=30, ge=1, le=365, description="统计天数")


class PrivacyProtocolInput(BaseModel):
    asset_id: str = Field(description="资产ID")
    sensitivity: str = Field(description="敏感度级别: low/medium/high/critical")
    requirements: Optional[Dict[str, Any]] = Field(default=None, description="隐私计算要求")


class AuditReportInput(BaseModel):
    transaction_id: str = Field(description="交易ID")
    days: int = Field(default=30, ge=1, le=365, description="报告时间窗口")


class SkillRegistry:
    """Registry of agent-callable skills backed by SKILL.md documents."""

    def __init__(self, db: AsyncSession, parser: SkillMDParser | None = None):
        self.db = db
        self._parser = parser or SkillMDParser()

    def get_skill_schemas(self, level: str = "l2") -> List[Dict[str, Any]]:
        return self._parser.get_schemas(capability_type="skill", level=level)

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_skill_md(name, arguments, self.db, self._parser)
