"""Agent 层 - 独立会话式 Agent 架构。

本包实现了从函数式 Skill 调用到独立会话式 Agent 的架构重构：
- AgentSession: 每个 Agent 实例拥有独立的 LLM 客户端、工具注册表、记忆命名空间
- AgentMessageBus: Agent 间异步通信（Redis Pub/Sub + Celery）
- SidechainLogger: Agent 内部执行过程的独立日志
- CircuitBreaker: 熔断器防止故障 Agent 持续被调用
- AgentRegistry: Agent 定义注册与发现

设计原则：
1. Agent != Skill != Tool
2. Agent 是独立会话（独立 LLM、工具、记忆、数据库 session）
3. Agent 间异步通信
4. 失败显式处理
5. 记忆分层清晰（L3 namespace 隔离、L4 sidechain、L5 跨会话共享）
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AgentDefinition": ("app.agents.agents.definition", "AgentDefinition"),
    "AgentRequest": ("app.agents.agents.protocol", "AgentRequest"),
    "AgentResult": ("app.agents.agents.protocol", "AgentResult"),
    "AgentMessage": ("app.agents.agents.protocol", "AgentMessage"),
    "AgentMessageBus": ("app.agents.agents.bus", "AgentMessageBus"),
    "AgentSession": ("app.agents.agents.session", "AgentSession"),
    "AgentRegistry": ("app.agents.agents.registry", "AgentRegistry"),
    "SidechainLogger": ("app.agents.agents.sidechain", "SidechainLogger"),
    "CircuitBreaker": ("app.agents.agents.circuit_breaker", "CircuitBreaker"),
    "AgentMaxRoundsError": ("app.agents.agents.session", "AgentMaxRoundsError"),
    "SkillLoader": ("app.agents.skills.loader", "SkillLoader"),
    "SkillDefinition": ("app.agents.skills.loader", "SkillDefinition"),
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
