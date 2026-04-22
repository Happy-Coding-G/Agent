"""
Agent core package.

Only the MainAgent-based routing and sub-agent dispatch path is kept here.
"""

from .main_agent import MainAgent, SubAgents
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
from .state import (
    AgentType,
    TaskStatus,
    MainAgentState,
    ReviewState,
    QAState,
    AssetOrganizeState,
    TradeState,
)
from .prompts import (
    INTENT_DETECTION_PROMPT,
    QA_SYSTEM_PROMPT,
    ASSET_CLUSTER_PROMPT,
    REVIEW_CRITERIA,
    CAPABILITY_ROUTING_SYSTEM_PROMPT,
)

__all__ = [
    "MainAgent",
    "SubAgents",
    "AgentType",
    "TaskStatus",
    "MainAgentState",
    "ReviewState",
    "QAState",
    "AssetOrganizeState",
    "TradeState",
    "INTENT_DETECTION_PROMPT",
    "QA_SYSTEM_PROMPT",
    "ASSET_CLUSTER_PROMPT",
    "REVIEW_CRITERIA",
    "CAPABILITY_ROUTING_SYSTEM_PROMPT",
    # New agent architecture exports
    "AgentDefinition",
    "AgentRequest",
    "AgentResult",
    "AgentSession",
    "AgentRegistry",
    "AgentMessageBus",
    "SidechainLogger",
    "CircuitBreaker",
]
