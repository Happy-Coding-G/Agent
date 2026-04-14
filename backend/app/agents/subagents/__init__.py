"""Sub-agent package with lazy exports."""

from importlib import import_module

_EXPORTS = {
    "FileQueryAgent": ("app.agents.subagents.file_query_agent", "FileQueryAgent"),
    "QAAgent": ("app.agents.subagents.qa_agent", "QAAgent"),
    "ReviewAgent": ("app.agents.subagents.review_agent", "ReviewAgent"),
    "AssetOrganizeAgent": ("app.agents.subagents.asset_organize_agent", "AssetOrganizeAgent"),
    "TradeAgent": ("app.agents.subagents.trade", "TradeAgent"),
    "SubAgentRegistry": ("app.agents.subagents.registry", "SubAgentRegistry"),
    "DynamicWorkflowSubAgent": ("app.agents.subagents.template", "DynamicWorkflowSubAgent"),
    "SubAgentTemplate": ("app.agents.subagents.template", "SubAgentTemplate"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
