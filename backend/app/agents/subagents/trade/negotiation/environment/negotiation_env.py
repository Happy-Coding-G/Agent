"""
Negotiation Environment - 谈判环境模拟

用于训练RL Agent的模拟环境：
1. 状态转移
2. 奖励计算
3. 对手模拟
4. 回合管理
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class NegotiationAction(Enum):
    """协商动作"""
    ACCEPT = 0
    REJECT = 1
    COUNTER_LOW = 2      # 保守/激进反报价
    COUNTER_MEDIUM = 3   # 适中反报价
    COUNTER_HIGH = 4     # 激进/保守反报价


@dataclass
class NegotiationReward:
    """
    协商奖励

    多维度奖励设计
    """
    deal_value: float = 0.0        # 成交价值
    time_cost: float = 0.0         # 时间成本（负值）
    effort_cost: float = 0.0       # 努力成本（负值）
    relationship_value: float = 0.0  # 关系价值
    reputation_impact: float = 0.0   # 声誉影响

    def total(self) -> float:
        """总奖励"""
        return (
            self.deal_value +
            self.time_cost +
            self.effort_cost +
            self.relationship_value +
            self.reputation_impact
        )

    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return {
            "deal_value": round(self.deal_value, 2),
            "time_cost": round(self.time_cost, 2),
            "effort_cost": round(self.effort_cost, 2),
            "relationship_value": round(self.relationship_value, 2),
            "reputation_impact": round(self.reputation_impact, 2),
            "total": round(self.total(), 2),
        }


class SimulatedOpponent:
    """
    模拟对手

    用于训练环境的虚拟对手
    """

    def __init__(
        self,
        is_seller: bool,
        initial_price: float,
        reservation_price: float,
        strategy: str = "linear",  # "linear", "boulware", "conceder", "random"
    ):
        self.is_seller = is_seller
        self.initial_price = initial_price
        self.reservation_price = reservation_price
        self.strategy = strategy

        self.current_price = initial_price
        self.round_num = 0

    def make_offer(self, my_last_offer: Optional[float] = None) -> float:
        """做出报价"""
        self.round_num += 1

        if self.strategy == "linear":
            # 线性让步
            progress = min(self.round_num / 10, 1.0)
            if self.is_seller:
                self.current_price = self.initial_price - \
                    (self.initial_price - self.reservation_price) * progress
            else:
                self.current_price = self.initial_price + \
                    (self.reservation_price - self.initial_price) * progress

        elif self.strategy == "boulware":
            # 坚定策略，后期才让步
            if self.round_num < 7:
                self.current_price = self.initial_price * 0.98
            else:
                progress = (self.round_num - 7) / 3
                if self.is_seller:
                    self.current_price = self.initial_price - \
                        (self.initial_price - self.reservation_price) * progress
                else:
                    self.current_price = self.initial_price + \
                        (self.reservation_price - self.initial_price) * progress

        elif self.strategy == "conceder":
            # 早期快速让步
            progress = min(self.round_num / 5, 1.0)
            if self.is_seller:
                self.current_price = self.initial_price - \
                    (self.initial_price - self.reservation_price) * progress
            else:
                self.current_price = self.initial_price + \
                    (self.reservation_price - self.initial_price) * progress

        elif self.strategy == "random":
            # 随机策略
            noise = np.random.uniform(-0.1, 0.1) * self.initial_price
            self.current_price += noise

        # 考虑对方报价
        if my_last_offer is not None:
            # 向对方靠拢一点
            self.current_price = (self.current_price + my_last_offer) / 2

        # 限制在保留价格内
        if self.is_seller:
            self.current_price = max(self.reservation_price, self.current_price)
        else:
            self.current_price = min(self.reservation_price, self.current_price)

        return round(self.current_price, 2)

    def will_accept(self, offer: float) -> bool:
        """判断是否接受报价"""
        if self.is_seller:
            return offer >= self.reservation_price * 0.95
        else:
            return offer <= self.reservation_price * 1.05


class NegotiationEnvironment:
    """
    谈判环境

    用于训练RL Agent的Gym-like环境
    """

    def __init__(
        self,
        is_seller: bool = True,
        max_rounds: int = 10,
        time_limit: float = 300.0,  # 5分钟
    ):
        self.is_seller = is_seller
        self.max_rounds = max_rounds
        self.time_limit = time_limit

        # 环境状态
        self.round_num = 0
        self.time_elapsed = 0.0
        self.done = False

        # 价格配置
        self.my_initial_price: Optional[float] = None
        self.my_reservation_price: Optional[float] = None
        self.my_current_price: Optional[float] = None

        self.opponent_initial_price: Optional[float] = None
        self.opponent_reservation_price: Optional[float] = None
        self.opponent_current_price: Optional[float] = None

        # 模拟对手
        self.simulated_opponent: Optional[SimulatedOpponent] = None

        # 三档价格
        self.conservative_price: float = 0.0
        self.moderate_price: float = 0.0
        self.aggressive_price: float = 0.0

        # 历史
        self.price_history: List[Dict[str, Any]] = []
        self.outcome: Optional[str] = None

    def reset(
        self,
        my_initial: float,
        my_reservation: float,
        opponent_initial: float,
        opponent_reservation: float,
        opponent_strategy: str = "linear",
    ) -> Dict[str, Any]:
        """
        重置环境

        Returns:
            initial_state: 初始状态
        """
        self.round_num = 0
        self.time_elapsed = 0.0
        self.done = False

        self.my_initial_price = my_initial
        self.my_reservation_price = my_reservation
        self.my_current_price = my_initial

        self.opponent_initial_price = opponent_initial
        self.opponent_reservation_price = opponent_reservation
        self.opponent_current_price = opponent_initial

        # 创建模拟对手
        self.simulated_opponent = SimulatedOpponent(
            is_seller=not self.is_seller,
            initial_price=opponent_initial,
            reservation_price=opponent_reservation,
            strategy=opponent_strategy,
        )

        # 计算三档价格
        self._calculate_three_tier_prices()

        # 清空历史
        self.price_history.clear()
        self.outcome = None

        return self._get_state()

    def _calculate_three_tier_prices(self):
        """计算三档价格"""
        if self.is_seller:
            # 卖方：从高到低
            price_range = self.my_initial_price - self.my_reservation_price
            self.conservative_price = self.my_initial_price - price_range * 0.1
            self.moderate_price = self.my_initial_price - price_range * 0.3
            self.aggressive_price = self.my_reservation_price + price_range * 0.1
        else:
            # 买方：从低到高
            price_range = self.my_reservation_price - self.my_initial_price
            self.conservative_price = self.my_initial_price + price_range * 0.1
            self.moderate_price = self.my_initial_price + price_range * 0.3
            self.aggressive_price = self.my_reservation_price - price_range * 0.1

    def step(self, action: int, offer_price: Optional[float] = None) -> Tuple[Dict[str, Any], NegotiationReward, bool, Dict[str, Any]]:
        """
        执行一步

        Args:
            action: 动作索引
            offer_price: 反报价（如果是counter动作）

        Returns:
            (state, reward, done, info)
        """
        if self.done:
            return self._get_state(), NegotiationReward(), True, {"error": "Episode already done"}

        self.round_num += 1
        self.time_elapsed += 10.0  # 假设每轮10秒

        reward = NegotiationReward()
        info = {"action": NegotiationAction(action).name}

        action_enum = NegotiationAction(action)

        if action_enum == NegotiationAction.ACCEPT:
            # 接受对手报价
            deal_price = self.opponent_current_price
            reward = self._calculate_reward(deal_price, accepted=True)
            self.done = True
            self.outcome = "accept"
            info["deal_price"] = deal_price

        elif action_enum == NegotiationAction.REJECT:
            # 拒绝/退出
            reward = self._calculate_reward(None, accepted=False, walked_away=True)
            self.done = True
            self.outcome = "reject"

        else:
            # 反报价
            if offer_price is None:
                # 根据档位生成价格
                offer_price = self._get_price_by_tier(action_enum)

            self.my_current_price = offer_price

            # 检查对手是否接受
            if self.simulated_opponent.will_accept(offer_price):
                reward = self._calculate_reward(offer_price, accepted=True)
                self.done = True
                self.outcome = "counter_accepted"
                info["deal_price"] = offer_price
            else:
                # 对手反报价
                self.opponent_current_price = self.simulated_opponent.make_offer(offer_price)
                reward.time_cost = -1.0  # 时间成本

                # 检查是否达到最大轮次
                if self.round_num >= self.max_rounds:
                    reward = self._calculate_reward(None, accepted=False, timeout=True)
                    self.done = True
                    self.outcome = "timeout"

        # 记录历史
        self.price_history.append({
            "round": self.round_num,
            "my_price": self.my_current_price,
            "opponent_price": self.opponent_current_price,
            "action": action_enum.name,
        })

        info.update({
            "round": self.round_num,
            "my_price": self.my_current_price,
            "opponent_price": self.opponent_current_price,
        })

        return self._get_state(), reward, self.done, info

    def _get_price_by_tier(self, action: NegotiationAction) -> float:
        """根据档位获取价格"""
        if action == NegotiationAction.COUNTER_LOW:
            return self.conservative_price if self.is_seller else self.aggressive_price
        elif action == NegotiationAction.COUNTER_MEDIUM:
            return self.moderate_price
        elif action == NegotiationAction.COUNTER_HIGH:
            return self.aggressive_price if self.is_seller else self.conservative_price
        else:
            return self.moderate_price

    def _get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "round_num": self.round_num,
            "max_rounds": self.max_rounds,
            "time_elapsed": self.time_elapsed,
            "time_limit": self.time_limit,
            "time_pressure": self.time_elapsed / self.time_limit,

            "my_last_price": self.my_current_price,
            "opponent_last_price": self.opponent_current_price,
            "my_initial_price": self.my_initial_price,
            "opponent_initial_price": self.opponent_initial_price,

            "conservative_price": self.conservative_price,
            "moderate_price": self.moderate_price,
            "aggressive_price": self.aggressive_price,

            "price_gap": abs(self.my_current_price - self.opponent_current_price) if self.my_current_price else 0,
        }

    def _calculate_reward(
        self,
        deal_price: Optional[float],
        accepted: bool,
        walked_away: bool = False,
        timeout: bool = False,
    ) -> NegotiationReward:
        """计算奖励"""
        reward = NegotiationReward()

        if accepted and deal_price is not None:
            # 成交奖励
            if self.is_seller:
                # 卖方：价格越高越好
                price_range = self.my_initial_price - self.my_reservation_price
                if price_range > 0:
                    value = (deal_price - self.my_reservation_price) / price_range
                else:
                    value = 0.5
            else:
                # 买方：价格越低越好
                price_range = self.my_reservation_price - self.my_initial_price
                if price_range > 0:
                    value = (self.my_reservation_price - deal_price) / price_range
                else:
                    value = 0.5

            reward.deal_value = value * 100  # 基础成交价值

            # 时间奖励（越快越好）
            time_bonus = max(0, 20 - self.round_num * 2)
            reward.time_cost = time_bonus

            # 关系价值
            reward.relationship_value = 10  # 成功建立关系

            # 声誉影响
            reward.reputation_impact = 5

        elif walked_away:
            # 退出惩罚
            reward.effort_cost = -20
            reward.reputation_impact = -2

        elif timeout:
            # 超时惩罚
            reward.time_cost = -10
            reward.effort_cost = -15

        return reward

    def render(self) -> str:
        """渲染当前状态"""
        lines = [
            f"Round: {self.round_num}/{self.max_rounds}",
            f"Time: {self.time_elapsed:.1f}s/{self.time_limit}s",
            f"My Price: {self.my_current_price}",
            f"Opponent Price: {self.opponent_current_price}",
            f"Gap: {abs(self.my_current_price - self.opponent_current_price) if self.my_current_price else 0:.2f}",
        ]
        if self.outcome:
            lines.append(f"Outcome: {self.outcome}")
        return "\n".join(lines)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_rounds": self.round_num,
            "outcome": self.outcome,
            "final_price": self.my_current_price if self.outcome in ["accept", "counter_accepted"] else None,
            "price_history": self.price_history,
        }


def train_rl_agent(
    agent,
    env: NegotiationEnvironment,
    num_episodes: int = 1000,
) -> Dict[str, List[float]]:
    """
    训练RL Agent

    Returns:
        训练历史
    """
    history = {
        "rewards": [],
        "success_rate": [],
        "avg_rounds": [],
    }

    successes = 0

    for episode in range(num_episodes):
        # 随机配置
        my_initial = np.random.uniform(80, 120)
        my_reservation = my_initial * np.random.uniform(0.6, 0.9)
        opponent_initial = np.random.uniform(80, 120)
        opponent_reservation = opponent_initial * np.random.uniform(0.6, 0.9)
        strategy = np.random.choice(["linear", "boulware", "conceder"])

        state_dict = env.reset(
            my_initial=my_initial,
            my_reservation=my_reservation,
            opponent_initial=opponent_initial,
            opponent_reservation=opponent_reservation,
            opponent_strategy=strategy,
        )

        episode_reward = 0
        done = False

        while not done:
            # 这里需要与agent的接口匹配
            # 简化处理
            action = np.random.randint(0, 5)
            _, reward, done, info = env.step(action)
            episode_reward += reward.total()

        history["rewards"].append(episode_reward)

        if env.outcome in ["accept", "counter_accepted"]:
            successes += 1

        if (episode + 1) % 100 == 0:
            success_rate = successes / (episode + 1)
            avg_reward = np.mean(history["rewards"][-100:])
            logger.info(f"Episode {episode + 1}: Success Rate={success_rate:.2%}, Avg Reward={avg_reward:.2f}")

    return history
