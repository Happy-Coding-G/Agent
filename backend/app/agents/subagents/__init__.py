"""Sub-agent package with lazy exports.

Backward compatibility: re-exports AgentRegistry as SubAgentRegistry
for legacy code that imports from this module.
"""

from importlib import import_module

_EXPORTS = {
    "QAAgent": ("app.agents.subagents.qa_agent", "QAAgent"),
    "ReviewAgent": ("app.agents.subagents.review_agent", "ReviewAgent"),
    "AssetOrganizeAgent": ("app.agents.subagents.asset_organize_agent", "AssetOrganizeAgent"),
    "TradeAgent": ("app.agents.subagents.trade", "TradeAgent"),
    # SubAgentRegistry is now an alias for AgentRegistry
    "SubAgentRegistry": ("app.agents.agents.registry", "AgentRegistry"),
    "AgentRegistry": ("app.agents.agents.registry", "AgentRegistry"),
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
