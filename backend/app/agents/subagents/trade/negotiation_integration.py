"""
Negotiation Module Integration - 博弈模块集成

将Phase 3的博弈模块集成到TradeAgent：
1. 对手建模集成
2. RL决策集成
3. 让步策略集成
4. 完整的协商工作流
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.subagents.trade.negotiation.models.opponent import (
    OpponentModel,
    OpponentProfile,
    NegotiationStyle,
)
from app.agents.subagents.trade.negotiation.rl.agent import (
    RLNegotiationAgent,
    NegotiationPolicy,
    NegotiationState,
    PPOTrainer,
)
from app.agents.subagents.trade.negotiation.strategy.concession import (
    ConcessionStrategy,
    create_optimal_concession_strategy,
    ConcessionCurveType,
)
from app.services.pricing.pricing_service import UnifiedPricingService

logger = logging.getLogger(__name__)


@dataclass
class NegotiationDecision:
    """协商决策结果"""
    action: str  # accept, reject, counter
    price: Optional[float] = None
    confidence: float = 0.5
    reasoning: str = ""
    strategy_used: str = ""

    # 元信息
    opponent_model_version: str = ""
    concession_rate: float = 0.0
    time_pressure: float = 0.0


class SmartNegotiationAgent:
    """
    智能协商Agent

    整合所有Phase 3模块的协商系统
    """

    def __init__(
        self,
        db: AsyncSession,
        agent_id: str,
        is_seller: bool = True,
        enable_rl: bool = True,
        enable_opponent_modeling: bool = True,
    ):
        self.db = db
        self.agent_id = agent_id
        self.is_seller = is_seller
        self.enable_rl = enable_rl
        self.enable_opponent_modeling = enable_opponent_modeling

        # 子模块
        self.opponent_models: Dict[str, OpponentModel] = {}
        self.rl_agent: Optional[RLNegotiationAgent] = None
        self.concession_strategy: Optional[ConcessionStrategy] = None

        # 定价服务
        self.pricing_service = UnifiedPricingService(db)

        # 协商状态
        self.current_negotiation: Optional[Dict[str, Any]] = None
        self.round_num: int = 0

        if enable_rl:
            policy = NegotiationPolicy()
            trainer = PPOTrainer(policy)
            self.rl_agent = RLNegotiationAgent(
                policy=policy,
                is_seller=is_seller,
                trainer=trainer,
            )

    async def start_negotiation(
        self,
        asset_id: str,
        opponent_id: str,
        initial_offer: Optional[float] = None,
    ) -> Dict[str, Any]:
        """开始协商"""
        # 获取增强版定价建议
        pricing = await self.pricing_service.calculate_price(asset_id)

        # 初始化对手模型
        if self.enable_opponent_modeling and opponent_id not in self.opponent_models:
            self.opponent_models[opponent_id] = OpponentModel(opponent_id)

        # 初始化让步策略
        target = pricing.recommended_price
        reserve = pricing.aggressive_price if self.is_seller else pricing.conservative_price

        self.concession_strategy = create_optimal_concession_strategy(
            is_seller=self.is_seller,
            target_price=target,
            reservation_price=reserve,
            urgency="normal",
        )

        self.current_negotiation = {
            "asset_id": asset_id,
            "opponent_id": opponent_id,
            "started_at": datetime.utcnow(),
            "pricing": pricing,
        }
        self.round_num = 0

        return {
            "negotiation_id": f"{self.agent_id}_{opponent_id}_{datetime.utcnow().timestamp()}",
            "initial_offer": initial_offer or pricing.recommended_price,
            "three_tier_prices": {
                "conservative": pricing.conservative_price,
                "moderate": pricing.moderate_price,
                "aggressive": pricing.aggressive_price,
            },
            "strategy": "rl" if self.enable_rl else "rule_based",
        }

    async def negotiate_round(
        self,
        opponent_id: str,
        opponent_offer: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> NegotiationDecision:
        """
        执行一轮协商

        完整的决策流程：
        1. 记录对手报价
        2. 更新对手模型
        3. 构建状态
        4. RL决策
        5. 让步策略优化
        6. 生成决策
        """
        self.round_num += 1
        context = context or {}

        # 1. 记录对手行为
        if self.enable_opponent_modeling and opponent_id in self.opponent_models:
            self.opponent_models[opponent_id].record_offer(
                price=opponent_offer,
                round_num=self.round_num,
                is_opponent=True,
                response_time=context.get("response_time", 5.0),
            )

        # 2. 更新对手模型
        opponent_profile = None
        if self.enable_opponent_modeling and opponent_id in self.opponent_models:
            self.opponent_models[opponent_id].update_model()
            opponent_profile = self.opponent_models[opponent_id].get_profile()

        # 3. 构建协商状态
        pricing = self.current_negotiation["pricing"]

        state = NegotiationState(
            my_last_price=self.concession_strategy.curve.initial_price if self.concession_strategy else pricing.recommended_price,
            opponent_last_price=opponent_offer,
            my_initial_price=pricing.recommended_price,
            opponent_initial_price=context.get("opponent_initial", opponent_offer),
            round_num=self.round_num,
            max_rounds=context.get("max_rounds", 10),
            time_elapsed=(datetime.utcnow() - self.current_negotiation["started_at"]).total_seconds(),
            time_limit=context.get("time_limit", 300),
            conservative_price=pricing.conservative_price,
            moderate_price=pricing.moderate_price,
            aggressive_price=pricing.aggressive_price,
            opponent_style=self._get_opponent_style_code(opponent_profile),
            opponent_concession_rate=opponent_profile.concession_rate if opponent_profile else 0.1,
            opponent_price_sensitivity=opponent_profile.price_sensitivity if opponent_profile else 0.5,
            opponent_patience=opponent_profile.patience_level if opponent_profile else 0.5,
            my_total_concession=0.0,  # 简化
            opponent_total_concession=0.0,
            price_gap=abs(pricing.recommended_price - opponent_offer),
            gap_trend=0.0,
            market_pressure=context.get("market_pressure", 0.5),
            alternative_deals=context.get("alternatives", 0),
            deal_urgency=context.get("urgency", 0.5),
        )

        # 4. 使用RL Agent决策
        if self.enable_rl and self.rl_agent:
            result = self.rl_agent.decide_action(
                state=state,
                opponent_model=self.opponent_models.get(opponent_id),
                use_rl=True,
            )
        else:
            # 使用规则策略
            result = self._rule_based_decision(state, opponent_offer, opponent_profile)

        # 5. 让步策略优化
        if self.concession_strategy and opponent_id in self.opponent_models:
            self.concession_strategy.optimize_strategy(
                self.opponent_models[opponent_id]
            )

        # 6. 组装决策
        decision = NegotiationDecision(
            action=result["action"],
            price=result.get("counter_price"),
            confidence=result["confidence"],
            reasoning=result["reasoning"],
            strategy_used="rl_ppo" if self.enable_rl else "rule_based",
            opponent_model_version="1.0" if opponent_profile else "",
            time_pressure=state.time_pressure,
        )

        return decision

    def _rule_based_decision(
        self,
        state: NegotiationState,
        opponent_offer: float,
        opponent_profile: Optional[OpponentProfile],
    ) -> Dict[str, Any]:
        """基于规则的决策"""
        # 简单的基于三档价格的决策
        if self.is_seller:
            if opponent_offer >= state.conservative_price * 0.95:
                return {
                    "action": "accept",
                    "confidence": 0.9,
                    "reasoning": "报价达到保守价位",
                }
            elif opponent_offer >= state.moderate_price:
                if state.time_pressure > 0.7:
                    return {
                        "action": "accept",
                        "confidence": 0.8,
                        "reasoning": "报价合理且时间紧迫",
                    }
                else:
                    return {
                        "action": "counter_moderate",
                        "counter_price": state.conservative_price * 0.98,
                        "confidence": 0.7,
                        "reasoning": "尝试争取更高价格",
                    }
            else:
                return {
                    "action": "counter_moderate",
                    "counter_price": state.moderate_price,
                    "confidence": 0.6,
                    "reasoning": "报价偏低，反报价至适中区间",
                }
        else:
            # 买方逻辑
            if opponent_offer <= state.aggressive_price * 1.05:
                return {
                    "action": "accept",
                    "confidence": 0.9,
                    "reasoning": "报价达到激进价位",
                }
            elif opponent_offer <= state.moderate_price:
                return {
                    "action": "accept",
                    "confidence": 0.8,
                    "reasoning": "报价在合理范围",
                }
            else:
                return {
                    "action": "counter_moderate",
                    "counter_price": state.moderate_price * 0.95,
                    "confidence": 0.7,
                    "reasoning": "尝试压低价格",
                }

    def _get_opponent_style_code(self, profile: Optional[OpponentProfile]) -> int:
        """获取对手风格编码"""
        if profile is None:
            return 1  # Collaborative default

        style_map = {
            "competitive": 0,
            "collaborative": 1,
            "compromising": 2,
            "avoiding": 3,
            "accommodating": 4,
        }
        return style_map.get(profile.negotiation_style.value, 1)

    def record_outcome(
        self,
        opponent_id: str,
        outcome: str,  # accept, reject, timeout
        deal_price: Optional[float] = None,
    ):
        """记录协商结果"""
        if opponent_id in self.opponent_models:
            self.opponent_models[opponent_id].record_outcome(outcome, deal_price)

        if self.current_negotiation:
            self.current_negotiation["outcome"] = outcome
            self.current_negotiation["deal_price"] = deal_price
            self.current_negotiation["ended_at"] = datetime.utcnow()
            self.current_negotiation["total_rounds"] = self.round_num

    def get_opponent_profile(self, opponent_id: str) -> Optional[Dict[str, Any]]:
        """获取对手画像"""
        if opponent_id not in self.opponent_models:
            return None

        model = self.opponent_models[opponent_id]
        return {
            "profile": model.get_profile().to_dict(),
            "statistics": model.get_statistics(),
        }

    def get_negotiation_stats(self) -> Dict[str, Any]:
        """获取协商统计"""
        if not self.current_negotiation:
            return {}

        return {
            "current_negotiation": self.current_negotiation,
            "round_num": self.round_num,
            "opponent_models_count": len(self.opponent_models),
        }


# 便捷函数
async def create_smart_negotiator(
    db: AsyncSession,
    agent_id: str,
    is_seller: bool = True,
    **kwargs,
) -> SmartNegotiationAgent:
    """创建智能协商Agent"""
    return SmartNegotiationAgent(
        db=db,
        agent_id=agent_id,
        is_seller=is_seller,
        **kwargs,
    )
