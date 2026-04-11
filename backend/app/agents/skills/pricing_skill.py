"""
PricingSkill - 数据资产定价计算Skill

提供数据资产的动态定价、价格建议、市场分析等能力。
这是一个无状态的计算Skill，可被TradeAgent或其他Agent复用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.services.trade.pricing_engine import (
    DynamicPricingEngine,
    PricingFactors,
    MarketConditions,
)
from app.services.trade.data_rights_events import (
    DataRightsPayload,
    DataRightsType,
    UsageScope,
)
from app.db.models import DataAssets
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)


@dataclass
class PriceSuggestion:
    """价格建议结果"""
    fair_value: float
    min_price: float
    recommended_price: float
    max_price: float
    currency: str
    factors: Dict[str, Any]
    confidence: float  # 0-1
    reasoning: str


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    demand_score: float  # 0-1
    competition_level: float  # 0-1
    recent_transactions: int
    average_price: Optional[float]
    price_trend: str  # up, down, stable
    similar_assets_count: int


@dataclass
class NegotiationAdvice:
    """协商建议"""
    action: str  # accept, counter, reject, wait
    suggested_price: Optional[float]
    confidence: float
    reasoning: str
    fallback_options: List[Dict[str, Any]]


class PricingSkill:
    """
    定价计算Skill

    职责：
    1. 计算数据资产的公允价格
    2. 提供价格区间建议
    3. 分析市场条件
    4. 给出协商策略建议

    使用示例：
        skill = PricingSkill(db)

        # 快速定价
        price = await skill.calculate_quick_price(asset_id, rights_types)

        # 详细定价分析
        suggestion = await skill.get_price_suggestion(
            asset_id=asset_id,
            rights_request=rights_payload,
            market_conditions=market_data
        )

        # 协商建议
        advice = await skill.advise_negotiation(
            asset_id=asset_id,
            current_offer=100.0,
            is_seller=True,
            negotiation_context=context
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.engine = DynamicPricingEngine(db)

    # ========================================================================
    # 核心定价API
    # ========================================================================

    async def calculate_quick_price(
        self,
        asset_id: str,
        rights_types: List[str],
        duration_days: int = 365,
    ) -> Dict[str, Any]:
        """
        快速定价 - 用于简单场景

        Args:
            asset_id: 资产ID
            rights_types: 权益类型列表 ["usage", "analysis", "derivative", "sub_license"]
            duration_days: 使用期限（天）

        Returns:
            {
                "fair_value": float,
                "price_range": {"min": float, "max": float},
                "currency": "CNY"
            }
        """
        try:
            # 构建权益请求
            rights_request = self._build_rights_request(rights_types, duration_days)

            # 计算公允价值
            fair_value, factors = await self.engine.calculate_fair_value(
                asset_id, rights_request
            )

            # 获取价格区间
            price_range = await self.engine.suggest_price_range(
                asset_id, rights_request
            )

            return {
                "fair_value": round(fair_value, 2),
                "price_range": {
                    "min": round(price_range["min"], 2),
                    "recommended": round(price_range["recommended"], 2),
                    "max": round(price_range["max"], 2),
                },
                "currency": "CNY",
                "factors_summary": {
                    "base_value": round(factors.base_value, 2),
                    "quality_multiplier": round(factors.quality_multiplier, 3),
                    "scarcity_multiplier": round(factors.scarcity_multiplier, 3),
                }
            }

        except ServiceError as e:
            logger.error(f"Failed to calculate price for {asset_id}: {e}")
            # 返回默认价格
            return {
                "fair_value": 100.0,
                "price_range": {"min": 80.0, "recommended": 100.0, "max": 130.0},
                "currency": "CNY",
                "error": str(e),
                "is_estimate": True,
            }

    async def get_price_suggestion(
        self,
        asset_id: str,
        rights_request: Optional[DataRightsPayload] = None,
        market_conditions: Optional[Dict[str, Any]] = None,
    ) -> PriceSuggestion:
        """
        获取详细的价格建议

        包含完整的市场分析和定价因子解释。
        """
        # 构建市场条件
        market = None
        if market_conditions:
            market = MarketConditions(
                demand_score=market_conditions.get("demand_score", 0.5),
                competition_level=market_conditions.get("competition_level", 0.5),
                recent_transactions_count=market_conditions.get("recent_transactions", 0),
                average_price=market_conditions.get("average_price"),
                price_trend=market_conditions.get("price_trend", "stable"),
            )

        # 使用默认权益请求
        if rights_request is None:
            rights_request = self._build_rights_request(
                ["usage", "analysis"], duration_days=365
            )

        # 计算价格
        fair_value, factors = await self.engine.calculate_fair_value(
            asset_id, rights_request, market
        )

        price_range = await self.engine.suggest_price_range(
            asset_id, rights_request
        )

        # 构建定价理由
        reasoning_parts = []
        if factors.quality_multiplier > 1.5:
            reasoning_parts.append("数据质量优秀")
        elif factors.quality_multiplier < 0.8:
            reasoning_parts.append("数据质量一般")

        if factors.scarcity_multiplier > 1.3:
            reasoning_parts.append("稀缺性高")

        if factors.network_value_multiplier > 1.2:
            reasoning_parts.append("网络价值高")

        reasoning = "。".join(reasoning_parts) if reasoning_parts else "基于标准定价模型"

        # 计算置信度
        confidence = self._calculate_confidence(factors)

        return PriceSuggestion(
            fair_value=round(fair_value, 2),
            min_price=round(price_range["min"], 2),
            recommended_price=round(price_range["recommended"], 2),
            max_price=round(price_range["max"], 2),
            currency="CNY",
            factors={
                "base_value": factors.base_value,
                "quality_multiplier": factors.quality_multiplier,
                "scarcity_multiplier": factors.scarcity_multiplier,
                "network_value_multiplier": factors.network_value_multiplier,
                "rights_scope_multiplier": factors.rights_scope_multiplier,
                "computation_cost": factors.computation_cost,
                "market_demand_multiplier": factors.market_demand_multiplier,
            },
            confidence=confidence,
            reasoning=reasoning,
        )

    # ========================================================================
    # 市场分析API
    # ========================================================================

    async def analyze_market(
        self,
        data_type: Optional[str] = None,
        asset_id: Optional[str] = None,
        days: int = 30,
    ) -> MarketAnalysis:
        """
        分析市场条件

        Args:
            data_type: 数据类型过滤
            asset_id: 特定资产（用于分析竞品）
            days: 统计时间范围

        Returns:
            MarketAnalysis对象
        """
        # 查询同类资产数量
        if data_type:
            stmt = select(func.count(DataAssets.id)).where(
                DataAssets.data_type == data_type,
                DataAssets.is_active == True,
            )
        else:
            stmt = select(func.count(DataAssets.id)).where(
                DataAssets.is_active == True,
            )

        result = await self.db.execute(stmt)
        total_assets = result.scalar() or 0

        # 计算竞争程度
        if total_assets <= 5:
            competition_level = 0.2
        elif total_assets <= 20:
            competition_level = 0.5
        else:
            competition_level = 0.8

        # 需求评分（简化：基于活跃资产比例）
        demand_score = min(0.9, 0.3 + (total_assets / 100))

        return MarketAnalysis(
            demand_score=demand_score,
            competition_level=competition_level,
            recent_transactions=0,  # 需从交易表查询
            average_price=None,
            price_trend="stable",
            similar_assets_count=total_assets,
        )

    async def get_comparable_prices(
        self,
        asset_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        获取可比资产的价格

        用于定价参考。
        """
        # 获取当前资产信息
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        asset = result.scalar_one_or_none()

        if not asset:
            return []

        # 查询同类型资产
        similar_stmt = (
            select(DataAssets)
            .where(
                DataAssets.data_type == asset.data_type,
                DataAssets.asset_id != asset_id,
                DataAssets.is_active == True,
                DataAssets.is_available_for_trade == True,
            )
            .order_by(DataAssets.quality_overall_score.desc())
            .limit(limit)
        )

        result = await self.db.execute(similar_stmt)
        similar_assets = result.scalars().all()

        comparables = []
        for similar in similar_assets:
            # 快速计算价格
            quick_price = await self.calculate_quick_price(
                similar.asset_id,
                rights_types=["usage"],
            )
            comparables.append({
                "asset_id": similar.asset_id,
                "asset_name": similar.asset_name,
                "data_type": similar.data_type,
                "quality_score": similar.quality_overall_score,
                "estimated_price": quick_price["fair_value"],
            })

        return comparables

    # ========================================================================
    # 协商策略API
    # ========================================================================

    async def advise_negotiation(
        self,
        asset_id: str,
        current_offer: float,
        is_seller: bool,
        negotiation_context: Optional[Dict[str, Any]] = None,
    ) -> NegotiationAdvice:
        """
        提供协商策略建议

        Args:
            asset_id: 资产ID
            current_offer: 当前报价
            is_seller: 是否为卖方
            negotiation_context: 协商上下文
                {
                    "round": int,
                    "my_previous_offers": List[float],
                    "their_previous_offers": List[float],
                    "reserve_price": float,  # 底价/天花板价
                    "deadline": datetime,
                }
        """
        context = negotiation_context or {}

        # 获取公允价格
        quick_price = await self.calculate_quick_price(
            asset_id, rights_types=["usage", "analysis"]
        )
        fair_value = quick_price["fair_value"]
        price_range = quick_price["price_range"]

        reserve_price = context.get("reserve_price",
            price_range["min"] if is_seller else price_range["max"])

        # 计算报价与公允价的比率
        if fair_value > 0:
            offer_ratio = current_offer / fair_value
        else:
            offer_ratio = 1.0

        # 根据角色和比率给出建议
        if is_seller:
            advice = self._advise_seller(
                current_offer, offer_ratio, reserve_price,
                price_range, context
            )
        else:
            advice = self._advise_buyer(
                current_offer, offer_ratio, reserve_price,
                price_range, context
            )

        return advice

    def _advise_seller(
        self,
        offer: float,
        offer_ratio: float,
        reserve_price: float,
        price_range: Dict[str, float],
        context: Dict[str, Any],
    ) -> NegotiationAdvice:
        """卖方建议"""
        round_num = context.get("round", 1)

        # 极好的报价
        if offer >= price_range["max"] * 0.95:
            return NegotiationAdvice(
                action="accept",
                suggested_price=None,
                confidence=0.9,
                reasoning=f"报价{offer}接近最高可接受价格，建议接受",
                fallback_options=[],
            )

        # 可接受的报价
        if offer >= reserve_price and offer_ratio >= 0.9:
            return NegotiationAdvice(
                action="accept" if round_num > 3 else "counter",
                suggested_price=offer * 1.05 if round_num <= 3 else None,
                confidence=0.8,
                reasoning=f"报价合理，{'可考虑小幅提升或直接接受' if round_num <= 3 else '建议接受'}",
                fallback_options=[
                    {"action": "accept", "price": offer, "confidence": 0.85}
                ] if round_num <= 3 else [],
            )

        # 偏低的报价
        if offer_ratio >= 0.7:
            counter = max(offer * 1.15, reserve_price * 1.1)
            return NegotiationAdvice(
                action="counter",
                suggested_price=round(counter, 2),
                confidence=0.75,
                reasoning="报价偏低，建议反报价",
                fallback_options=[
                    {"action": "counter", "price": round(offer * 1.08, 2), "confidence": 0.6},
                ],
            )

        # 过低的报价
        counter = max(offer * 1.25, reserve_price)
        return NegotiationAdvice(
            action="counter",
            suggested_price=round(min(counter, price_range["recommended"]), 2),
            confidence=0.6,
            reasoning="报价过低，建议明确底价立场",
            fallback_options=[
                {"action": "reject", "reason": "报价远低于预期", "confidence": 0.4},
            ],
        )

    def _advise_buyer(
        self,
        offer: float,
        offer_ratio: float,
        ceiling_price: float,
        price_range: Dict[str, float],
        context: Dict[str, Any],
    ) -> NegotiationAdvice:
        """买方建议"""
        round_num = context.get("round", 1)

        # 极好的报价（低于公允价很多）
        if offer_ratio <= 0.8:
            return NegotiationAdvice(
                action="accept",
                suggested_price=None,
                confidence=0.85,
                reasoning=f"报价{offer}低于公允价值，建议接受",
                fallback_options=[],
            )

        # 合理的报价
        if offer <= ceiling_price and offer_ratio <= 1.1:
            return NegotiationAdvice(
                action="accept" if offer_ratio <= 1.0 else "counter",
                suggested_price=offer * 0.95 if offer_ratio > 1.0 else None,
                confidence=0.75,
                reasoning="报价在合理范围内",
                fallback_options=[],
            )

        # 偏高的报价
        if offer <= ceiling_price * 1.1:
            counter = min(offer * 0.9, price_range["recommended"])
            return NegotiationAdvice(
                action="counter",
                suggested_price=round(counter, 2),
                confidence=0.7,
                reasoning="报价偏高，建议压低",
                fallback_options=[
                    {"action": "accept", "price": offer, "confidence": 0.5}
                    if round_num > 5 else None,
                ],
            )

        # 过高的报价
        return NegotiationAdvice(
            action="reject",
            suggested_price=round(price_range["recommended"], 2),
            confidence=0.6,
            reasoning="报价超出预算，建议明确天花板价",
            fallback_options=[
                {"action": "counter", "price": round(ceiling_price * 0.95, 2), "confidence": 0.4},
            ],
        )

    # ========================================================================
    # 批量定价API
    # ========================================================================

    async def batch_calculate_prices(
        self,
        asset_ids: List[str],
        rights_types: List[str],
    ) -> Dict[str, Any]:
        """
        批量计算价格

        用于资产组合定价。
        """
        results = []
        total_value = 0.0

        for asset_id in asset_ids:
            try:
                price = await self.calculate_quick_price(asset_id, rights_types)
                results.append({
                    "asset_id": asset_id,
                    "price": price["fair_value"],
                    "success": True,
                })
                total_value += price["fair_value"]
            except Exception as e:
                results.append({
                    "asset_id": asset_id,
                    "price": 0,
                    "success": False,
                    "error": str(e),
                })

        # 组合折扣
        bundle_discount = 0.1 if len(asset_ids) >= 5 else 0.05 if len(asset_ids) >= 3 else 0
        bundle_price = total_value * (1 - bundle_discount)

        return {
            "individual_prices": results,
            "total_value": round(total_value, 2),
            "bundle_discount": bundle_discount,
            "bundle_price": round(bundle_price, 2),
            "asset_count": len(asset_ids),
        }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _build_rights_request(
        self,
        rights_types: List[str],
        duration_days: int = 365,
    ) -> DataRightsPayload:
        """构建权益请求对象"""
        # 映射字符串到枚举
        type_mapping = {
            "usage": DataRightsType.USAGE_RIGHT,
            "analysis": DataRightsType.ANALYSIS_RIGHT,
            "derivative": DataRightsType.DERIVATIVE_RIGHT,
            "sub_license": DataRightsType.SUB_LICENSE_RIGHT,
        }

        rights_enum = []
        for rt in rights_types:
            if isinstance(rt, str):
                enum_val = type_mapping.get(rt.lower())
                if enum_val:
                    rights_enum.append(enum_val)
            elif isinstance(rt, DataRightsType):
                rights_enum.append(rt)

        if not rights_enum:
            rights_enum = [DataRightsType.USAGE_RIGHT]

        # 构建使用时间范围
        now = datetime.now()
        time_range = {
            "start": now.isoformat(),
            "end": (now + timedelta(days=duration_days)).isoformat(),
        }

        usage_scope = UsageScope(
            purposes=["research", "analysis"],
            time_range=time_range,
            aggregation_required=True,
            output_constraints={"max_rows": 10000},
        )

        return DataRightsPayload(
            data_asset_id="temp",  # 会在调用时被替换
            rights_types=rights_enum,
            computation_method="differential_privacy",
            usage_scope=usage_scope,
        )

    def _calculate_confidence(self, factors: PricingFactors) -> float:
        """计算定价置信度"""
        confidence = 0.7  # 基础置信度

        # 质量乘数极端值降低置信度
        if factors.quality_multiplier > 2.0 or factors.quality_multiplier < 0.5:
            confidence -= 0.1

        # 网络价值不确定
        if factors.network_value_multiplier == 1.0:
            confidence -= 0.05

        # 市场需求不确定
        if factors.market_demand_multiplier == 1.0:
            confidence -= 0.05

        return max(0.5, min(0.95, confidence))
