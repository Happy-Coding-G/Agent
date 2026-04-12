"""
Negotiation Module - Phase 3: Agent Game Theory & Negotiation

智能博弈与协商系统，提供：
1. 对手建模 (Opponent Modeling)
2. 强化学习协商 (RL Negotiation)
3. 让步策略优化 (Concession Strategy)
4. 谈判环境模拟 (Negotiation Environment)
"""

from app.agents.subagents.trade.negotiation.models.opponent import (
    OpponentModel,
    OpponentProfile,
    BehaviorPredictor,
)
from app.agents.subagents.trade.negotiation.rl.agent import (
    RLNegotiationAgent,
    NegotiationPolicy,
    NegotiationState,
)
from app.agents.subagents.trade.negotiation.strategy.concession import (
    ConcessionStrategy,
    TimePressureFunction,
    ConcessionCurve,
)
from app.agents.subagents.trade.negotiation.environment.negotiation_env import (
    NegotiationEnvironment,
    NegotiationAction,
    NegotiationReward,
)

__all__ = [
    # Opponent Modeling
    "OpponentModel",
    "OpponentProfile",
    "BehaviorPredictor",
    # RL Agent
    "RLNegotiationAgent",
    "NegotiationPolicy",
    "NegotiationState",
    # Strategy
    "ConcessionStrategy",
    "TimePressureFunction",
    "ConcessionCurve",
    # Environment
    "NegotiationEnvironment",
    "NegotiationAction",
    "NegotiationReward",
]
