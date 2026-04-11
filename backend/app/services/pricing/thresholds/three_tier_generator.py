"""
Three-Tier Price Threshold Generator - 三档价格阈值生成器

基于概率分布的三档定价：
- 保守价 (Conservative, P10): 成交概率 ~10%，最大化卖方利益
- 适中价 (Moderate, P50): 成交概率 ~50%，公允价值
- 激进价 (Aggressive, P90): 成交概率 ~90%，快速成交

支持：
1. 参数化分布拟合（对数正态、Gamma、Weibull）
2. 基于历史交易的价格分布估计
3. 置信度加权的价格选择
4. 动态阈值调整
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime
from enum import Enum
import numpy as np
from scipy import stats
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class PriceDistributionType(Enum):
    """价格分布类型"""
    LOGNORMAL = "lognormal"    # 对数正态（推荐，价格通常右偏）
    GAMMA = "gamma"            # Gamma分布
    WEIBULL = "weibull"        # Weibull分布
    NORMAL = "normal"          # 正态分布
    KERNEL = "kernel"          # 核密度估计（非参数）


@dataclass
class PriceThresholds:
    """
    三档价格阈值

    基于分位数的价格区间
    """
    conservative: float    # P10: 高价区，低成交概率
    moderate: float        # P50: 中位数，公允价值
    aggressive: float      # P90: 低价区，高成交概率

    # 概率解释
    conservative_prob: float = 0.10  # 在此价格成交的概率
    moderate_prob: float = 0.50
    aggressive_prob: float = 0.90

    # 分布参数
    distribution_type: PriceDistributionType = PriceDistributionType.LOGNORMAL
    distribution_params: Dict[str, float] = None

    # 置信区间
    confidence_interval_95: Tuple[float, float] = None  # 95%置信区间

    # 元数据
    generated_at: datetime = None
    sample_size: int = 0
    goodness_of_fit: float = 0.0  # 拟合优度

    def __post_init__(self):
        if self.distribution_params is None:
            self.distribution_params = {}
        if self.generated_at is None:
            self.generated_at = datetime.utcnow()
        if self.confidence_interval_95 is None:
            self.confidence_interval_95 = (self.aggressive, self.conservative)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "conservative": round(self.conservative, 2),
            "moderate": round(self.moderate, 2),
            "aggressive": round(self.aggressive, 2),
            "probabilities": {
                "conservative": self.conservative_prob,
                "moderate": self.moderate_prob,
                "aggressive": self.aggressive_prob,
            },
            "distribution": {
                "type": self.distribution_type.value,
                "params": self.distribution_params,
            },
            "confidence_interval": (
                round(self.confidence_interval_95[0], 2),
                round(self.confidence_interval_95[1], 2),
            ) if self.confidence_interval_95 else None,
            "sample_size": self.sample_size,
            "goodness_of_fit": round(self.goodness_of_fit, 4),
        }

    def get_price_by_strategy(self, strategy: str) -> float:
        """根据策略获取价格"""
        strategy_map = {
            "conservative": self.conservative,
            "moderate": self.moderate,
            "aggressive": self.aggressive,
            "premium": self.conservative,
            "fair": self.moderate,
            "penetration": self.aggressive,
        }
        return strategy_map.get(strategy.lower(), self.moderate)

    def calculate_expected_value(self) -> float:
        """计算期望值（假设对数正态分布）"""
        if self.distribution_type == PriceDistributionType.LOGNORMAL:
            mu = self.distribution_params.get("mu", np.log(self.moderate))
            sigma = self.distribution_params.get("sigma", 0.5)
            return np.exp(mu + sigma**2 / 2)
        else:
            return self.moderate

    def calculate_variance(self) -> float:
        """计算价格方差"""
        if self.distribution_type == PriceDistributionType.LOGNORMAL:
            mu = self.distribution_params.get("mu", np.log(self.moderate))
            sigma = self.distribution_params.get("sigma", 0.5)
            return (np.exp(sigma**2) - 1) * np.exp(2 * mu + sigma**2)
        else:
            # 近似计算
            return ((self.conservative - self.aggressive) / 2.56) ** 2


class PriceDistributionEstimator:
    """
    价格分布估计器

    基于历史交易数据拟合价格分布
    """

    def __init__(self):
        self.supported_distributions = {
            PriceDistributionType.LOGNORMAL: self._fit_lognormal,
            PriceDistributionType.GAMMA: self._fit_gamma,
            PriceDistributionType.WEIBULL: self._fit_weibull,
            PriceDistributionType.NORMAL: self._fit_normal,
        }

    def fit(
        self,
        prices: List[float],
        distribution_type: Optional[PriceDistributionType] = None,
    ) -> PriceThresholds:
        """
        拟合价格分布

        Args:
            prices: 历史交易价格列表
            distribution_type: 指定分布类型，None则自动选择

        Returns:
            PriceThresholds
        """
        if not prices or len(prices) < 3:
            logger.warning(f"Insufficient price data (n={len(prices)}), using default")
            return self._default_thresholds()

        prices = np.array(prices, dtype=np.float64)
        prices = prices[prices > 0]  # 过滤非正值

        if len(prices) < 3:
            return self._default_thresholds()

        # 自动选择最佳分布
        if distribution_type is None:
            distribution_type, params, gof = self._select_best_distribution(prices)
        else:
            params, gof = self.supported_distributions[distribution_type](prices)

        # 计算三档阈值
        thresholds = self._calculate_thresholds(
            prices, distribution_type, params, gof
        )

        return thresholds

    def fit_with_features(
        self,
        comparable_transactions: List[Dict[str, Any]],
        asset_features: Optional[Dict[str, float]] = None,
    ) -> PriceThresholds:
        """
        基于可比交易和特征拟合分布

        考虑特征相似度加权
        """
        if not comparable_transactions:
            return self._default_thresholds()

        prices = []
        weights = []

        for tx in comparable_transactions:
            price = tx.get("price", 0)
            if price <= 0:
                continue

            # 计算相似度权重
            similarity = tx.get("similarity", 0.5)
            weight = similarity ** 2  # 平方强调高相似度

            # 时间衰减
            days_ago = tx.get("days_ago", 0)
            time_decay = np.exp(-days_ago / 365)  # 一年衰减到1/e

            prices.append(price)
            weights.append(weight * time_decay)

        if not prices:
            return self._default_thresholds()

        # 加权分位数
        p10 = self._weighted_percentile(prices, weights, 0.10)
        p50 = self._weighted_percentile(prices, weights, 0.50)
        p90 = self._weighted_percentile(prices, weights, 0.90)

        # 估计分布参数
        if len(prices) >= 5:
            # 使用对数正态近似
            log_prices = np.log(prices)
            mu = np.average(log_prices, weights=weights)
            sigma = np.sqrt(np.average((log_prices - mu) ** 2, weights=weights))
            params = {"mu": mu, "sigma": sigma}
            gof = 0.8  # 假设良好拟合
        else:
            params = {}
            gof = 0.5

        return PriceThresholds(
            conservative=float(p10),
            moderate=float(p50),
            aggressive=float(p90),
            distribution_type=PriceDistributionType.LOGNORMAL,
            distribution_params=params,
            sample_size=len(prices),
            goodness_of_fit=gof,
        )

    def _select_best_distribution(
        self,
        prices: np.ndarray,
    ) -> Tuple[PriceDistributionType, Dict[str, float], float]:
        """选择最佳拟合分布"""
        results = []

        for dist_type, fit_func in self.supported_distributions.items():
            try:
                params, gof = fit_func(prices)
                results.append((dist_type, params, gof))
            except Exception as e:
                logger.debug(f"Failed to fit {dist_type}: {e}")
                continue

        if not results:
            # 默认使用对数正态
            return PriceDistributionType.LOGNORMAL, {}, 0.5

        # 选择拟合优度最高的
        best = max(results, key=lambda x: x[2])
        return best

    def _fit_lognormal(
        self,
        prices: np.ndarray,
    ) -> Tuple[Dict[str, float], float]:
        """拟合对数正态分布"""
        log_prices = np.log(prices)
        mu, sigma = stats.norm.fit(log_prices)

        # 计算拟合优度 (K-S检验)
        try:
            _, p_value = stats.kstest(
                log_prices,
                lambda x: stats.norm.cdf(x, mu, sigma)
            )
            gof = p_value
        except:
            gof = 0.5

        return {"mu": mu, "sigma": sigma}, gof

    def _fit_gamma(
        self,
        prices: np.ndarray,
    ) -> Tuple[Dict[str, float], float]:
        """拟合Gamma分布"""
        shape, loc, scale = stats.gamma.fit(prices, floc=0)

        try:
            _, p_value = stats.kstest(
                prices,
                lambda x: stats.gamma.cdf(x, shape, loc, scale)
            )
            gof = p_value
        except:
            gof = 0.5

        return {"shape": shape, "loc": loc, "scale": scale}, gof

    def _fit_weibull(
        self,
        prices: np.ndarray,
    ) -> Tuple[Dict[str, float], float]:
        """拟合Weibull分布"""
        shape, loc, scale = stats.weibull_min.fit(prices, floc=0)

        try:
            _, p_value = stats.kstest(
                prices,
                lambda x: stats.weibull_min.cdf(x, shape, loc, scale)
            )
            gof = p_value
        except:
            gof = 0.5

        return {"shape": shape, "loc": loc, "scale": scale}, gof

    def _fit_normal(
        self,
        prices: np.ndarray,
    ) -> Tuple[Dict[str, float], float]:
        """拟合正态分布"""
        mu, sigma = stats.norm.fit(prices)

        try:
            _, p_value = stats.kstest(
                prices,
                lambda x: stats.norm.cdf(x, mu, sigma)
            )
            gof = p_value
        except:
            gof = 0.5

        return {"mu": mu, "sigma": sigma}, gof

    def _calculate_thresholds(
        self,
        prices: np.ndarray,
        dist_type: PriceDistributionType,
        params: Dict[str, float],
        gof: float,
    ) -> PriceThresholds:
        """计算三档阈值"""
        # 根据分布类型计算分位数
        if dist_type == PriceDistributionType.LOGNORMAL:
            mu = params["mu"]
            sigma = params["sigma"]
            p10 = np.exp(stats.norm.ppf(0.10, mu, sigma))
            p50 = np.exp(stats.norm.ppf(0.50, mu, sigma))
            p90 = np.exp(stats.norm.ppf(0.90, mu, sigma))
            ci_low = np.exp(stats.norm.ppf(0.025, mu, sigma))
            ci_high = np.exp(stats.norm.ppf(0.975, mu, sigma))

        elif dist_type == PriceDistributionType.GAMMA:
            shape = params["shape"]
            loc = params["loc"]
            scale = params["scale"]
            p10 = stats.gamma.ppf(0.10, shape, loc, scale)
            p50 = stats.gamma.ppf(0.50, shape, loc, scale)
            p90 = stats.gamma.ppf(0.90, shape, loc, scale)
            ci_low = stats.gamma.ppf(0.025, shape, loc, scale)
            ci_high = stats.gamma.ppf(0.975, shape, loc, scale)

        elif dist_type == PriceDistributionType.WEIBULL:
            shape = params["shape"]
            loc = params["loc"]
            scale = params["scale"]
            p10 = stats.weibull_min.ppf(0.10, shape, loc, scale)
            p50 = stats.weibull_min.ppf(0.50, shape, loc, scale)
            p90 = stats.weibull_min.ppf(0.90, shape, loc, scale)
            ci_low = stats.weibull_min.ppf(0.025, shape, loc, scale)
            ci_high = stats.weibull_min.ppf(0.975, shape, loc, scale)

        else:  # Normal
            mu = params["mu"]
            sigma = params["sigma"]
            p10 = stats.norm.ppf(0.10, mu, sigma)
            p50 = stats.norm.ppf(0.50, mu, sigma)
            p90 = stats.norm.ppf(0.90, mu, sigma)
            ci_low = stats.norm.ppf(0.025, mu, sigma)
            ci_high = stats.norm.ppf(0.975, mu, sigma)

        return PriceThresholds(
            conservative=float(p90),   # P90作为保守价（卖方优势）
            moderate=float(p50),       # P50适中价
            aggressive=float(p10),     # P10激进价（快速成交）
            distribution_type=dist_type,
            distribution_params=params,
            confidence_interval_95=(float(ci_low), float(ci_high)),
            sample_size=len(prices),
            goodness_of_fit=gof,
        )

    def _weighted_percentile(
        self,
        values: List[float],
        weights: List[float],
        percentile: float,
    ) -> float:
        """计算加权分位数"""
        values = np.array(values)
        weights = np.array(weights)

        # 排序
        sorted_idx = np.argsort(values)
        sorted_values = values[sorted_idx]
        sorted_weights = weights[sorted_idx]

        # 计算累积权重
        cumsum = np.cumsum(sorted_weights)
        cumsum = cumsum / cumsum[-1]  # 归一化

        # 插值
        return np.interp(percentile, cumsum, sorted_values)

    def _default_thresholds(self) -> PriceThresholds:
        """默认阈值（冷启动）"""
        return PriceThresholds(
            conservative=100.0,
            moderate=80.0,
            aggressive=60.0,
            distribution_type=PriceDistributionType.LOGNORMAL,
            distribution_params={"mu": np.log(80), "sigma": 0.5},
            sample_size=0,
            goodness_of_fit=0.0,
        )


class ConfidenceBasedSelector:
    """
    基于置信度的价格选择器

    根据各维度置信度动态选择价格档位
    """

    def __init__(
        self,
        confidence_threshold_high: float = 0.8,
        confidence_threshold_low: float = 0.5,
    ):
        self.confidence_threshold_high = confidence_threshold_high
        self.confidence_threshold_low = confidence_threshold_low

    def select_price(
        self,
        thresholds: PriceThresholds,
        overall_confidence: float,
        confidence_breakdown: Optional[Dict[str, float]] = None,
        risk_tolerance: str = "medium",  # "low", "medium", "high"
    ) -> Dict[str, Any]:
        """
        基于置信度选择价格

        Args:
            thresholds: 三档价格阈值
            overall_confidence: 整体置信度
            confidence_breakdown: 各维度置信度
            risk_tolerance: 风险容忍度

        Returns:
            {
                "selected_price": float,
                "selected_tier": str,
                "confidence": float,
                "reasoning": str,
            }
        """
        # 根据风险容忍度调整置信度阈值
        if risk_tolerance == "low":
            # 风险厌恶，使用更高置信度要求
            adjusted_high = min(0.9, self.confidence_threshold_high + 0.1)
            adjusted_low = min(0.7, self.confidence_threshold_low + 0.2)
        elif risk_tolerance == "high":
            # 风险偏好，降低置信度要求
            adjusted_high = max(0.6, self.confidence_threshold_high - 0.2)
            adjusted_low = max(0.3, self.confidence_threshold_low - 0.2)
        else:
            adjusted_high = self.confidence_threshold_high
            adjusted_low = self.confidence_threshold_low

        # 基于置信度选择档位
        if overall_confidence >= adjusted_high:
            selected_price = thresholds.conservative
            selected_tier = "conservative"
            reasoning = (
                f"高置信度({overall_confidence:.2f})支持保守定价，"
                "建议采用溢价策略最大化收益"
            )
        elif overall_confidence >= adjusted_low:
            selected_price = thresholds.moderate
            selected_tier = "moderate"
            reasoning = (
                f"中等置信度({overall_confidence:.2f})，"
                "建议采用公允价值定价平衡风险收益"
            )
        else:
            selected_price = thresholds.aggressive
            selected_tier = "aggressive"
            reasoning = (
                f"低置信度({overall_confidence:.2f})，"
                "建议采用激进定价快速成交降低不确定性"
            )

        return {
            "selected_price": selected_price,
            "selected_tier": selected_tier,
            "confidence": overall_confidence,
            "reasoning": reasoning,
            "all_tiers": {
                "conservative": thresholds.conservative,
                "moderate": thresholds.moderate,
                "aggressive": thresholds.aggressive,
            },
        }

    def calculate_dynamic_weight(
        self,
        confidence_breakdown: Dict[str, float],
    ) -> Dict[str, float]:
        """
        基于各维度置信度计算动态权重

        置信度越高的维度权重越大
        """
        # 特征维度重要性
        base_weights = {
            "graph": 0.30,
            "lineage": 0.25,
            "quality": 0.20,
            "market": 0.15,
            "rights": 0.10,
        }

        # 根据置信度调整权重
        adjusted_weights = {}
        total_weight = 0

        for feature, base_w in base_weights.items():
            conf = confidence_breakdown.get(feature, 0.5)
            # 置信度低的特征降低权重
            adjusted_w = base_w * (0.5 + 0.5 * conf)
            adjusted_weights[feature] = adjusted_w
            total_weight += adjusted_w

        # 归一化
        for feature in adjusted_weights:
            adjusted_weights[feature] /= total_weight

        return adjusted_weights


class ThreeTierPriceGenerator:
    """
    三档价格生成器

    整合分布估计和置信度选择，生成最终的三档定价
    """

    def __init__(
        self,
        estimator: Optional[PriceDistributionEstimator] = None,
        selector: Optional[ConfidenceBasedSelector] = None,
    ):
        self.estimator = estimator or PriceDistributionEstimator()
        self.selector = selector or ConfidenceBasedSelector()

    async def generate(
        self,
        asset_id: str,
        comparable_transactions: List[Dict[str, Any]],
        confidence_scores: Dict[str, float],
        base_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        生成三档价格

        Args:
            asset_id: 资产ID
            comparable_transactions: 可比交易
            confidence_scores: 各维度置信度
            base_price: 基础价格（可选）

        Returns:
            完整的价格建议
        """
        # 1. 拟合价格分布
        if comparable_transactions:
            thresholds = self.estimator.fit_with_features(
                comparable_transactions
            )
        elif base_price:
            # 基于基础价格构造阈值
            thresholds = self._thresholds_from_base(base_price)
        else:
            thresholds = self.estimator._default_thresholds()

        # 2. 计算整体置信度
        overall_confidence = self._calculate_overall_confidence(confidence_scores)

        # 3. 基于置信度选择价格
        selection = self.selector.select_price(
            thresholds,
            overall_confidence,
            confidence_scores,
        )

        # 4. 计算价格调整建议
        adjustments = self._calculate_adjustments(
            thresholds, confidence_scores
        )

        return {
            "asset_id": asset_id,
            "thresholds": thresholds.to_dict(),
            "selection": selection,
            "confidence": {
                "overall": overall_confidence,
                "breakdown": confidence_scores,
            },
            "adjustments": adjustments,
            "recommendations": self._generate_recommendations(
                thresholds, selection, confidence_scores
            ),
        }

    def _thresholds_from_base(self, base_price: float) -> PriceThresholds:
        """基于基础价格构造阈值"""
        # 假设对数正态分布，sigma=0.3
        sigma = 0.3
        mu = np.log(base_price)

        p10 = np.exp(mu - 1.28 * sigma)
        p50 = base_price
        p90 = np.exp(mu + 1.28 * sigma)

        return PriceThresholds(
            conservative=float(p90),
            moderate=float(p50),
            aggressive=float(p10),
            distribution_type=PriceDistributionType.LOGNORMAL,
            distribution_params={"mu": mu, "sigma": sigma},
            sample_size=1,
            goodness_of_fit=0.5,
        )

    def _calculate_overall_confidence(
        self,
        confidence_scores: Dict[str, float],
    ) -> float:
        """计算整体置信度"""
        if not confidence_scores:
            return 0.5

        # 加权平均
        weights = {
            "graph": 0.30,
            "lineage": 0.25,
            "quality": 0.20,
            "market": 0.15,
            "rights": 0.10,
        }

        total_weight = 0
        weighted_sum = 0

        for feature, conf in confidence_scores.items():
            weight = weights.get(feature, 0.1)
            weighted_sum += conf * weight
            total_weight += weight

        overall = weighted_sum / total_weight if total_weight > 0 else 0.5
        return min(1.0, max(0.0, overall))

    def _calculate_adjustments(
        self,
        thresholds: PriceThresholds,
        confidence_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """计算价格调整因子"""
        adjustments = {}

        # 基于血缘质量调整
        lineage_conf = confidence_scores.get("lineage", 0.5)
        if lineage_conf > 0.8:
            adjustments["lineage_premium"] = 0.05
        elif lineage_conf < 0.4:
            adjustments["lineage_discount"] = -0.10

        # 基于市场置信度调整
        market_conf = confidence_scores.get("market", 0.5)
        if market_conf < 0.3:
            adjustments["market_uncertainty_discount"] = -0.05

        # 综合调整
        total_adjustment = sum(adjustments.values())
        adjustments["total"] = total_adjustment

        return adjustments

    def _generate_recommendations(
        self,
        thresholds: PriceThresholds,
        selection: Dict[str, Any],
        confidence_scores: Dict[str, float],
    ) -> List[str]:
        """生成定价建议"""
        recommendations = []

        # 基于分布特征的建议
        if thresholds.distribution_type == PriceDistributionType.LOGNORMAL:
            sigma = thresholds.distribution_params.get("sigma", 0.5)
            if sigma > 0.5:
                recommendations.append(
                    "价格分布离散度较高，建议采用保守策略降低风险"
                )
            elif sigma < 0.3:
                recommendations.append(
                    "价格分布较为集中，可以采用积极定价策略"
                )

        # 基于置信度的建议
        low_conf_features = [
            f for f, c in confidence_scores.items() if c < 0.5
        ]
        if low_conf_features:
            recommendations.append(
                f"以下维度置信度较低，建议收集更多数据: {', '.join(low_conf_features)}"
            )

        # 基于样本量的建议
        if thresholds.sample_size < 5:
            recommendations.append(
                "历史交易数据不足，建议参考可比资产或采用成本加成法"
            )

        return recommendations
