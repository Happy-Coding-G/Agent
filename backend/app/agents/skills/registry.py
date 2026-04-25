"""Agent-layer skill registry.

Skill schema 从 SKILL.md 文档中读取，skill 执行通过通用 executor dispatcher 调用
backend/app/services/skills/ 中的 Python 实现类。

三层职责边界：
- tool:   原子操作，单步完成，无内部决策（如 file_search, vector_search）
- skill:  有状态分析/计算，多步内部逻辑但不需要 LLM 自主决策（如 market_overview, audit_report）
- subagent: 需要 LLM 自主决策的复杂工作流，有独立 ReAct 循环（如 qa_research, trade_workflow）
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.skills.parser import SkillMDParser

logger = logging.getLogger(__name__)


# ---- Pydantic input models (fallback validation) ---------------------------

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


# ---- Executor dispatcher ---------------------------------------------------

# Map skill_id -> Pydantic input model for strict validation
_SKILL_INPUT_MODELS: Dict[str, type[BaseModel]] = {
    "market_overview": MarketOverviewInput,
    "market_trend": MarketTrendInput,
    "audit_report": AuditReportInput,
    "privacy_protocol": PrivacyProtocolInput,
}


def _resolve_executor(executor_path: str):
    """解析 executor 路径并返回 (cls, method_name, requires_await)。

    executor_path 格式: module.path:ClassName.method_name
    示例: app.services.skills.market_analysis_skill:MarketAnalysisSkill.get_market_overview
    """
    if ":" not in executor_path:
        raise ValueError(f"Invalid executor path (missing ':'): {executor_path}")

    module_path, class_method = executor_path.split(":", 1)
    if "." not in class_method:
        raise ValueError(f"Invalid executor path (missing '.' in class.method): {executor_path}")

    class_name, method_name = class_method.rsplit(".", 1)

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    method = getattr(cls, method_name)

    # 检查是否为 async 方法 (CO_COROUTINE = 0x80)
    requires_await = bool(callable(method) and hasattr(method, "__code__") and method.__code__.co_flags & 0x80)

    return cls, method_name, requires_await


async def execute_skill_md(
    name: str,
    arguments: Dict[str, Any],
    db: AsyncSession,
    parser: SkillMDParser,
) -> Dict[str, Any]:
    """通过 SKILL.md 中的 executor 字段执行 skill。

    执行流程：
    1. 从 parser 获取 skill 文档
    2. 解析 executor 路径（module:Class.method）
    3. 动态导入并实例化类（注入 db）
    4. 用 Pydantic 模型校验参数（如果注册了）
    5. 调用方法并返回结构化结果
    """
    # 1. 获取 skill 文档
    doc = parser.get_document(name)
    if not doc:
        logger.warning(f"Skill '{name}' not found in parser documents")
        return {
            "skill": name,
            "success": False,
            "result": None,
            "error": f"Skill '{name}' not found.",
        }

    executor_path = doc.executor
    if not executor_path:
        logger.warning(f"Skill '{name}' has no executor defined in frontmatter")
        return {
            "skill": name,
            "success": False,
            "result": None,
            "error": f"Skill '{name}' has no executor configured.",
        }

    # 2. 解析 executor
    try:
        cls, method_name, requires_await = _resolve_executor(executor_path)
    except Exception as e:
        logger.exception(f"Failed to resolve executor for skill '{name}': {executor_path}")
        return {
            "skill": name,
            "success": False,
            "result": None,
            "error": f"Failed to resolve executor: {e}",
        }

    # 3. Pydantic 参数校验（可选）
    input_model = _SKILL_INPUT_MODELS.get(name)
    if input_model:
        try:
            validated = input_model(**arguments)
            arguments = validated.model_dump()
        except Exception as e:
            logger.warning(f"Skill '{name}' input validation failed: {e}")
            return {
                "skill": name,
                "success": False,
                "result": None,
                "error": f"Input validation failed: {e}",
            }

    # 4. 实例化并调用
    try:
        instance = cls(db)
        bound_method = getattr(instance, method_name)

        if requires_await:
            result = await bound_method(**arguments)
        else:
            result = bound_method(**arguments)

        return {
            "skill": name,
            "success": True,
            "result": result,
            "error": None,
        }

    except Exception as e:
        logger.exception(f"Skill '{name}' execution failed: {e}")
        return {
            "skill": name,
            "success": False,
            "result": None,
            "error": str(e),
        }


class SkillRegistry:
    """Registry of agent-callable skills backed by SKILL.md documents."""

    def __init__(self, db: AsyncSession, parser: SkillMDParser | None = None):
        self.db = db
        self._parser = parser or SkillMDParser()

    def get_skill_schemas(self, level: str = "l2") -> List[Dict[str, Any]]:
        return self._parser.get_schemas(capability_type="skill", level=level)

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_skill_md(name, arguments, self.db, self._parser)
