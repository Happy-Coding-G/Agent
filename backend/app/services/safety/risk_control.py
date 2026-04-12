"""
Risk Control Service - 风险控制服务

提供价格异常检测、风险评估、市场风控等功能
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.db.models import TradeListings, TradeOrders, TradeMarketListings
from app.services.pricing.pricing_service import UnifiedPricingService
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """风险等级"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskType(str, Enum):
    """风险类型"""
    PRICE_TOO_LOW = "price_too_low"           # 价格过低
    PRICE_TOO_HIGH = "price_too_high"         # 价格过高
    PRICE_VOLATILITY = "price_volatility"     # 价格波动过大
    DEVIATION_FROM_ESTIMATE = "deviation"     # 偏离定价建议
    SUSPICIOUS_PATTERN = "suspicious"         # 可疑模式
    MARKET_MANIPULATION = "manipulation"      # 市场操纵
    LIQUIDITY_RISK = "liquidity"              # 流动性风险


@dataclass
class Risk:
    """单个风险项"""
    type: RiskType
    level: RiskLevel
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskAssessment:
    """风险评估结果"""
    passed: bool
    overall_risk: RiskLevel
    risks: List[Risk] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.risks:
            self.risks = []
        if not self.suggestions:
            self.suggestions = []
        if not self.metadata:
            self.metadata = {}


class PriceRiskControl:
    """
    价格风险控制服务

    检测价格异常：
    1. 与定价建议对比
    2. 与市场均价对比
    3. 价格波动率检查
    4. 可疑交易模式检测
    """

    # 风险阈值配置
    DEVIATION_WARNING = 0.3      # 30%偏差警告
    DEVIATION_CRITICAL = 0.5     # 50%偏差严重
    VOLATILITY_THRESHOLD = 0.5   # 50%波动率阈值
    PRICE_SPIKE_RATIO = 2.0      # 价格暴涨倍数
    PRICE_DROP_RATIO = 0.5       # 价格暴跌比例

    def __init__(self, db: AsyncSession):
        self.db = db
        self.pricing_service = UnifiedPricingService(db)

    async def validate_listing_price(
        self,
        asset_id: str,
        listing_price: float,
        category: Optional[str] = None,
    ) -> RiskAssessment:
        """
        验证上架价格

        Args:
            asset_id: 资产ID
            listing_price: 上架价格（元）
            category: 资产类别

        Returns:
            RiskAssessment
        """
        risks = []
        suggestions = []

        # 1. 与定价建议对比
        pricing_risks = await self._check_pricing_estimate(asset_id, listing_price)
        risks.extend(pricing_risks)

        # 2. 与市场均价对比
        if category:
            market_risks = await self._check_market_average(category, listing_price)
            risks.extend(market_risks)

        # 3. 价格合理性检查
        if listing_price <= 0:
            risks.append(Risk(
                type=RiskType.PRICE_TOO_LOW,
                level=RiskLevel.CRITICAL,
                message="Price must be greater than 0",
                details={"price": listing_price}
            ))

        if listing_price > 1000000:  # 超过100万
            risks.append(Risk(
                type=RiskType.PRICE_TOO_HIGH,
                level=RiskLevel.HIGH,
                message="Price exceeds 1,000,000 - manual review required",
                details={"price": listing_price}
            ))
            suggestions.append("High-value listing requires additional verification")

        # 4. 评估整体风险
        overall_risk = self._calculate_overall_risk(risks)
        passed = overall_risk not in [RiskLevel.HIGH, RiskLevel.CRITICAL]

        return RiskAssessment(
            passed=passed,
            overall_risk=overall_risk,
            risks=risks,
            suggestions=suggestions,
            metadata={
                "asset_id": asset_id,
                "listing_price": listing_price,
                "category": category,
            }
        )

    async def validate_negotiation_price(
        self,
        negotiation_id: str,
        proposed_price: float,
        original_price: float,
        listing_id: str,
    ) -> RiskAssessment:
        """
        验证协商价格

        Args:
            negotiation_id: 协商ID
            proposed_price: 提议价格
            original_price: 原始价格
            listing_id: 上架ID

        Returns:
            RiskAssessment
        """
        risks = []
        suggestions = []

        # 1. 价格变动比例检查
        if original_price > 0:
            change_ratio = abs(proposed_price - original_price) / original_price

            if change_ratio > self.DEVIATION_CRITICAL:
                risks.append(Risk(
                    type=RiskType.DEVIATION_FROM_ESTIMATE,
                    level=RiskLevel.HIGH,
                    message=f"Price deviation too large ({change_ratio:.1%})",
                    details={
                        "original": original_price,
                        "proposed": proposed_price,
                        "change_ratio": change_ratio,
                    }
                ))
                suggestions.append("Large price deviation requires approval")

            elif change_ratio > self.DEVIATION_WARNING:
                risks.append(Risk(
                    type=RiskType.DEVIATION_FROM_ESTIMATE,
                    level=RiskLevel.MEDIUM,
                    message=f"Significant price deviation ({change_ratio:.1%})",
                    details={
                        "original": original_price,
                        "proposed": proposed_price,
                        "change_ratio": change_ratio,
                    }
                ))

        # 2. 获取上架信息进行更详细检查
        listing = await self._get_listing(listing_id)
        if listing:
            # 检查是否低于底价
            if hasattr(listing, 'reserve_price') and listing.reserve_price:
                if proposed_price < listing.reserve_price:
                    risks.append(Risk(
                        type=RiskType.PRICE_TOO_LOW,
                        level=RiskLevel.HIGH,
                        message=f"Price below seller's reserve price",
                        details={
                            "proposed": proposed_price,
                            "reserve": listing.reserve_price,
                        }
                    ))

        # 3. 检查价格波动（历史数据）
        volatility_risks = await self._check_price_volatility(listing_id, proposed_price)
        risks.extend(volatility_risks)

        overall_risk = self._calculate_overall_risk(risks)
        passed = overall_risk not in [RiskLevel.CRITICAL]

        return RiskAssessment(
            passed=passed,
            overall_risk=overall_risk,
            risks=risks,
            suggestions=suggestions,
            metadata={
                "negotiation_id": negotiation_id,
                "proposed_price": proposed_price,
                "original_price": original_price,
            }
        )

    async def _check_pricing_estimate(
        self,
        asset_id: str,
        listing_price: float,
    ) -> List[Risk]:
        """与定价建议对比"""
        risks = []

        try:
            pricing = await self.pricing_service.calculate_price(asset_id)

            if not pricing:
                return risks

            # 与保守价格对比
            if pricing.conservative_price > 0:
                if listing_price < pricing.conservative_price * 0.5:
                    risks.append(Risk(
                        type=RiskType.PRICE_TOO_LOW,
                        level=RiskLevel.HIGH,
                        message=f"Price is 50% below conservative estimate",
                        details={
                            "listing_price": listing_price,
                            "conservative": pricing.conservative_price,
                            "ratio": listing_price / pricing.conservative_price,
                        }
                    ))

            # 与激进价格对比
            if pricing.aggressive_price > 0:
                if listing_price > pricing.aggressive_price * 2:
                    risks.append(Risk(
                        type=RiskType.PRICE_TOO_HIGH,
                        level=RiskLevel.MEDIUM,
                        message=f"Price is 2x above aggressive estimate",
                        details={
                            "listing_price": listing_price,
                            "aggressive": pricing.aggressive_price,
                            "ratio": listing_price / pricing.aggressive_price,
                        }
                    ))

        except Exception as e:
            logger.warning(f"Failed to get pricing estimate: {e}")

        return risks

    async def _check_market_average(
        self,
        category: str,
        listing_price: float,
    ) -> List[Risk]:
        """与市场均价对比"""
        risks = []

        try:
            market_avg = await self._get_market_average(category)

            if market_avg <= 0:
                return risks

            ratio = listing_price / market_avg

            if ratio > self.PRICE_SPIKE_RATIO:
                risks.append(Risk(
                    type=RiskType.PRICE_TOO_HIGH,
                    level=RiskLevel.MEDIUM,
                    message=f"Price is {ratio:.1f}x above market average",
                    details={
                        "listing_price": listing_price,
                        "market_average": market_avg,
                        "ratio": ratio,
                    }
                ))
            elif ratio < self.PRICE_DROP_RATIO:
                risks.append(Risk(
                    type=RiskType.PRICE_TOO_LOW,
                    level=RiskLevel.MEDIUM,
                    message=f"Price is {ratio:.1%} of market average",
                    details={
                        "listing_price": listing_price,
                        "market_average": market_avg,
                        "ratio": ratio,
                    }
                ))

        except Exception as e:
            logger.warning(f"Failed to get market average: {e}")

        return risks

    async def _check_price_volatility(
        self,
        listing_id: str,
        proposed_price: float,
    ) -> List[Risk]:
        """检查价格波动"""
        risks = []

        try:
            # 获取该上架的历史价格（协商历史）
            result = await self.db.execute(
                select(TradeOrders.price_credits)
                .where(TradeOrders.listing_id == listing_id)
                .order_by(TradeOrders.purchased_at.desc())
                .limit(10)
            )
            historical_prices = [row[0] / 100 for row in result.all()]  # 转换为元

            if len(historical_prices) < 2:
                return risks

            # 计算波动率
            avg_price = sum(historical_prices) / len(historical_prices)
            if avg_price > 0:
                variance = sum((p - avg_price) ** 2 for p in historical_prices) / len(historical_prices)
                std_dev = variance ** 0.5
                volatility = std_dev / avg_price

                if volatility > self.VOLATILITY_THRESHOLD:
                    risks.append(Risk(
                        type=RiskType.PRICE_VOLATILITY,
                        level=RiskLevel.MEDIUM,
                        message=f"High price volatility detected ({volatility:.1%})",
                        details={
                            "volatility": volatility,
                            "historical_avg": avg_price,
                            "proposed": proposed_price,
                        }
                    ))

        except Exception as e:
            logger.warning(f"Failed to check price volatility: {e}")

        return risks

    async def _get_market_average(self, category: str) -> float:
        """获取市场平均价格"""
        try:
            # 获取最近30天内该类别的成交平均价
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)

            result = await self.db.execute(
                select(func.avg(TradeOrders.price_credits))
                .join(TradeListings, TradeOrders.listing_id == TradeListings.listing_id)
                .where(
                    and_(
                        TradeListings.category == category,
                        TradeOrders.purchased_at >= thirty_days_ago,
                    )
                )
            )
            avg_price = result.scalar()

            return (avg_price or 0) / 100  # 转换为元

        except Exception as e:
            logger.error(f"Failed to calculate market average: {e}")
            return 0.0

    async def _get_listing(self, listing_id: str) -> Optional[TradeListings]:
        """获取上架信息"""
        try:
            result = await self.db.execute(
                select(TradeListings).where(TradeListings.listing_id == listing_id)
            )
            return result.scalar_one_or_none()
        except Exception:
            return None

    def _calculate_overall_risk(self, risks: List[Risk]) -> RiskLevel:
        """计算整体风险等级"""
        if not risks:
            return RiskLevel.NONE

        # 取最高风险等级
        level_order = [
            RiskLevel.NONE,
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ]

        max_level = RiskLevel.NONE
        for risk in risks:
            if level_order.index(risk.level) > level_order.index(max_level):
                max_level = risk.level

        return max_level

    async def get_market_analytics(
        self,
        category: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取市场分析数据

        Args:
            category: 类别筛选
            days: 天数

        Returns:
            市场分析数据
        """
        since = datetime.utcnow() - timedelta(days=days)

        query = select(
            func.count(TradeOrders.order_id).label("total_orders"),
            func.avg(TradeOrders.price_credits).label("avg_price"),
            func.min(TradeOrders.price_credits).label("min_price"),
            func.max(TradeOrders.price_credits).label("max_price"),
        ).where(TradeOrders.purchased_at >= since)

        if category:
            query = query.join(
                TradeListings,
                TradeOrders.listing_id == TradeListings.listing_id
            ).where(TradeListings.category == category)

        result = await self.db.execute(query)
        row = result.one()

        return {
            "period_days": days,
            "category": category,
            "total_orders": row.total_orders or 0,
            "average_price": (row.avg_price or 0) / 100,
            "min_price": (row.min_price or 0) / 100,
            "max_price": (row.max_price or 0) / 100,
        }


# 便捷函数
async def check_price_risk(
    db: AsyncSession,
    asset_id: str,
    price: float,
    category: Optional[str] = None,
) -> RiskAssessment:
    """
    便捷函数：检查价格风险

    Args:
        db: 数据库会话
        asset_id: 资产ID
        price: 价格
        category: 类别

    Returns:
        RiskAssessment
    """
    service = PriceRiskControl(db)
    return await service.validate_listing_price(asset_id, price, category)
