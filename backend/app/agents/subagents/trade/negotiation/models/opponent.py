"""
Opponent Modeling - 对手建模系统

基于历史交互数据建模对手行为：
1. 价格敏感度估计
2. 时间偏好学习
3. 让步模式识别
4. 策略类型分类 (竞争/合作/妥协)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Deque
from collections import deque
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
from scipy import stats
from scipy.optimize import curve_fit

logger = logging.getLogger(__name__)


class NegotiationStyle(Enum):
    """协商风格类型"""
    COMPETITIVE = "competitive"    # 竞争型：强硬、少让步
    COLLABORATIVE = "collaborative"  # 合作型：寻求双赢
    COMPROMISING = "compromising"   # 妥协型：快速让步
    AVOIDING = "avoiding"          # 回避型：消极参与
    ACCOMMODATING = "accommodating"  # 迁就型：轻易让步


class ConcessionPattern(Enum):
    """让步模式"""
    BOULWARE = "boulware"          # 坚定到最后才让步
    CONCEDER = "conceder"          # 早期快速让步
    LINEAR = "linear"              # 线性匀速让步
    LOGARITHMIC = "logarithmic"    # 先慢后快
    EXPONENTIAL = "exponential"    # 先快后慢
    IRREGULAR = "irregular"        # 不规则让步


@dataclass
class OfferRecord:
    """出价记录"""
    round_num: int
    price: float
    timestamp: datetime
    response_time: float  # 响应时间（秒）
    message: Optional[str] = None


@dataclass
class OpponentProfile:
    """
    对手画像

    全面描述对手的协商特征
    """
    opponent_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # 基础属性
    negotiation_style: NegotiationStyle = NegotiationStyle.COLLABORATIVE
    concession_pattern: ConcessionPattern = ConcessionPattern.LINEAR

    # 价格相关
    price_sensitivity: float = 0.5  # [0,1] 价格敏感度
    reservation_price_estimate: Optional[float] = None  # 估计的保留价格
    target_price_estimate: Optional[float] = None       # 估计的目标价格

    # 时间相关
    time_pressure_sensitivity: float = 0.5  # 时间压力敏感度
    patience_level: float = 0.5             # 耐心程度
    deadline_estimate: Optional[datetime] = None  # 估计的截止时间

    # 行为特征
    avg_response_time: float = 5.0  # 平均响应时间（秒）
    concession_rate: float = 0.1    # 平均让步率
    strategic_consistency: float = 0.5  # 策略一致性

    # 历史统计
    total_negotiations: int = 0
    successful_deals: int = 0
    avg_deal_price_ratio: float = 0.5  # 成交价相对于初始报价的比例

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "opponent_id": self.opponent_id,
            "negotiation_style": self.negotiation_style.value,
            "concession_pattern": self.concession_pattern.value,
            "price_sensitivity": round(self.price_sensitivity, 3),
            "reservation_price": self.reservation_price_estimate,
            "time_pressure": round(self.time_pressure_sensitivity, 3),
            "patience": round(self.patience_level, 3),
            "concession_rate": round(self.concession_rate, 3),
            "success_rate": self.successful_deals / max(self.total_negotiations, 1),
        }


class BehaviorPredictor:
    """
    行为预测器

    预测对手的下一步行为
    """

    def __init__(self, profile: OpponentProfile):
        self.profile = profile

    def predict_next_offer(
        self,
        current_offer: float,
        my_last_offer: float,
        round_num: int,
        max_rounds: int,
    ) -> Tuple[float, float]:
        """
        预测对手的下一个报价

        Returns:
            (predicted_offer, confidence)
        """
        # 基于让步模式预测
        if self.profile.concession_pattern == ConcessionPattern.BOULWARE:
            # 坚定型：很少让步
            if round_num < max_rounds * 0.7:
                predicted = current_offer * 0.98  # 微小让步
            else:
                predicted = current_offer * 0.90  # 最后才让步
            confidence = 0.7

        elif self.profile.concession_pattern == ConcessionPattern.CONCEDER:
            # 迁就型：快速让步
            concession = 0.15 * (1 - round_num / max_rounds)
            predicted = current_offer * (1 - concession)
            confidence = 0.6

        elif self.profile.concession_pattern == ConcessionPattern.LINEAR:
            # 线性让步
            progress = round_num / max_rounds
            target = self.profile.reservation_price_estimate or (current_offer * 0.8)
            predicted = current_offer + (target - current_offer) * progress * 0.5
            confidence = 0.65

        else:
            # 默认：小幅让步
            predicted = current_offer * 0.95
            confidence = 0.5

        return predicted, confidence

    def predict_acceptance_probability(
        self,
        offer: float,
        opponent_current: float,
        round_num: int,
    ) -> float:
        """
        预测对手接受报价的概率
        """
        # 基于保留价格估计
        reservation = self.profile.reservation_price_estimate
        if reservation is None:
            # 基于历史让步推断
            reservation = opponent_current * 0.85

        # 报价优于保留价格的概率
        if offer <= reservation:
            base_prob = 0.9
        else:
            # 超出保留价格，概率递减
            gap_ratio = (offer - reservation) / reservation
            base_prob = max(0.1, 0.9 - gap_ratio * 2)

        # 时间压力调整
        time_factor = 1 + self.profile.time_pressure_sensitivity * (round_num / 10)

        # 风格调整
        if self.profile.negotiation_style == NegotiationStyle.COMPETITIVE:
            style_factor = 0.8
        elif self.profile.negotiation_style == NegotiationStyle.ACCOMMODATING:
            style_factor = 1.2
        else:
            style_factor = 1.0

        prob = min(1.0, base_prob * time_factor * style_factor)
        return prob

    def predict_walk_away_probability(self, round_num: int, max_rounds: int) -> float:
        """
        预测对手退出的概率
        """
        if self.profile.patience_level > 0.7:
            # 高耐心，不太可能退出
            return 0.05

        # 基于轮次进度
        progress = round_num / max_rounds
        base_prob = progress * 0.3  # 最多30%退出概率

        # 风格调整
        if self.profile.negotiation_style == NegotiationStyle.AVOIDING:
            return min(1.0, base_prob * 2)

        return base_prob


class OpponentModel:
    """
    对手建模器

    在线学习对手行为特征
    """

    def __init__(self, opponent_id: str, max_history: int = 50):
        self.opponent_id = opponent_id
        self.max_history = max_history

        # 出价历史
        self.offer_history: Deque[OfferRecord] = deque(maxlen=max_history)
        self.my_offer_history: Deque[OfferRecord] = deque(maxlen=max_history)

        # 交互结果
        self.outcomes: List[str] = []  # "accept", "reject", "timeout"

        # 当前画像
        self.profile = OpponentProfile(opponent_id=opponent_id)
        self.predictor = BehaviorPredictor(self.profile)

        # 在线学习参数
        self.learning_rate = 0.1
        self.min_samples_for_update = 3

    def record_offer(
        self,
        price: float,
        round_num: int,
        is_opponent: bool = True,
        response_time: float = 5.0,
    ):
        """记录出价"""
        record = OfferRecord(
            round_num=round_num,
            price=price,
            timestamp=datetime.utcnow(),
            response_time=response_time,
        )

        if is_opponent:
            self.offer_history.append(record)
        else:
            self.my_offer_history.append(record)

    def record_outcome(self, outcome: str, deal_price: Optional[float] = None):
        """记录协商结果"""
        self.outcomes.append(outcome)
        self.profile.total_negotiations += 1

        if outcome == "accept":
            self.profile.successful_deals += 1
            if deal_price and self.offer_history:
                initial = self.offer_history[0].price
                ratio = deal_price / initial if initial > 0 else 0.5
                # 更新平均成交比例
                n = self.profile.successful_deals
                self.profile.avg_deal_price_ratio = (
                    (self.profile.avg_deal_price_ratio * (n - 1) + ratio) / n
                )

    def update_model(self):
        """更新对手模型"""
        if len(self.offer_history) < self.min_samples_for_update:
            return

        # 1. 识别协商风格
        self._identify_negotiation_style()

        # 2. 识别让步模式
        self._identify_concession_pattern()

        # 3. 估计价格参数
        self._estimate_price_parameters()

        # 4. 学习时间偏好
        self._learn_time_preferences()

        # 5. 计算让步率
        self._calculate_concession_rate()

        self.profile.updated_at = datetime.utcnow()
        logger.debug(f"Opponent model updated for {self.opponent_id}")

    def _identify_negotiation_style(self):
        """识别协商风格"""
        offers = list(self.offer_history)
        if len(offers) < 2:
            return

        # 分析让步幅度
        concessions = []
        for i in range(1, len(offers)):
            prev_price = offers[i - 1].price
            curr_price = offers[i].price
            if prev_price > 0:
                concession = abs(curr_price - prev_price) / prev_price
                concessions.append(concession)

        if not concessions:
            return

        avg_concession = np.mean(concessions)
        concession_variance = np.var(concessions)

        # 分类逻辑
        if avg_concession < 0.05 and concession_variance < 0.01:
            # 很少让步且稳定 = 竞争型
            self.profile.negotiation_style = NegotiationStyle.COMPETITIVE
        elif avg_concession > 0.15:
            # 快速让步 = 迁就型
            self.profile.negotiation_style = NegotiationStyle.ACCOMMODATING
        elif concession_variance > 0.05:
            # 不规则让步 = 回避型
            self.profile.negotiation_style = NegotiationStyle.AVOIDING
        elif 0.05 <= avg_concession <= 0.15:
            # 适度让步 = 合作型
            self.profile.negotiation_style = NegotiationStyle.COLLABORATIVE
        else:
            self.profile.negotiation_style = NegotiationStyle.COMPROMISING

    def _identify_concession_pattern(self):
        """识别让步模式"""
        offers = list(self.offer_history)
        if len(offers) < 3:
            return

        prices = [o.price for o in offers]
        rounds = [o.round_num for o in offers]

        # 计算价格变化率
        if len(prices) >= 3:
            # 尝试拟合不同模式
            try:
                # 线性
                linear_fit = np.polyfit(rounds, prices, 1)
                linear_residual = np.sum((np.polyval(linear_fit, rounds) - prices) ** 2)

                # 指数
                def exp_func(x, a, b, c):
                    return a * np.exp(-b * np.array(x)) + c

                popt, _ = curve_fit(exp_func, rounds, prices, maxfev=5000)
                exp_residual = np.sum((exp_func(rounds, *popt) - prices) ** 2)

                # 对数
                def log_func(x, a, b, c):
                    return a * np.log(np.array(x) + 1) + b + c

                popt_log, _ = curve_fit(log_func, rounds, prices, maxfev=5000)
                log_residual = np.sum((log_func(rounds, *popt_log) - prices) ** 2)

                # 选择最佳拟合
                residuals = {
                    ConcessionPattern.LINEAR: linear_residual,
                    ConcessionPattern.EXPONENTIAL: exp_residual,
                    ConcessionPattern.LOGARITHMIC: log_residual,
                }

                best_pattern = min(residuals, key=residuals.get)

                # 如果残差都很大，可能是Boulware或不规则
                if min(residuals.values()) > np.var(prices):
                    # 检查是否是Boulware（后期才让步）
                    early_prices = prices[:len(prices)//2]
                    late_prices = prices[len(prices)//2:]
                    if np.std(early_prices) < np.std(late_prices) * 0.3:
                        best_pattern = ConcessionPattern.BOULWARE
                    else:
                        best_pattern = ConcessionPattern.IRREGULAR

                self.profile.concession_pattern = best_pattern

            except Exception as e:
                logger.debug(f"Pattern fitting failed: {e}")
                self.profile.concession_pattern = ConcessionPattern.IRREGULAR

    def _estimate_price_parameters(self):
        """估计价格参数"""
        offers = list(self.offer_history)
        if not offers:
            return

        prices = [o.price for o in offers]

        # 目标价格估计（可能是第一个报价）
        self.profile.target_price_estimate = prices[0]

        # 保留价格估计（最低/最高报价的延伸）
        if len(prices) >= 2:
            min_price = min(prices)
            max_price = max(prices)
            price_range = max_price - min_price

            # 假设保留价格在极值外延伸20%
            if self._is_seller():
                self.profile.reservation_price_estimate = min_price - price_range * 0.2
            else:
                self.profile.reservation_price_estimate = max_price + price_range * 0.2

        # 价格敏感度：基于价格变化的响应
        if len(prices) >= 2:
            price_changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
            avg_change = np.mean(price_changes) / np.mean(prices)
            self.profile.price_sensitivity = min(1.0, avg_change * 5)

    def _learn_time_preferences(self):
        """学习时间偏好"""
        offers = list(self.offer_history)
        if len(offers) < 2:
            return

        # 响应时间分析
        response_times = [o.response_time for o in offers]
        self.profile.avg_response_time = np.mean(response_times)

        # 响应时间变化 = 时间压力指标
        if len(response_times) >= 3:
            early_avg = np.mean(response_times[:len(response_times)//2])
            late_avg = np.mean(response_times[len(response_times)//2:])

            if late_avg < early_avg * 0.7:
                # 后期响应变快 = 有时间压力
                self.profile.time_pressure_sensitivity = 0.7
            elif late_avg > early_avg * 1.3:
                # 后期响应变慢 = 不着急
                self.profile.time_pressure_sensitivity = 0.3
            else:
                self.profile.time_pressure_sensitivity = 0.5

        # 耐心程度：让步速度与时间的关系
        concessions = []
        for i in range(1, len(offers)):
            price_diff = abs(offers[i].price - offers[i-1].price)
            time_diff = (offers[i].timestamp - offers[i-1].timestamp).total_seconds()
            if time_diff > 0:
                concessions.append(price_diff / time_diff)

        if concessions:
            avg_concession_speed = np.mean(concessions)
            # 快速让步 = 低耐心
            self.profile.patience_level = max(0.0, min(1.0, 1 - avg_concession_speed * 10))

    def _calculate_concession_rate(self):
        """计算让步率"""
        offers = list(self.offer_history)
        if len(offers) < 2:
            return

        initial = offers[0].price
        final = offers[-1].price
        rounds = len(offers)

        if initial > 0 and rounds > 1:
            total_concession = abs(final - initial) / initial
            self.profile.concession_rate = total_concession / (rounds - 1)

    def _is_seller(self) -> bool:
        """判断是否为卖方（基于出价趋势）"""
        offers = list(self.offer_history)
        if len(offers) < 2:
            return True

        # 价格下降趋势 = 卖方
        return offers[-1].price < offers[0].price

    def get_predictor(self) -> BehaviorPredictor:
        """获取预测器"""
        return self.predictor

    def get_profile(self) -> OpponentProfile:
        """获取当前画像"""
        return self.profile

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "opponent_id": self.opponent_id,
            "offer_count": len(self.offer_history),
            "model_confidence": min(1.0, len(self.offer_history) / 10),
            "profile": self.profile.to_dict(),
        }
