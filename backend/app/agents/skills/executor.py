"""Generic executor dispatcher for SKILL.md workflows.

Resolves executor paths like `module.path:ClassName.method_name`
and invokes them with keyword arguments.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def resolve_executor(executor_path: Optional[str]) -> Any:
    """Resolve an executor path to a callable.

    Supports formats:
    - module.path:function_name
    - module.path:ClassName.method_name
    """
    if not executor_path:
        return None

    if ":" not in executor_path:
        raise ValueError(f"Invalid executor path: {executor_path}. Expected 'module.path:callable_name'.")

    module_path, callable_path = executor_path.split(":", 1)
    module = importlib.import_module(module_path)

    obj = module
    for part in callable_path.split("."):
        obj = getattr(obj, part)

    return obj


def instantiate_executor_class(executor_path: Optional[str], db: Any) -> Any:
    """If the executor points to a class, instantiate it with db."""
    if not executor_path:
        return None

    if ":" not in executor_path:
        raise ValueError(f"Invalid executor path: {executor_path}")

    module_path, callable_path = executor_path.split(":", 1)
    module = importlib.import_module(module_path)

    parts = callable_path.split(".")
    cls = module
    for part in parts[:-1]:
        cls = getattr(cls, part)

    instance = cls(db)
    return instance


def get_executor_method(executor_path: Optional[str], db: Any) -> Any:
    """Resolve executor path and return a bound method or callable.

    For paths like `module:ClassName.method_name`, instantiates ClassName(db)
    and returns the bound method.
    For paths like `module:function_name`, returns the function directly.
    """
    if not executor_path:
        return None

    if ":" not in executor_path:
        raise ValueError(f"Invalid executor path: {executor_path}")

    module_path, callable_path = executor_path.split(":", 1)
    module = importlib.import_module(module_path)

    parts = callable_path.split(".")

    if len(parts) == 1:
        # function_name
        return getattr(module, parts[0])

    # ClassName.method_name
    cls = module
    for part in parts[:-1]:
        cls = getattr(cls, part)

    instance = cls(db)
    return getattr(instance, parts[-1])


async def execute_skill_md(skill_id: str, arguments: Dict[str, Any], db: Any, parser: Any) -> Dict[str, Any]:
    """Execute a SKILL.md workflow by skill_id."""
    from app.agents.skills.parser import SkillMDParser

    if parser is None:
        parser = SkillMDParser()

    doc = parser.get_document(skill_id)
    if not doc:
        raise ValueError(f"SKILL.md workflow not found: {skill_id}")

    executor_path = doc.executor
    if not executor_path:
        return {
            "skill": skill_id,
            "result": {
                "success": True,
                "message": f"Workflow '{doc.name}' is a prompt/template skill with no executable backend.",
                "workflow_steps": doc.workflow_steps,
            },
        }

    method = get_executor_method(executor_path, db)
    result = await method(**arguments)
    return {"skill": skill_id, "result": result}
