"""
Negotiation Circuit Breaker - 协商熔断保护机制

防止协商过程中的各种风险和异常情况：
1. 无限循环协商
2. 异常价格操纵
3. 恶意拖延战术
4. 价格不收敛
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class CircuitBreakerTrigger(str, Enum):
    """熔断触发原因"""
    MAX_ROUNDS = "max_rounds"           # 达到最大轮数
    MAX_DURATION = "max_duration"       # 超过最大持续时间
    PRICE_NOT_CONVERGING = "not_converging"  # 价格不收敛
    SUSPICIOUS_PATTERN = "suspicious"   # 可疑行为模式
    PRICE_ANOMALY = "price_anomaly"     # 价格异常
    RAPID_FLUCTUATION = "fluctuation"   # 价格剧烈波动
    USER_REQUEST = "user_request"       # 用户主动请求


class ArbitrationResult(str, Enum):
    """仲裁结果"""
    ACCEPT_MIDPOINT = "accept_midpoint"     # 接受中间价
    ACCEPT_BUYER = "accept_buyer"           # 接受买方报价
    ACCEPT_SELLER = "accept_seller"         # 接受卖方报价
    REJECT_BOTH = "reject_both"             # 双方拒绝
    EXTEND_NEGOTIATION = "extend"           # 延长协商
    MANUAL_REVIEW = "manual_review"         # 转人工审核


@dataclass
class NegotiationMetrics:
    """协商指标数据"""
    round_count: int = 0
    start_time: Optional[datetime] = None
    last_update_time: Optional[datetime] = None

    # 价格历史
    buyer_offers: List[float] = field(default_factory=list)
    seller_offers: List[float] = field(default_factory=list)

    # 响应时间历史（秒）
    response_times: List[float] = field(default_factory=list)

    # 行为标记
    rapid_changes: int = 0  # 快速变化次数
    stalemate_count: int = 0  # 僵局次数

    def add_round(self, buyer_price: Optional[float], seller_price: Optional[float]):
        """记录一轮协商"""
        self.round_count += 1
        self.last_update_time = datetime.utcnow()

        if buyer_price:
            self.buyer_offers.append(buyer_price)
        if seller_price:
            self.seller_offers.append(seller_price)

    def get_price_volatility(self) -> float:
        """计算价格波动率"""
        all_prices = self.buyer_offers + self.seller_offers
        if len(all_prices) < 2:
            return 0.0

        avg = sum(all_prices) / len(all_prices)
        variance = sum((p - avg) ** 2 for p in all_prices) / len(all_prices)
        std_dev = variance ** 0.5

        return std_dev / avg if avg > 0 else 0.0

    def get_price_gap(self) -> Optional[float]:
        """获取当前价格差距"""
        if not self.buyer_offers or not self.seller_offers:
            return None

        last_buyer = self.buyer_offers[-1]
        last_seller = self.seller_offers[-1]

        # 买方出价 vs 卖方报价
        return abs(last_seller - last_buyer)

    def get_convergence_rate(self) -> float:
        """计算价格收敛率"""
        if len(self.buyer_offers) < 2 or len(self.seller_offers) < 2:
            return 0.0

        # 计算双方各自的让步幅度
        buyer_concession = abs(self.buyer_offers[-1] - self.buyer_offers[0])
        seller_concession = abs(self.seller_offers[-1] - self.seller_offers[0])

        initial_gap = abs(self.seller_offers[0] - self.buyer_offers[0])
        if initial_gap == 0:
            return 1.0

        total_concession = buyer_concession + seller_concession
        return min(1.0, total_concession / initial_gap)


@dataclass
class CircuitBreakerResult:
    """熔断检查结果"""
    should_break: bool
    trigger: Optional[CircuitBreakerTrigger] = None
    reason: Optional[str] = None
    suggested_action: Optional[str] = None
    arbitration: Optional[ArbitrationResult] = None
    metrics: Optional[Dict[str, Any]] = None


class NegotiationCircuitBreaker:
    """
    协商熔断保护器

    监控协商过程，在以下情况触发熔断：
    1. 轮数超限 - 防止无限循环
    2. 时间超限 - 防止拖延战术
    3. 价格不收敛 - 双方僵持不下
    4. 异常行为 - 检测到可疑模式
    """

    # 默认配置
    DEFAULT_MAX_ROUNDS = 20
    DEFAULT_MAX_DURATION_MINUTES = 60
    DEFAULT_MIN_CONVERGENCE_RATE = 0.3  # 最小30%收敛率
    DEFAULT_MAX_PRICE_GAP_RATIO = 0.5   # 最大50%价格分歧
    DEFAULT_MAX_VOLATILITY = 0.5        # 最大50%波动率

    def __init__(
        self,
        max_rounds: Optional[int] = None,
        max_duration_minutes: Optional[int] = None,
        min_convergence_rate: Optional[float] = None,
        max_price_gap_ratio: Optional[float] = None,
        max_volatility: Optional[float] = None,
    ):
        self.max_rounds = max_rounds or self.DEFAULT_MAX_ROUNDS
        self.max_duration = timedelta(minutes=max_duration_minutes or self.DEFAULT_MAX_DURATION_MINUTES)
        self.min_convergence_rate = min_convergence_rate or self.DEFAULT_MIN_CONVERGENCE_RATE
        self.max_price_gap_ratio = max_price_gap_ratio or self.DEFAULT_MAX_PRICE_GAP_RATIO
        self.max_volatility = max_volatility or self.DEFAULT_MAX_VOLATILITY

    async def check(
        self,
        metrics: NegotiationMetrics,
        current_buyer_price: Optional[float] = None,
        current_seller_price: Optional[float] = None,
    ) -> CircuitBreakerResult:
        """
        检查是否需要熔断

        Args:
            metrics: 协商指标
            current_buyer_price: 买方当前出价
            current_seller_price: 卖方当前报价

        Returns:
            CircuitBreakerResult
        """
        # 1. 检查轮数限制
        if metrics.round_count >= self.max_rounds:
            return CircuitBreakerResult(
                should_break=True,
                trigger=CircuitBreakerTrigger.MAX_ROUNDS,
                reason=f"Reached maximum rounds ({self.max_rounds})",
                suggested_action="Suggest accepting midpoint price or manual review",
                arbitration=ArbitrationResult.ACCEPT_MIDPOINT,
                metrics={"rounds": metrics.round_count},
            )

        # 2. 检查时间限制
        if metrics.start_time:
            elapsed = datetime.utcnow() - metrics.start_time
            if elapsed > self.max_duration:
                return CircuitBreakerResult(
                    should_break=True,
                    trigger=CircuitBreakerTrigger.MAX_DURATION,
                    reason=f"Exceeded maximum duration ({self.max_duration})",
                    suggested_action="Negotiation timeout - recommend rejection",
                    arbitration=ArbitrationResult.REJECT_BOTH,
                    metrics={"elapsed_minutes": elapsed.total_seconds() / 60},
                )

        # 3. 检查价格收敛
        if metrics.round_count >= 5:  # 至少5轮后再检查收敛
            convergence_rate = metrics.get_convergence_rate()
            if convergence_rate < self.min_convergence_rate:
                return CircuitBreakerResult(
                    should_break=True,
                    trigger=CircuitBreakerTrigger.PRICE_NOT_CONVERGING,
                    reason=f"Price not converging (rate: {convergence_rate:.2%})",
                    suggested_action="Parties too far apart - recommend rejection",
                    arbitration=ArbitrationResult.REJECT_BOTH,
                    metrics={"convergence_rate": convergence_rate},
                )

        # 4. 检查价格分歧
        if current_buyer_price and current_seller_price:
            avg_price = (current_buyer_price + current_seller_price) / 2
            if avg_price > 0:
                gap_ratio = abs(current_seller_price - current_buyer_price) / avg_price
                if gap_ratio > self.max_price_gap_ratio:
                    return CircuitBreakerResult(
                        should_break=True,
                        trigger=CircuitBreakerTrigger.PRICE_ANOMALY,
                        reason=f"Price gap too large ({gap_ratio:.2%})",
                        suggested_action="Significant price difference - manual review needed",
                        arbitration=ArbitrationResult.MANUAL_REVIEW,
                        metrics={"gap_ratio": gap_ratio},
                    )

        # 5. 检查价格波动率
        if metrics.round_count >= 3:
            volatility = metrics.get_price_volatility()
            if volatility > self.max_volatility:
                return CircuitBreakerResult(
                    should_break=True,
                    trigger=CircuitBreakerTrigger.RAPID_FLUCTUATION,
                    reason=f"Excessive price volatility ({volatility:.2%})",
                    suggested_action="Unstable pricing detected - recommend rejection",
                    arbitration=ArbitrationResult.REJECT_BOTH,
                    metrics={"volatility": volatility},
                )

        # 6. 检查可疑行为模式
        suspicious_result = self._check_suspicious_patterns(metrics)
        if suspicious_result:
            return suspicious_result

        # 未触发熔断
        return CircuitBreakerResult(
            should_break=False,
            metrics={
                "rounds": metrics.round_count,
                "convergence_rate": metrics.get_convergence_rate(),
                "volatility": metrics.get_price_volatility(),
            },
        )

    def _check_suspicious_patterns(
        self,
        metrics: NegotiationMetrics,
    ) -> Optional[CircuitBreakerResult]:
        """检查可疑行为模式"""
        # 检查响应时间异常
        if len(metrics.response_times) >= 3:
            avg_response = sum(metrics.response_times) / len(metrics.response_times)
            last_response = metrics.response_times[-1]

            # 如果最近响应时间突然变得极长（拖延战术）
            if last_response > avg_response * 5 and last_response > 300:  # 5倍平均且超过5分钟
                return CircuitBreakerResult(
                    should_break=True,
                    trigger=CircuitBreakerTrigger.SUSPICIOUS_PATTERN,
                    reason="Suspicious delay detected (possible stalling tactic)",
                    suggested_action="Unusual response time - manual review",
                    arbitration=ArbitrationResult.MANUAL_REVIEW,
                    metrics={
                        "avg_response": avg_response,
                        "last_response": last_response,
                    },
                )

        # 检查价格反向调整（反复无常）
        if len(metrics.buyer_offers) >= 3:
            # 买方出价应该递增，如果出现递减可能是恶意行为
            recent_buyer = metrics.buyer_offers[-3:]
            if recent_buyer[2] < recent_buyer[1] < recent_buyer[0]:
                metrics.rapid_changes += 1
                if metrics.rapid_changes >= 2:
                    return CircuitBreakerResult(
                        should_break=True,
                        trigger=CircuitBreakerTrigger.SUSPICIOUS_PATTERN,
                        reason="Buyer repeatedly lowering offers (unusual behavior)",
                        suggested_action="Inconsistent bidding pattern detected",
                        arbitration=ArbitrationResult.MANUAL_REVIEW,
                    )

        if len(metrics.seller_offers) >= 3:
            # 卖方报价应该递减，如果出现递增可能是恶意行为
            recent_seller = metrics.seller_offers[-3:]
            if recent_seller[2] > recent_seller[1] > recent_seller[0]:
                metrics.rapid_changes += 1
                if metrics.rapid_changes >= 2:
                    return CircuitBreakerResult(
                        should_break=True,
                        trigger=CircuitBreakerTrigger.SUSPICIOUS_PATTERN,
                        reason="Seller repeatedly raising prices (unusual behavior)",
                        suggested_action="Inconsistent pricing pattern detected",
                        arbitration=ArbitrationResult.MANUAL_REVIEW,
                    )

        return None

    async def suggest_arbitration(
        self,
        metrics: NegotiationMetrics,
        trigger: CircuitBreakerTrigger,
    ) -> ArbitrationResult:
        """
        建议仲裁方案

        Args:
            metrics: 协商指标
            trigger: 熔断触发原因

        Returns:
            建议的仲裁结果
        """
        if trigger == CircuitBreakerTrigger.MAX_ROUNDS:
            # 达到最大轮数，建议接受中间价
            return ArbitrationResult.ACCEPT_MIDPOINT

        elif trigger == CircuitBreakerTrigger.PRICE_NOT_CONVERGING:
            # 价格不收敛，建议拒绝
            return ArbitrationResult.REJECT_BOTH

        elif trigger == CircuitBreakerTrigger.PRICE_ANOMALY:
            # 价格异常，转人工
            return ArbitrationResult.MANUAL_REVIEW

        elif trigger == CircuitBreakerTrigger.SUSPICIOUS_PATTERN:
            # 可疑行为，转人工
            return ArbitrationResult.MANUAL_REVIEW

        elif trigger == CircuitBreakerTrigger.MAX_DURATION:
            # 超时，建议拒绝
            return ArbitrationResult.REJECT_BOTH

        else:
            # 默认转人工
            return ArbitrationResult.MANUAL_REVIEW

    def calculate_midpoint_price(
        self,
        metrics: NegotiationMetrics,
    ) -> Optional[float]:
        """计算中间价（建议成交价）"""
        if not metrics.buyer_offers or not metrics.seller_offers:
            return None

        last_buyer = metrics.buyer_offers[-1]
        last_seller = metrics.seller_offers[-1]

        # 中间价
        return (last_buyer + last_seller) / 2

    def get_status_summary(self, metrics: NegotiationMetrics) -> Dict[str, Any]:
        """获取熔断器状态摘要"""
        return {
            "config": {
                "max_rounds": self.max_rounds,
                "max_duration_minutes": self.max_duration.total_seconds() / 60,
                "min_convergence_rate": self.min_convergence_rate,
                "max_price_gap_ratio": self.max_price_gap_ratio,
                "max_volatility": self.max_volatility,
            },
            "current_metrics": {
                "rounds": metrics.round_count,
                "convergence_rate": metrics.get_convergence_rate(),
                "volatility": metrics.get_price_volatility(),
                "price_gap": metrics.get_price_gap(),
            },
            "thresholds": {
                "rounds_remaining": self.max_rounds - metrics.round_count,
                "convergence_needed": self.min_convergence_rate,
                "volatility_limit": self.max_volatility,
            },
        }


# 便捷函数
async def check_negotiation_health(
    rounds: int,
    buyer_offers: List[float],
    seller_offers: List[float],
    start_time: Optional[datetime] = None,
) -> CircuitBreakerResult:
    """
    便捷函数：检查协商健康状况

    Args:
        rounds: 当前轮数
        buyer_offers: 买方出价历史
        seller_offers: 卖方报价历史
        start_time: 协商开始时间

    Returns:
        CircuitBreakerResult
    """
    metrics = NegotiationMetrics(
        round_count=rounds,
        start_time=start_time,
        buyer_offers=buyer_offers,
        seller_offers=seller_offers,
    )

    breaker = NegotiationCircuitBreaker()
    return await breaker.check(metrics)
