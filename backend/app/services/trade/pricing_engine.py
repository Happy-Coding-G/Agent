"""
Pricing Engine - 动态定价引擎与增强决策逻辑

Phase 2: 实现数据资产的动态定价和智能决策
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.services.trade.data_rights_events import (
    DataRightsPayload,
    DataRightsType,
    ComputationMethod,
    DataSensitivityLevel,
)
from app.db.models import DataAssets

logger = logging.getLogger(__name__)


@dataclass
class PricingFactors:
    """定价因子"""
    base_value: float
    quality_multiplier: float
    scarcity_multiplier: float
    network_value_multiplier: float
    rights_scope_multiplier: float
    computation_cost: float
    market_demand_multiplier: float


@dataclass
class MarketConditions:
    """市场条件"""
    demand_score: float  # 0-1
    competition_level: float  # 0-1
    recent_transactions_count: int
    average_price: Optional[float]
    price_trend: str  # up, down, stable


class DynamicPricingEngine:
    """
    动态定价引擎

    基于多因素计算数据资产的公允价值
    """

    # 基础价格参考（人民币）
    BASE_PRICE_BY_TYPE = {
        "medical": 10000.0,
        "financial": 8000.0,
        "behavioral": 5000.0,
        "location": 3000.0,
        "demographic": 2000.0,
        "generic": 1000.0,
    }

    # 权益类型价值系数
    RIGHTS_VALUE_MULTIPLIERS = {
        DataRightsType.USAGE_RIGHT: 0.3,
        DataRightsType.ANALYSIS_RIGHT: 0.5,
        DataRightsType.DERIVATIVE_RIGHT: 0.8,
        DataRightsType.SUB_LICENSE_RIGHT: 1.0,
    }

    # 敏感度折扣（越高敏感度，价格越低，因为使用限制越多）
    SENSITIVITY_DISCOUNTS = {
        DataSensitivityLevel.LOW: 1.0,
        DataSensitivityLevel.MEDIUM: 0.9,
        DataSensitivityLevel.HIGH: 0.7,
        DataSensitivityLevel.CRITICAL: 0.5,
    }

    # 计算方法成本系数
    COMPUTATION_COST_FACTORS = {
        ComputationMethod.RAW_DATA: 1.0,
        ComputationMethod.DIFFERENTIAL_PRIVACY: 1.1,
        ComputationMethod.TEE: 1.3,
        ComputationMethod.FEDERATED_LEARNING: 1.5,
        ComputationMethod.MULTI_PARTY_COMPUTATION: 2.0,
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_fair_value(
        self,
        asset_id: str,
        rights_request: DataRightsPayload,
        market_conditions: Optional[MarketConditions] = None,
    ) -> Tuple[float, PricingFactors]:
        """
        计算公允价值

        Args:
            asset_id: 数据资产ID
            rights_request: 权益请求
            market_conditions: 市场条件（可选）

        Returns:
            (fair_value, pricing_factors): 公允价值和定价因子
        """
        # 获取资产信息
        asset = await self._get_asset(asset_id)
        if not asset:
            raise ServiceError(404, f"Data asset not found: {asset_id}")

        # 1. 计算基础价值
        base_value = await self._calculate_base_value(asset)

        # 2. 质量乘数
        quality_multiplier = self._calculate_quality_multiplier(asset)

        # 3. 稀缺性乘数
        scarcity_multiplier = await self._calculate_scarcity_multiplier(asset)

        # 4. 网络价值乘数（基于知识图谱连接度）
        network_value_multiplier = await self._calculate_network_value(asset)

        # 5. 权益范围乘数
        rights_scope_multiplier = self._calculate_rights_scope_multiplier(
            rights_request
        )

        # 6. 计算成本
        computation_cost = self._calculate_computation_cost(rights_request)

        # 7. 市场需求乘数
        market_demand_multiplier = self._calculate_market_demand(
            asset, market_conditions
        )

        # 汇总定价因子
        factors = PricingFactors(
            base_value=base_value,
            quality_multiplier=quality_multiplier,
            scarcity_multiplier=scarcity_multiplier,
            network_value_multiplier=network_value_multiplier,
            rights_scope_multiplier=rights_scope_multiplier,
            computation_cost=computation_cost,
            market_demand_multiplier=market_demand_multiplier,
        )

        # 计算公允价值
        fair_value = (
            base_value *
            quality_multiplier *
            scarcity_multiplier *
            network_value_multiplier *
            rights_scope_multiplier *
            market_demand_multiplier +
            computation_cost
        )

        # 应用敏感度折扣
        sensitivity_discount = self.SENSITIVITY_DISCOUNTS.get(
            asset.sensitivity_level, 0.7
        )
        fair_value *= sensitivity_discount

        logger.info(
            f"Calculated fair value for {asset_id}: {fair_value:.2f} CNY, "
            f"factors: {factors}"
        )

        return fair_value, factors

    async def _calculate_base_value(self, asset: DataAssets) -> float:
        """计算基础价值"""
        # 根据数据类型获取基础价格
        base_price = self.BASE_PRICE_BY_TYPE.get(
            asset.data_type,
            self.BASE_PRICE_BY_TYPE["generic"]
        )

        # 根据数据量调整
        if asset.record_count and asset.record_count > 0:
            volume_factor = min(2.0, 1.0 + (asset.record_count / 100000))
        else:
            volume_factor = 1.0

        # 根据数据大小调整
        if asset.data_size_bytes and asset.data_size_bytes > 0:
            size_gb = asset.data_size_bytes / (1024 ** 3)
            size_factor = min(1.5, 1.0 + (size_gb / 10))
        else:
            size_factor = 1.0

        return base_price * volume_factor * size_factor

    def _calculate_quality_multiplier(self, asset: DataAssets) -> float:
        """计算质量乘数"""
        if asset.quality_overall_score > 0:
            # 使用已有质量评分
            quality_score = asset.quality_overall_score
        else:
            # 计算默认质量评分
            quality_score = (
                asset.quality_completeness * 0.25 +
                asset.quality_accuracy * 0.30 +
                asset.quality_timeliness * 0.20 +
                asset.quality_consistency * 0.15 +
                asset.quality_uniqueness * 0.10
            )

        # 质量评分映射到价格乘数 (0.5 - 2.0)
        return 0.5 + (quality_score * 1.5)

    async def _calculate_scarcity_multiplier(self, asset: DataAssets) -> float:
        """
        计算稀缺性乘数

        基于市场上类似数据的可获得性
        """
        # 查询同类型数据资产数量
        stmt = select(func.count(DataAssets.id)).where(
            and_(
                DataAssets.data_type == asset.data_type,
                DataAssets.is_active == True,
                DataAssets.is_available_for_trade == True,
            )
        )
        result = await self.db.execute(stmt)
        similar_assets_count = result.scalar() or 1

        # 同类资产越少，稀缺性越高
        if similar_assets_count <= 5:
            return 2.0
        elif similar_assets_count <= 20:
            return 1.5
        elif similar_assets_count <= 50:
            return 1.2
        else:
            return 1.0

    async def _calculate_network_value(self, asset: DataAssets) -> float:
        """
        计算网络价值

        基于知识图谱中的连接度
        """
        # 获取关联实体数量
        related_entities_count = len(asset.related_entities or [])

        # 连接越多，网络价值越高
        if related_entities_count >= 20:
            return 1.5
        elif related_entities_count >= 10:
            return 1.3
        elif related_entities_count >= 5:
            return 1.1
        else:
            return 1.0

    def _calculate_rights_scope_multiplier(
        self,
        rights: DataRightsPayload,
    ) -> float:
        """计算权益范围乘数"""
        multiplier = 1.0

        # 根据权益类型累加
        for right in rights.rights_types:
            multiplier += self.RIGHTS_VALUE_MULTIPLIERS.get(right, 0.1)

        # 根据使用范围调整
        usage_scope = rights.usage_scope
        if usage_scope:
            # 时间范围越长，价格越高
            if usage_scope.time_range:
                start = datetime.fromisoformat(usage_scope.time_range.get("start", ""))
                end = datetime.fromisoformat(usage_scope.time_range.get("end", ""))
                duration_days = (end - start).days if start and end else 365

                if duration_days > 365:
                    multiplier *= 1.3
                elif duration_days > 180:
                    multiplier *= 1.1

            # 用途越广，价格越高
            purposes = usage_scope.purposes or []
            if len(purposes) > 3:
                multiplier *= 1.2

        return multiplier

    def _calculate_computation_cost(self, rights: DataRightsPayload) -> float:
        """计算隐私计算成本"""
        base_cost = 500.0  # 基础计算成本
        cost_factor = self.COMPUTATION_COST_FACTORS.get(
            rights.computation_method,
            1.0
        )
        return base_cost * cost_factor

    def _calculate_market_demand(
        self,
        asset: DataAssets,
        market_conditions: Optional[MarketConditions],
    ) -> float:
        """计算市场需求乘数"""
        if not market_conditions:
            return 1.0

        # 基于市场需求调整
        demand_multiplier = 0.8 + (market_conditions.demand_score * 0.4)

        # 竞争影响
        if market_conditions.competition_level > 0.7:
            demand_multiplier *= 0.9  # 竞争激烈，价格略降

        # 价格趋势
        if market_conditions.price_trend == "up":
            demand_multiplier *= 1.1
        elif market_conditions.price_trend == "down":
            demand_multiplier *= 0.9

        return demand_multiplier

    async def suggest_price_range(
        self,
        asset_id: str,
        rights_request: DataRightsPayload,
    ) -> Dict[str, float]:
        """
        建议价格区间

        Returns:
            {
                "min": 最低可接受价格,
                "recommended": 推荐价格,
                "max": 最高可尝试价格,
            }
        """
        fair_value, factors = await self.calculate_fair_value(
            asset_id, rights_request
        )

        return {
            "min": fair_value * 0.8,
            "recommended": fair_value,
            "max": fair_value * 1.3,
            "factors": {
                "base_value": factors.base_value,
                "quality_multiplier": factors.quality_multiplier,
                "scarcity_multiplier": factors.scarcity_multiplier,
                "network_value_multiplier": factors.network_value_multiplier,
                "rights_scope_multiplier": factors.rights_scope_multiplier,
                "computation_cost": factors.computation_cost,
            },
        }

    async def _get_asset(self, asset_id: str) -> Optional[DataAssets]:
        """获取资产信息"""
        stmt = select(DataAssets).where(DataAssets.asset_id == asset_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


class EnhancedDecisionEngine:
    """
    增强决策引擎

    基于多因素的智能决策
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.pricing_engine = DynamicPricingEngine(db)

    async def evaluate_offer(
        self,
        negotiation_id: str,
        current_offer: float,
        rights_offer: DataRightsPayload,
        buyer_profile: Dict[str, Any],
        seller_constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        评估报价并给出决策建议

        Args:
            negotiation_id: 协商ID
            current_offer: 当前报价
            rights_offer: 权益报价
            buyer_profile: 买方画像
            seller_constraints: 卖方约束

        Returns:
            决策建议
        """
        asset_id = rights_offer.data_asset_id

        # 1. 计算公允价值
        fair_value, factors = await self.pricing_engine.calculate_fair_value(
            asset_id, rights_offer
        )

        # 2. 计算报价比率
        offer_ratio = current_offer / fair_value if fair_value > 0 else 0

        # 3. 评估买方信誉
        reputation_score = buyer_profile.get("reputation_score", 0.5)

        # 4. 评估隐私风险
        privacy_risk = self._assess_privacy_risk(
            rights_offer,
            buyer_profile
        )

        # 5. 评估效用损失
        utility_loss = self._assess_utility_loss(
            rights_offer,
            seller_constraints
        )

        # 6. 计算替代成本（从其他地方获取的成本）
        alternative_cost = seller_constraints.get("alternative_cost", fair_value * 0.8)

        # 综合评分
        decision_score = self._calculate_decision_score(
            offer_ratio=offer_ratio,
            reputation_score=reputation_score,
            privacy_risk=privacy_risk,
            utility_loss=utility_loss,
            alternative_cost_ratio=alternative_cost / fair_value if fair_value > 0 else 1.0,
        )

        # 决策建议
        decision = self._make_decision(
            decision_score,
            offer_ratio,
            seller_constraints
        )

        return {
            "decision": decision["action"],
            "confidence": decision["confidence"],
            "suggested_counter": decision.get("suggested_counter"),
            "reasoning": {
                "fair_value": fair_value,
                "offer_ratio": offer_ratio,
                "reputation_score": reputation_score,
                "privacy_risk": privacy_risk,
                "utility_loss": utility_loss,
                "decision_score": decision_score,
            },
            "factors": factors,
        }

    def _assess_privacy_risk(
        self,
        rights: DataRightsPayload,
        buyer_profile: Dict[str, Any],
    ) -> float:
        """
        评估隐私风险 (0-1, 越高风险越大)
        """
        risk = 0.0

        # 权益类型风险
        if DataRightsType.DERIVATIVE_RIGHT in rights.rights_types:
            risk += 0.3
        if DataRightsType.SUB_LICENSE_RIGHT in rights.rights_types:
            risk += 0.4

        # 使用范围风险
        usage_scope = rights.usage_scope
        if usage_scope:
            if not usage_scope.aggregation_required:
                risk += 0.2
            if len(usage_scope.purposes) > 5:
                risk += 0.1

        # 买方信誉风险（信誉低则风险高）
        reputation = buyer_profile.get("reputation_score", 0.5)
        risk += (1 - reputation) * 0.3

        return min(1.0, risk)

    def _assess_utility_loss(
        self,
        rights: DataRightsPayload,
        seller_constraints: Dict[str, Any],
    ) -> float:
        """
        评估效用损失 (0-1, 越高损失越大)
        """
        # 获取卖方期望保留的权益
        reserved_rights = seller_constraints.get("reserved_rights", [])

        loss = 0.0
        for right in rights.rights_types:
            if right in reserved_rights:
                loss += 0.3

        return min(1.0, loss)

    def _calculate_decision_score(
        self,
        offer_ratio: float,
        reputation_score: float,
        privacy_risk: float,
        utility_loss: float,
        alternative_cost_ratio: float,
    ) -> float:
        """计算决策评分"""
        # 价格因素 (40%)
        price_score = offer_ratio * 40

        # 信誉因素 (20%)
        reputation_component = reputation_score * 20

        # 隐私风险负向 (20%)
        privacy_component = (1 - privacy_risk) * 20

        # 效用损失负向 (10%)
        utility_component = (1 - utility_loss) * 10

        # 替代成本 (10%)
        alternative_component = (1 - alternative_cost_ratio) * 10

        return price_score + reputation_component + privacy_component + utility_component + alternative_component

    def _make_decision(
        self,
        decision_score: float,
        offer_ratio: float,
        constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """做出决策"""
        accept_threshold = constraints.get("auto_accept_threshold", 75)
        counter_threshold = constraints.get("auto_counter_threshold", 50)

        if decision_score >= accept_threshold:
            return {
                "action": "accept",
                "confidence": min(1.0, (decision_score - accept_threshold) / 25),
            }
        elif decision_score >= counter_threshold:
            # 建议反报价
            suggested_counter = self._suggest_counter_offer(
                offer_ratio,
                constraints
            )
            return {
                "action": "counter",
                "confidence": min(1.0, (decision_score - counter_threshold) / 25),
                "suggested_counter": suggested_counter,
            }
        else:
            return {
                "action": "reject",
                "confidence": min(1.0, (counter_threshold - decision_score) / 50),
            }

    def _suggest_counter_offer(
        self,
        offer_ratio: float,
        constraints: Dict[str, Any],
    ) -> float:
        """建议反报价"""
        target_ratio = constraints.get("target_price_ratio", 1.0)

        if offer_ratio < 0.6:
            # 报价过低，建议接近目标价
            return target_ratio * 0.95
        elif offer_ratio < 0.8:
            # 报价偏低，建议中间值
            return (offer_ratio + target_ratio) / 2
        else:
            # 报价接近，微调
            return target_ratio * 0.98


# Helper for type checking
and_ = None  # Will be imported when needed
