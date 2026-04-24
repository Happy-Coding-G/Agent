"""Sub-agent package.

Agent definitions under this package are loaded from markdown documents
and executed through AgentRegistry → AgentSession.
"""

from importlib import import_module

_EXPORTS = {
    "AgentRegistry": ("app.agents.agents.registry", "AgentRegistry"),
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
