"""
RL Negotiation Agent - 强化学习协商Agent

基于Actor-Critic架构的协商策略学习：
1. 状态空间：价格、轮次、时间压力、对手特征
2. 动作空间：接受/拒绝/反报价（保守/适中/激进）
3. 奖励函数：成交收益 + 时间惩罚 + 对手关系
4. PPO训练
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Deque
from collections import deque
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical

logger = logging.getLogger(__name__)


@dataclass
class NegotiationState:
    """
    协商状态

    完全描述当前协商局势
    """
    # 价格信息
    my_last_price: float
    opponent_last_price: float
    my_initial_price: float
    opponent_initial_price: float

    # 进度信息
    round_num: int
    max_rounds: int
    time_elapsed: float  # 已用时间（秒）
    time_limit: float    # 时间限制（秒）

    # 三档价格阈值
    conservative_price: float
    moderate_price: float
    aggressive_price: float

    # 对手特征（来自OpponentModel）
    opponent_style: int           # 0-4: Competitive, Collaborative, etc.
    opponent_concession_rate: float
    opponent_price_sensitivity: float
    opponent_patience: float

    # 历史统计
    my_total_concession: float    # 我的总让步幅度
    opponent_total_concession: float  # 对手总让步幅度
    price_gap: float              # 当前价格差距
    gap_trend: float              # 差距变化趋势

    # 外部条件
    market_pressure: float        # 市场压力 [0,1]
    alternative_deals: int        # 替代方案数量
    deal_urgency: float           # 成交紧迫度 [0,1]

    def to_tensor(self) -> torch.Tensor:
        """转换为神经网络输入"""
        features = [
            # 价格归一化（相对于适中价）
            self.my_last_price / self.moderate_price if self.moderate_price > 0 else 1.0,
            self.opponent_last_price / self.moderate_price if self.moderate_price > 0 else 1.0,
            (self.my_last_price - self.opponent_last_price) / self.moderate_price if self.moderate_price > 0 else 0.0,

            # 进度
            self.round_num / self.max_rounds if self.max_rounds > 0 else 0.0,
            self.time_elapsed / self.time_limit if self.time_limit > 0 else 0.0,

            # 三档价格相对位置
            self.conservative_price / self.moderate_price if self.moderate_price > 0 else 1.0,
            self.aggressive_price / self.moderate_price if self.moderate_price > 0 else 1.0,

            # 对手特征
            self.opponent_style / 4.0,
            self.opponent_concession_rate,
            self.opponent_price_sensitivity,
            self.opponent_patience,

            # 历史统计
            self.my_total_concession,
            self.opponent_total_concession,
            self.gap_trend,

            # 外部条件
            self.market_pressure,
            self.alternative_deals / 5.0,  # 归一化
            self.deal_urgency,
        ]

        return torch.tensor(features, dtype=torch.float32)

    @property
    def time_pressure(self) -> float:
        """计算时间压力"""
        round_pressure = self.round_num / self.max_rounds if self.max_rounds > 0 else 0.0
        clock_pressure = self.time_elapsed / self.time_limit if self.time_limit > 0 else 0.0
        return max(round_pressure, clock_pressure)


class NegotiationPolicy(nn.Module):
    """
    协商策略网络 (Actor-Critic)

    Actor: 输出动作概率分布
    Critic: 评估状态价值
    """

    def __init__(
        self,
        state_dim: int = 19,
        action_dim: int = 5,
        hidden_dim: int = 128,
    ):
        super().__init__()

        self.state_dim = state_dim
        self.action_dim = action_dim

        # 共享特征提取层
        self.shared = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
        )

        # Actor头
        self.actor = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, action_dim),
        )

        # Critic头
        self.critic = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )

        self._init_weights()

    def _init_weights(self):
        """初始化权重"""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.orthogonal_(m.weight, gain=np.sqrt(2))
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        前向传播

        Returns:
            action_logits: [batch, action_dim]
            state_value: [batch, 1]
        """
        features = self.shared(state)
        action_logits = self.actor(features)
        state_value = self.critic(features)
        return action_logits, state_value

    def select_action(
        self,
        state: NegotiationState,
        deterministic: bool = False,
    ) -> Tuple[int, float, float]:
        """
        选择动作

        Args:
            state: 协商状态
            deterministic: 是否确定性选择

        Returns:
            action: 动作索引
            log_prob: 动作对数概率
            value: 状态价值
        """
        with torch.no_grad():
            state_tensor = state.to_tensor().unsqueeze(0)
            action_logits, state_value = self.forward(state_tensor)

            if deterministic:
                action = torch.argmax(action_logits, dim=-1).item()
                log_prob = 0.0
            else:
                probs = F.softmax(action_logits, dim=-1)
                dist = Categorical(probs)
                action = dist.sample().item()
                log_prob = dist.log_prob(torch.tensor(action)).item()

            return action, log_prob, state_value.item()

    def evaluate_actions(
        self,
        states: torch.Tensor,
        actions: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        评估动作（用于PPO训练）

        Returns:
            log_probs: 动作对数概率
            values: 状态价值
            entropy: 策略熵
        """
        action_logits, values = self.forward(states)
        probs = F.softmax(action_logits, dim=-1)
        dist = Categorical(probs)

        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()

        return log_probs, values.squeeze(-1), entropy


class PPOTrainer:
    """
    PPO训练器

    Proximal Policy Optimization
    """

    def __init__(
        self,
        policy: NegotiationPolicy,
        lr: float = 3e-4,
        gamma: float = 0.99,
        epsilon: float = 0.2,
        value_coef: float = 0.5,
        entropy_coef: float = 0.01,
    ):
        self.policy = policy
        self.optimizer = torch.optim.Adam(policy.parameters(), lr=lr)

        self.gamma = gamma
        self.epsilon = epsilon
        self.value_coef = value_coef
        self.entropy_coef = entropy_coef

        # 训练缓冲区
        self.states: Deque[torch.Tensor] = deque(maxlen=10000)
        self.actions: Deque[int] = deque(maxlen=10000)
        self.rewards: Deque[float] = deque(maxlen=10000)
        self.log_probs: Deque[float] = deque(maxlen=10000)
        self.values: Deque[float] = deque(maxlen=10000)
        self.dones: Deque[bool] = deque(maxlen=10000)

    def store_transition(
        self,
        state: NegotiationState,
        action: int,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ):
        """存储转移"""
        self.states.append(state.to_tensor())
        self.actions.append(action)
        self.rewards.append(reward)
        self.log_probs.append(log_prob)
        self.values.append(value)
        self.dones.append(done)

    def update(self, batch_size: int = 64, epochs: int = 4) -> Dict[str, float]:
        """
        更新策略

        Returns:
            训练指标
        """
        if len(self.states) < batch_size:
            return {}

        # 准备数据
        states = torch.stack(list(self.states))
        actions = torch.tensor(list(self.actions), dtype=torch.long)
        old_log_probs = torch.tensor(list(self.log_probs), dtype=torch.float32)
        old_values = torch.tensor(list(self.values), dtype=torch.float32)

        # 计算回报和优势
        returns, advantages = self._compute_gae()

        # 多轮更新
        total_loss = 0
        total_policy_loss = 0
        total_value_loss = 0
        total_entropy = 0

        for _ in range(epochs):
            # 随机采样
            indices = torch.randperm(len(states))[:batch_size]

            batch_states = states[indices]
            batch_actions = actions[indices]
            batch_old_log_probs = old_log_probs[indices]
            batch_returns = returns[indices]
            batch_advantages = advantages[indices]

            # 评估动作
            new_log_probs, new_values, entropy = self.policy.evaluate_actions(
                batch_states, batch_actions
            )

            # 计算比率
            ratio = torch.exp(new_log_probs - batch_old_log_probs)

            # PPO损失
            surr1 = ratio * batch_advantages
            surr2 = torch.clamp(ratio, 1 - self.epsilon, 1 + self.epsilon) * batch_advantages
            policy_loss = -torch.min(surr1, surr2).mean()

            # 价值损失
            value_loss = F.mse_loss(new_values, batch_returns)

            # 总损失
            loss = (
                policy_loss +
                self.value_coef * value_loss -
                self.entropy_coef * entropy.mean()
            )

            # 反向传播
            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.policy.parameters(), 0.5)
            self.optimizer.step()

            total_loss += loss.item()
            total_policy_loss += policy_loss.item()
            total_value_loss += value_loss.item()
            total_entropy += entropy.mean().item()

        n = epochs
        return {
            "loss": total_loss / n,
            "policy_loss": total_policy_loss / n,
            "value_loss": total_value_loss / n,
            "entropy": total_entropy / n,
        }

    def _compute_gae(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        计算广义优势估计 (GAE)
        """
        rewards = list(self.rewards)
        values = list(self.values)
        dones = list(self.dones)

        returns = []
        advantages = []

        gae = 0
        next_value = 0

        for t in reversed(range(len(rewards))):
            if dones[t]:
                next_value = 0
                gae = 0

            delta = rewards[t] + self.gamma * next_value - values[t]
            gae = delta + self.gamma * 0.95 * gae

            returns.insert(0, gae + values[t])
            advantages.insert(0, gae)

            next_value = values[t]

        returns = torch.tensor(returns, dtype=torch.float32)
        advantages = torch.tensor(advantages, dtype=torch.float32)

        # 标准化优势
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        return returns, advantages

    def clear_buffer(self):
        """清空缓冲区"""
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.log_probs.clear()
        self.values.clear()
        self.dones.clear()


class RLNegotiationAgent:
    """
    强化学习协商Agent

    整合策略网络、对手模型、让步策略
    """

    # 动作定义
    ACTIONS = [
        "accept",           # 接受报价
        "reject",           # 拒绝/退出
        "counter_conservative",  # 反报价-保守
        "counter_moderate",      # 反报价-适中
        "counter_aggressive",    # 反报价-激进
    ]

    def __init__(
        self,
        policy: Optional[NegotiationPolicy] = None,
        is_seller: bool = True,
        trainer: Optional[PPOTrainer] = None,
    ):
        self.is_seller = is_seller
        self.policy = policy or NegotiationPolicy()
        self.trainer = trainer

        # 当前协商状态
        self.current_state: Optional[NegotiationState] = None
        self.negotiation_history: List[Dict] = []

    def decide_action(
        self,
        state: NegotiationState,
        opponent_model=None,
        use_rl: bool = True,
    ) -> Dict[str, Any]:
        """
        决策动作

        Args:
            state: 当前状态
            opponent_model: 对手模型（可选）
            use_rl: 是否使用RL策略

        Returns:
            决策结果
        """
        self.current_state = state

        if use_rl and self.policy is not None:
            # 使用RL策略
            action_idx, log_prob, value = self.policy.select_action(state)
            action_name = self.ACTIONS[action_idx]
            confidence = 0.7  # RL置信度
        else:
            # 使用规则策略
            action_name, confidence = self._rule_based_decision(state, opponent_model)
            log_prob = 0.0
            value = 0.0

        # 计算具体价格
        counter_price = None
        if action_name.startswith("counter_"):
            counter_price = self._calculate_counter_price(action_name, state, opponent_model)

        result = {
            "action": action_name,
            "action_idx": self.ACTIONS.index(action_name) if action_name in self.ACTIONS else -1,
            "confidence": confidence,
            "counter_price": counter_price,
            "log_prob": log_prob,
            "value": value,
            "reasoning": self._generate_reasoning(action_name, state, opponent_model),
        }

        # 记录历史
        self.negotiation_history.append({
            "round": state.round_num,
            "state": state,
            "action": action_name,
            "result": result,
        })

        return result

    def _rule_based_decision(
        self,
        state: NegotiationState,
        opponent_model=None,
    ) -> Tuple[str, float]:
        """基于规则的决策"""
        my_price = state.my_last_price
        opponent_price = state.opponent_last_price

        # 对于卖方
        if self.is_seller:
            # 如果对手报价 >= 保守价，接受
            if opponent_price >= state.conservative_price * 0.95:
                return "accept", 0.9

            # 如果对手报价 >= 适中价且快到最后
            if opponent_price >= state.moderate_price and state.time_pressure > 0.7:
                return "accept", 0.8

            # 如果对手报价太低，拒绝
            if opponent_price < state.aggressive_price * 0.8:
                return "reject", 0.6

            # 根据时间压力选择反报价档位
            if state.time_pressure < 0.3:
                return "counter_conservative", 0.7
            elif state.time_pressure < 0.7:
                return "counter_moderate", 0.7
            else:
                return "counter_aggressive", 0.6

        # 对于买方
        else:
            # 如果对手报价 <= 激进价，接受
            if opponent_price <= state.aggressive_price * 1.05:
                return "accept", 0.9

            # 如果对手报价 <= 适中价且快到最后
            if opponent_price <= state.moderate_price and state.time_pressure > 0.7:
                return "accept", 0.8

            # 如果对手报价太高，拒绝
            if opponent_price > state.conservative_price * 1.2:
                return "reject", 0.6

            # 根据时间压力选择反报价档位
            if state.time_pressure < 0.3:
                return "counter_conservative", 0.7
            elif state.time_pressure < 0.7:
                return "counter_moderate", 0.7
            else:
                return "counter_aggressive", 0.6

    def _calculate_counter_price(
        self,
        action_name: str,
        state: NegotiationState,
        opponent_model=None,
    ) -> float:
        """计算反报价"""
        # 基于档位选择基准价格
        if action_name == "counter_conservative":
            base_price = state.conservative_price
        elif action_name == "counter_moderate":
            base_price = state.moderate_price
        else:  # aggressive
            base_price = state.aggressive_price

        # 微调
        if opponent_model:
            # 根据对手模型调整
            predictor = opponent_model.get_predictor()
            predicted_acceptance = predictor.predict_acceptance_probability(
                base_price, state.opponent_last_price, state.round_num
            )

            # 如果预测接受概率太低，向对手预期靠拢
            if predicted_acceptance < 0.3:
                opponent_target = state.opponent_last_price
                base_price = (base_price + opponent_target) / 2

        return round(base_price, 2)

    def _generate_reasoning(
        self,
        action_name: str,
        state: NegotiationState,
        opponent_model=None,
    ) -> str:
        """生成决策理由"""
        reasonings = []

        # 时间压力
        if state.time_pressure > 0.7:
            reasonings.append("时间压力较高")
        elif state.time_pressure < 0.3:
            reasonings.append("时间充裕")

        # 价格差距
        gap_ratio = abs(state.my_last_price - state.opponent_last_price) / state.moderate_price
        if gap_ratio < 0.1:
            reasonings.append("价格差距很小")
        elif gap_ratio > 0.5:
            reasonings.append("价格差距较大")

        # 动作说明
        action_reasons = {
            "accept": "报价在可接受范围内",
            "reject": "报价不可接受",
            "counter_conservative": "尝试争取更好价格",
            "counter_moderate": "提出公允价格",
            "counter_aggressive": "快速推进成交",
        }

        reasonings.append(action_reasons.get(action_name, ""))

        return "; ".join(filter(None, reasonings))

    def store_transition(
        self,
        state: NegotiationState,
        action: int,
        reward: float,
        log_prob: float,
        value: float,
        done: bool,
    ):
        """存储转移（用于训练）"""
        if self.trainer:
            self.trainer.store_transition(state, action, reward, log_prob, value, done)

    def train_step(self) -> Dict[str, float]:
        """训练步骤"""
        if self.trainer:
            metrics = self.trainer.update()
            self.trainer.clear_buffer()
            return metrics
        return {}

    def reset(self):
        """重置Agent状态"""
        self.current_state = None
        self.negotiation_history.clear()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "negotiation_history_length": len(self.negotiation_history),
            "is_seller": self.is_seller,
            "has_trainer": self.trainer is not None,
        }
