"""Agents Module - Multi-agent orchestration system for Agent Data Space Platform

Architecture (Agent != Skill != Tool):
- MainAgent: Orchestrator (routing + aggregation)
- AgentSession: Independent agent execution context (own LLM, tools, memory)
- AgentRegistry: Agent definition discovery + execution dispatch
- AgentToolRegistry: Atomic operation tools
"""

from app.agents.core import MainAgent
from app.agents.core import (
    AgentType,
    TaskStatus,
    MainAgentState,
    ReviewState,
    QAState,
    AssetOrganizeState,
    TradeState,
)
from app.agents.tools import AgentToolRegistry

# New agent architecture exports
from app.agents.agents import (
    AgentDefinition,
    AgentRequest,
    AgentResult,
    AgentSession,
    AgentRegistry,
    AgentMessageBus,
    SidechainLogger,
    CircuitBreaker,
)

__all__ = [
    # Core
    "MainAgent",
    "AgentToolRegistry",
    # State types
    "MainAgentState",
    "TaskStatus",
    "AgentType",
    "ReviewState",
    "QAState",
    "AssetOrganizeState",
    "TradeState",
    # New agent architecture
    "AgentDefinition",
    "AgentRequest",
    "AgentResult",
    "AgentSession",
    "AgentRegistry",
    "AgentMessageBus",
    "SidechainLogger",
    "CircuitBreaker",
]
