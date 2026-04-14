"""Agent-layer skill package.

SKILL.md 是工作流文档的单一真相源：
- parser 负责读取和解析 markdown
- executor 负责把文档中的 executor 路径解析为可调用对象
- registry 为 MainAgent 提供 schema 暴露与执行入口
"""

from importlib import import_module

__all__ = [
    "SkillMDDocument",
    "SkillMDParser",
    "SkillRegistry",
    "execute_skill_md",
    "get_executor_method",
    "resolve_executor",
]


def __getattr__(name: str):
    lazy_map = {
        "SkillRegistry": "app.agents.skills.registry",
        "SkillMDDocument": "app.agents.skills.parser",
        "SkillMDParser": "app.agents.skills.parser",
        "execute_skill_md": "app.agents.skills.executor",
        "get_executor_method": "app.agents.skills.executor",
        "resolve_executor": "app.agents.skills.executor",
    }
    if name in lazy_map:
        module = import_module(lazy_map[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
