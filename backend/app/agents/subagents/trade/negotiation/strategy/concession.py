"""
Concession Strategy - 让步策略优化

基于时间压力和替代方案的动态让步：
1. 多种让步曲线（线性/对数/指数/Boulware/Conceder）
2. 时间压力函数
3. 替代方案评估
4. 效用最大化
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Tuple, Any
from enum import Enum
import numpy as np
from scipy.optimize import minimize_scalar

logger = logging.getLogger(__name__)


class ConcessionCurveType(Enum):
    """让步曲线类型"""
    LINEAR = "linear"              # 线性：匀速让步
    LOGARITHMIC = "logarithmic"    # 对数：先慢后快
    EXPONENTIAL = "exponential"    # 指数：先快后慢
    BOULWARE = "boulware"          # Boulware：坚定到最后
    CONCEDER = "conceder"          # Conceder：早期快速让步
    SIGMOID = "sigmoid"            # S型：中期加速让步


@dataclass
class ConcessionCurve:
    """
    让步曲线

    描述价格随轮次的变化
    """
    curve_type: ConcessionCurveType
    initial_price: float
    reservation_price: float
    max_rounds: int

    # 曲线参数
    beta: float = 1.0  # 形状参数

    def get_price(self, round_num: int) -> float:
        """获取指定轮次的价格"""
        if round_num >= self.max_rounds:
            return self.reservation_price

        progress = round_num / self.max_rounds

        if self.curve_type == ConcessionCurveType.LINEAR:
            # 线性: P = P0 + (Pr - P0) * t
            alpha = progress

        elif self.curve_type == ConcessionCurveType.LOGARITHMIC:
            # 对数: P = P0 + (Pr - P0) * log(1 + beta*t) / log(1 + beta)
            alpha = np.log(1 + self.beta * progress) / np.log(1 + self.beta)

        elif self.curve_type == ConcessionCurveType.EXPONENTIAL:
            # 指数: P = P0 + (Pr - P0) * (1 - exp(-beta*t))
            alpha = 1 - np.exp(-self.beta * progress)

        elif self.curve_type == ConcessionCurveType.BOULWARE:
            # Boulware: P = P0 + (Pr - P0) * t^beta (beta > 1)
            beta = max(self.beta, 3.0)
            alpha = progress ** beta

        elif self.curve_type == ConcessionCurveType.CONCEDER:
            # Conceder: P = P0 + (Pr - P0) * (1 - (1-t)^beta) (beta > 1)
            beta = max(self.beta, 2.0)
            alpha = 1 - (1 - progress) ** beta

        elif self.curve_type == ConcessionCurveType.SIGMOID:
            # Sigmoid
            alpha = 1 / (1 + np.exp(-self.beta * (progress - 0.5)))

        else:
            alpha = progress

        return self.initial_price + alpha * (self.reservation_price - self.initial_price)

    def get_concession_rate(self, round_num: int) -> float:
        """获取指定轮次的让步率（导数近似）"""
        if round_num >= self.max_rounds - 1:
            return 0.0

        p1 = self.get_price(round_num)
        p2 = self.get_price(round_num + 1)

        if self.initial_price == self.reservation_price:
            return 0.0

        return abs(p2 - p1) / abs(self.reservation_price - self.initial_price)

    def get_curve_points(self, num_points: int = 50) -> List[Tuple[int, float]]:
        """获取曲线点（用于可视化）"""
        points = []
        for i in range(num_points):
            round_num = int(i * self.max_rounds / num_points)
            price = self.get_price(round_num)
            points.append((round_num, price))
        return points


class TimePressureFunction:
    """
    时间压力函数

    模拟时间压力对让步意愿的影响
    """

    def __init__(
        self,
        base_pressure: float = 0.0,
        deadline_effect: float = 0.5,
        urgency_factor: float = 1.0,
    ):
        self.base_pressure = base_pressure
        self.deadline_effect = deadline_effect
        self.urgency_factor = urgency_factor

    def calculate(
        self,
        round_num: int,
        max_rounds: int,
        time_elapsed: float,
        time_limit: float,
    ) -> float:
        """
        计算时间压力

        Returns:
            pressure: [0, 1] 时间压力值
        """
        # 轮次压力
        round_pressure = round_num / max_rounds if max_rounds > 0 else 0.0

        # 时钟压力
        clock_pressure = time_elapsed / time_limit if time_limit > 0 else 0.0

        # 综合压力
        pressure = max(round_pressure, clock_pressure)

        # 应用deadline效应（最后时刻压力急剧上升）
        if pressure > 0.8:
            pressure = pressure + (pressure - 0.8) * self.deadline_effect

        # 应用紧迫因子
        pressure = pressure * self.urgency_factor

        return min(1.0, self.base_pressure + pressure)

    def get_concession_multiplier(self, pressure: float) -> float:
        """
        获取让步倍率

        压力越大，让步越快（倍率越大）
        """
        # 基础倍率1.0，压力最大时倍率2.0
        return 1.0 + pressure


class AlternativeEvaluator:
    """
    替代方案评估器

    评估BATNA (Best Alternative To Negotiated Agreement)
    """

    def __init__(self):
        self.alternatives: List[Dict[str, Any]] = []

    def add_alternative(self, price: float, quality: float = 0.5, availability: float = 1.0):
        """添加替代方案"""
        self.alternatives.append({
            "price": price,
            "quality": quality,
            "availability": availability,
            "score": self._calculate_score(price, quality, availability),
        })

    def _calculate_score(self, price: float, quality: float, availability: float) -> float:
        """计算替代方案得分"""
        # 综合评分：价格越低越好，质量越高越好，可用性越高越好
        return (1.0 / (1 + price / 100)) * quality * availability

    def get_batna(self) -> Optional[Dict[str, Any]]:
        """获取最佳替代方案"""
        if not self.alternatives:
            return None
        return max(self.alternatives, key=lambda x: x["score"])

    def get_batna_value(self) -> float:
        """获取BATNA价值"""
        batna = self.get_batna()
        if batna is None:
            return 0.0
        return batna["score"]

    def should_accept(self, offer_price: float, offer_quality: float = 0.5) -> bool:
        """
        判断是否应接受报价

        如果报价优于BATNA，则接受
        """
        batna = self.get_batna()
        if batna is None:
            return True

        offer_score = self._calculate_score(offer_price, offer_quality, 1.0)
        return offer_score >= batna["score"]


class ConcessionStrategy:
    """
    让步策略

    整合让步曲线、时间压力、替代方案的完整策略
    """

    def __init__(
        self,
        curve_type: ConcessionCurveType = ConcessionCurveType.LOGARITHMIC,
        initial_price: float = 100.0,
        reservation_price: float = 80.0,
        max_rounds: int = 10,
    ):
        self.curve = ConcessionCurve(
            curve_type=curve_type,
            initial_price=initial_price,
            reservation_price=reservation_price,
            max_rounds=max_rounds,
        )
        self.time_pressure = TimePressureFunction()
        self.alternatives = AlternativeEvaluator()

        # 效用函数参数
        self.risk_aversion = 0.5
        self.time_discount = 0.95  # 每轮时间折扣因子

    def get_offer(
        self,
        round_num: int,
        time_elapsed: float = 0.0,
        time_limit: float = 100.0,
        opponent_offer: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        生成报价

        Returns:
            {
                "price": float,
                "concession_rate": float,
                "time_pressure": float,
                "reasoning": str,
            }
        """
        # 1. 计算时间压力
        pressure = self.time_pressure.calculate(
            round_num, self.curve.max_rounds, time_elapsed, time_limit
        )

        # 2. 获取基准价格（来自让步曲线）
        base_price = self.curve.get_price(round_num)

        # 3. 应用时间压力调整
        multiplier = self.time_pressure.get_concession_multiplier(pressure)

        # 根据方向调整
        if self.curve.initial_price > self.curve.reservation_price:
            # 卖方：时间压力大时降价更多
            adjusted_price = self.curve.initial_price - \
                           (self.curve.initial_price - base_price) * multiplier
        else:
            # 买方：时间压力大时加价更多
            adjusted_price = self.curve.initial_price + \
                           (base_price - self.curve.initial_price) * multiplier

        # 4. 限制在合理范围
        adjusted_price = max(
            min(self.curve.initial_price, self.curve.reservation_price),
            min(max(self.curve.initial_price, self.curve.reservation_price), adjusted_price)
        )

        # 5. 考虑对手报价
        if opponent_offer is not None:
            adjusted_price = self._adjust_for_opponent_offer(
                adjusted_price, opponent_offer, round_num
            )

        # 6. 生成理由
        reasoning = self._generate_reasoning(round_num, pressure, adjusted_price)

        return {
            "price": round(adjusted_price, 2),
            "concession_rate": self.curve.get_concession_rate(round_num),
            "time_pressure": pressure,
            "reasoning": reasoning,
        }

    def _adjust_for_opponent_offer(
        self,
        base_price: float,
        opponent_offer: float,
        round_num: int,
    ) -> float:
        """根据对手报价调整"""
        # 如果对手报价比我们的预期好，向他靠拢
        if self.curve.initial_price > self.curve.reservation_price:
            # 卖方
            if opponent_offer > base_price * 0.9:
                # 对手报价接近我们的预期，可以稍微提高
                return (base_price + opponent_offer) / 2
        else:
            # 买方
            if opponent_offer < base_price * 1.1:
                return (base_price + opponent_offer) / 2

        return base_price

    def should_accept(
        self,
        offer_price: float,
        round_num: int,
        time_pressure: float,
    ) -> Dict[str, Any]:
        """
        判断是否应接受报价
        """
        # 1. 检查是否优于BATNA
        if not self.alternatives.should_accept(offer_price):
            return {
                "should_accept": False,
                "reason": "报价不如BATNA",
                "batna_value": self.alternatives.get_batna_value(),
            }

        # 2. 检查是否达到保留价格
        if self.curve.initial_price > self.curve.reservation_price:
            # 卖方：报价 >= 保留价
            if offer_price >= self.curve.reservation_price * 0.95:
                return {
                    "should_accept": True,
                    "reason": "报价达到保留价格",
                    "confidence": 0.9,
                }
        else:
            # 买方：报价 <= 保留价
            if offer_price <= self.curve.reservation_price * 1.05:
                return {
                    "should_accept": True,
                    "reason": "报价达到保留价格",
                    "confidence": 0.9,
                }

        # 3. 检查是否快到最后且有收益
        if time_pressure > 0.8:
            utility = self.calculate_utility(offer_price, round_num)
            if utility > 0.6:
                return {
                    "should_accept": True,
                    "reason": "时间紧迫且收益可接受",
                    "utility": utility,
                    "confidence": 0.7,
                }

        return {
            "should_accept": False,
            "reason": "报价未达到接受标准",
        }

    def calculate_utility(self, price: float, round_num: int) -> float:
        """
        计算效用

        综合考虑价格收益和时间成本
        """
        # 价格效用
        if self.curve.initial_price > self.curve.reservation_price:
            # 卖方：价格越高越好
            price_range = self.curve.initial_price - self.curve.reservation_price
            if price_range > 0:
                price_utility = (price - self.curve.reservation_price) / price_range
            else:
                price_utility = 0.5
        else:
            # 买方：价格越低越好
            price_range = self.curve.reservation_price - self.curve.initial_price
            if price_range > 0:
                price_utility = (self.curve.reservation_price - price) / price_range
            else:
                price_utility = 0.5

        # 时间效用（越早成交越好）
        time_utility = self.time_discount ** round_num

        # 风险调整
        if self.risk_aversion > 0.5:
            # 风险厌恶：更看重确定性
            utility = 0.6 * price_utility + 0.4 * time_utility
        else:
            # 风险偏好：更看重价格
            utility = 0.8 * price_utility + 0.2 * time_utility

        return max(0.0, min(1.0, utility))

    def optimize_strategy(self, opponent_model=None) -> Dict[str, Any]:
        """
        优化策略参数

        基于对手模型调整让步曲线类型
        """
        if opponent_model is None:
            return {"curve_type": self.curve.curve_type.value}

        profile = opponent_model.get_profile()

        # 根据对手风格选择策略
        if profile.negotiation_style.value == "competitive":
            # 对手强硬，我们也采用Boulware策略
            best_type = ConcessionCurveType.BOULWARE
        elif profile.negotiation_style.value == "accommodating":
            # 对手软弱，可以采用Conceder快速成交
            best_type = ConcessionCurveType.CONCEDER
        elif profile.concession_rate > 0.15:
            # 对手让步快，我们线性让步
            best_type = ConcessionCurveType.LINEAR
        else:
            # 对手让步慢，我们对数让步
            best_type = ConcessionCurveType.LOGARITHMIC

        # 如果建议改变，更新曲线
        if best_type != self.curve.curve_type:
            self.curve.curve_type = best_type
            logger.info(f"Optimized concession curve to {best_type.value}")

        return {
            "curve_type": best_type.value,
            "beta": self.curve.beta,
            "reasoning": f"Based on opponent {profile.negotiation_style.value} style",
        }

    def _generate_reasoning(self, round_num: int, pressure: float, price: float) -> str:
        """生成策略理由"""
        reasons = []

        # 曲线类型
        reasons.append(f"使用{self.curve.curve_type.value}让步曲线")

        # 时间压力
        if pressure > 0.7:
            reasons.append(f"时间压力高({pressure:.2f})，加速让步")
        elif pressure < 0.3:
            reasons.append(f"时间充裕({pressure:.2f})，保持立场")

        # 价格位置
        progress = abs(price - self.curve.initial_price) / \
                   abs(self.curve.reservation_price - self.curve.initial_price)
        reasons.append(f"已完成{progress:.0%}预期让步")

        return "; ".join(reasons)


def create_optimal_concession_strategy(
    is_seller: bool,
    target_price: float,
    reservation_price: float,
    max_rounds: int = 10,
    urgency: str = "normal",
) -> ConcessionStrategy:
    """
    创建最优让步策略

    Args:
        is_seller: 是否为卖方
        target_price: 目标价格
        reservation_price: 保留价格
        max_rounds: 最大轮次
        urgency: 紧迫度 ("low", "normal", "high")

    Returns:
        ConcessionStrategy
    """
    # 根据紧迫度选择曲线类型
    urgency_map = {
        "low": ConcessionCurveType.BOULWARE,
        "normal": ConcessionCurveType.LOGARITHMIC,
        "high": ConcessionCurveType.CONCEDER,
    }
    curve_type = urgency_map.get(urgency, ConcessionCurveType.LOGARITHMIC)

    # 确保价格方向正确
    if is_seller and target_price < reservation_price:
        target_price, reservation_price = reservation_price, target_price
    elif not is_seller and target_price > reservation_price:
        target_price, reservation_price = reservation_price, target_price

    strategy = ConcessionStrategy(
        curve_type=curve_type,
        initial_price=target_price,
        reservation_price=reservation_price,
        max_rounds=max_rounds,
    )

    # 设置时间压力参数
    if urgency == "high":
        strategy.time_pressure.urgency_factor = 1.5
    elif urgency == "low":
        strategy.time_pressure.urgency_factor = 0.7

    return strategy
