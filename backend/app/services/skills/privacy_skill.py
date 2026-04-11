"""
PrivacyComputationSkill - 隐私计算Skill

提供隐私计算协议协商、脱敏处理、敏感度评估等能力。
无状态、纯计算的Skill，可被多个Agent复用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.privacy_computation import (
    PrivacyComputationNegotiator,
    AnonymizationService,
    ComputationMethodProfile,
    PrivacyRequirement,
)
from app.services.trade.data_rights_events import (
    ComputationMethod,
    DataSensitivityLevel,
    AnonymizationLevel,
)

logger = logging.getLogger(__name__)


@dataclass
class ProtocolRecommendation:
    """协议推荐结果"""
    recommended_method: str
    method_profile: Dict[str, Any]
    score: float
    constraints: Dict[str, Any]
    verification_mechanism: str
    cost_allocation: Dict[str, float]
    reasoning: str


@dataclass
class AnonymizationResult:
    """脱敏处理结果"""
    original_count: int
    processed_count: int
    level: str
    fields_processed: List[str]
    sample_before: Optional[Dict]
    sample_after: Optional[Dict]


@dataclass
class SensitivityAssessment:
    """敏感度评估结果"""
    assessed_level: str
    confidence: float
    factors: List[str]
    recommended_anonymization: str
    risk_factors: List[str]


class PrivacyComputationSkill:
    """
    隐私计算Skill

    职责：
    1. 协商隐私计算协议
    2. 推荐合适的计算方法
    3. 执行数据脱敏
    4. 评估数据敏感度
    5. 生成隐私合规报告

    使用示例：
        skill = PrivacyComputationSkill(db)

        # 协商协议
        protocol = await skill.negotiate_protocol(
            asset_id="asset_123",
            sensitivity="high",
            requirements={"precision": "exact", "max_cost": 1000}
        )

        # 脱敏数据
        result = await skill.anonymize_data(
            data=records,
            level="k_anonymity"
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.negotiator = PrivacyComputationNegotiator(db)
        self.anonymization = AnonymizationService(db)

    # ========================================================================
    # 协议协商API
    # ========================================================================

    async def negotiate_protocol(
        self,
        asset_id: str,
        sensitivity: str,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        协商隐私计算协议

        Args:
            asset_id: 资产ID
            sensitivity: 敏感度级别 (low, medium, high, critical)
            requirements: 买方需求
                {
                    "min_protection": int (1-4),
                    "precision": str (exact, high, medium),
                    "max_cost": float,
                    "latency_sensitive": bool
                }

        Returns:
            协议详情
        """
        try:
            # 映射敏感度
            sensitivity_level = self._parse_sensitivity(sensitivity)

            # 构建需求
            req = PrivacyRequirement(
                min_protection_level=requirements.get("min_protection", 2),
                required_precision=requirements.get("precision", "high"),
                max_computation_cost=requirements.get("max_cost"),
                latency_sensitive=requirements.get("latency_sensitive", False),
            )

            # 协商协议
            agreement = await self.negotiator.negotiate_protocol(
                asset_id=asset_id,
                data_sensitivity=sensitivity_level,
                buyer_requirements=req,
            )

            # 获取方法详情
            method_profile = self.negotiator.METHOD_PROFILES.get(
                agreement.computation_method
            )

            return {
                "success": True,
                "asset_id": asset_id,
                "protocol": {
                    "method": agreement.computation_method.value,
                    "method_name": self._get_method_name(agreement.computation_method),
                    "description": method_profile.description if method_profile else "",
                    "constraints": agreement.constraints,
                    "verification_mechanism": agreement.verification_mechanism,
                    "cost_allocation": agreement.cost_allocation,
                },
                "reasoning": f"基于{sensitivity}敏感度选择{agreement.computation_method.value}",
            }

        except Exception as e:
            logger.error(f"Failed to negotiate protocol for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
                "fallback_method": "differential_privacy",
            }

    async def recommend_protocols(
        self,
        asset_id: str,
        sensitivity: str,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """
        推荐多种隐私计算协议（供选择）

        返回多个可选方案及其评分。
        """
        try:
            sensitivity_level = self._parse_sensitivity(sensitivity)

            # 获取允许的方法
            allowed_methods = self.negotiator._get_allowed_methods(sensitivity_level)

            # 为每种方法评分
            recommendations = []
            for method in allowed_methods[:top_k]:
                profile = self.negotiator.METHOD_PROFILES.get(method)
                if profile:
                    # 使用默认需求评分
                    req = PrivacyRequirement(
                        min_protection_level=2,
                        required_precision="high",
                    )
                    score = self.negotiator._score_method(
                        profile, sensitivity_level, req
                    )

                    constraints = self.negotiator._generate_constraints(
                        method, sensitivity_level, req
                    )

                    recommendations.append({
                        "method": method.value,
                        "method_name": self._get_method_name(method),
                        "score": round(score, 2),
                        "description": profile.description,
                        "data_exposure": profile.data_exposure,
                        "precision": profile.precision,
                        "overhead": profile.overhead,
                        "trust_requirement": profile.trust_requirement,
                        "constraints": constraints,
                        "use_cases": profile.use_cases,
                    })

            # 按评分排序
            recommendations.sort(key=lambda x: x["score"], reverse=True)

            return {
                "success": True,
                "asset_id": asset_id,
                "sensitivity": sensitivity,
                "recommendations": recommendations[:top_k],
                "total_options": len(allowed_methods),
            }

        except Exception as e:
            logger.error(f"Failed to recommend protocols for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
            }

    # ========================================================================
    # 脱敏处理API
    # ========================================================================

    async def anonymize_data(
        self,
        data: List[Dict[str, Any]],
        level: str,
        sensitive_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        对数据进行脱敏处理

        Args:
            data: 原始数据列表
            level: 脱敏级别 (raw, pseudonymized, k_anonymity, differential)
            sensitive_fields: 敏感字段列表

        Returns:
            脱敏结果
        """
        try:
            # 映射脱敏级别
            anon_level = self._parse_anonymization_level(level)

            # 执行脱敏
            processed_data = await self.anonymization.anonymize_data(
                data=data,
                level=anon_level,
                sensitive_fields=sensitive_fields,
            )

            # 生成样本对比
            sample_before = data[0] if data else None
            sample_after = processed_data[0] if processed_data else None

            return {
                "success": True,
                "original_count": len(data),
                "processed_count": len(processed_data),
                "level": level,
                "level_description": self._get_anonymization_description(anon_level),
                "fields_processed": sensitive_fields or ["auto-detected"],
                "sample_comparison": {
                    "before": sample_before,
                    "after": sample_after,
                },
                "data": processed_data,  # 实际返回处理后的数据
            }

        except Exception as e:
            logger.error(f"Failed to anonymize data: {e}")
            return {
                "success": False,
                "error": str(e),
                "original_count": len(data),
                "processed_count": 0,
            }

    async def assess_anonymization_needs(
        self,
        sensitivity: str,
        data_sample: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        评估脱敏需求

        根据敏感度级别推荐合适的脱敏策略。
        """
        try:
            sensitivity_level = self._parse_sensitivity(sensitivity)

            # 获取推荐的脱敏级别
            recommended_level = self.anonymization.get_anonymization_requirements(
                sensitivity_level
            )

            # 分析数据样本（如果提供）
            risk_factors = []
            if data_sample:
                # 检查直接标识符
                common_id_fields = ["name", "email", "phone", "id", "ssn"]
                if any(f in data_sample[0] for f in common_id_fields):
                    risk_factors.append("包含直接标识符")

                # 检查准标识符
                quasi_fields = ["age", "gender", "zip", "location"]
                if sum(1 for f in quasi_fields if f in data_sample[0]) >= 2:
                    risk_factors.append("包含多个准标识符")

            level_descriptions = {
                AnonymizationLevel.L1_RAW: "无需脱敏，原始数据",
                AnonymizationLevel.L2_PSEUDONYMIZED: "假名化，替换直接标识符",
                AnonymizationLevel.L3_K_ANONYMITY: "K-匿名，泛化准标识符",
                AnonymizationLevel.L4_DIFFERENTIAL: "差分隐私，添加噪声",
            }

            return {
                "success": True,
                "sensitivity": sensitivity,
                "recommended_level": recommended_level.value,
                "level_description": level_descriptions.get(
                    recommended_level, "未知"
                ),
                "risk_factors": risk_factors,
                "confidence": 0.85 if data_sample else 0.6,
            }

        except Exception as e:
            logger.error(f"Failed to assess anonymization needs: {e}")
            return {
                "success": False,
                "error": str(e),
                "recommended_level": "k_anonymity",
            }

    # ========================================================================
    # 敏感度评估API
    # ========================================================================

    async def assess_sensitivity(
        self,
        asset_id: str,
        data_sample: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        评估数据敏感度

        基于数据内容和元数据评估敏感度级别。
        """
        try:
            factors = []
            risk_factors = []

            # 基于元数据评估
            if metadata:
                data_type = metadata.get("data_type", "")
                if data_type in ["medical", "health"]:
                    factors.append("医疗健康数据")
                    assessed_level = "critical"
                elif data_type in ["financial", "banking"]:
                    factors.append("金融数据")
                    assessed_level = "high"
                elif data_type in ["personal", "behavioral"]:
                    factors.append("个人行为数据")
                    assessed_level = "medium"
                else:
                    assessed_level = "low"

                # 检查合规要求
                if metadata.get("contains_pii"):
                    risk_factors.append("包含个人身份信息")
                    if assessed_level == "low":
                        assessed_level = "medium"

                if metadata.get("regulated"):
                    factors.append("受监管数据")
                    risk_factors.append("需满足合规要求")

            # 基于样本评估
            if data_sample:
                sample = data_sample[0] if data_sample else {}

                # 检查敏感字段
                sensitive_patterns = ["password", "secret", "token", "credit_card"]
                if any(p in str(k).lower() for k in sample for p in sensitive_patterns):
                    factors.append("包含高敏感字段")
                    assessed_level = "high"

                # 检查多样性
                unique_ratio = len(set(str(v) for v in sample.values())) / len(sample) if sample else 0
                if unique_ratio > 0.8:
                    factors.append("数据多样性高")

            if not factors:
                factors.append("一般数据")
                assessed_level = "low"

            # 映射到脱敏级别
            anon_mapping = {
                "low": "pseudonymized",
                "medium": "k_anonymity",
                "high": "differential",
                "critical": "differential",
            }

            return {
                "success": True,
                "asset_id": asset_id,
                "assessed_level": assessed_level,
                "confidence": 0.75 if data_sample else 0.6,
                "factors": factors,
                "risk_factors": risk_factors,
                "recommended_anonymization": anon_mapping.get(assessed_level, "k_anonymity"),
            }

        except Exception as e:
            logger.error(f"Failed to assess sensitivity for {asset_id}: {e}")
            return {
                "success": False,
                "asset_id": asset_id,
                "error": str(e),
                "assessed_level": "medium",
            }

    # ========================================================================
    # 合规检查API
    # ========================================================================

    async def check_compliance(
        self,
        data: List[Dict[str, Any]],
        compliance_standard: str,
    ) -> Dict[str, Any]:
        """
        检查数据合规性

        Args:
            data: 数据样本
            compliance_standard: 合规标准 (GDPR, CCPA, HIPAA)

        Returns:
            合规检查结果
        """
        try:
            issues = []
            recommendations = []

            if not data:
                return {
                    "success": True,
                    "compliant": True,
                    "standard": compliance_standard,
                    "issues": [],
                }

            sample = data[0]

            # GDPR 检查
            if compliance_standard.upper() == "GDPR":
                # 检查是否有可能的直接标识符
                id_fields = ["name", "email", "phone", "address"]
                found_ids = [f for f in id_fields if f in sample]
                if found_ids:
                    issues.append(f"包含直接标识符: {found_ids}")
                    recommendations.append("建议应用假名化或K-匿名")

                # 检查敏感数据类型
                sensitive_types = ["health", "biometric", "genetic"]
                if any(t in str(sample) for t in sensitive_types):
                    issues.append("可能包含敏感个人数据")
                    recommendations.append("需要明确的数据处理依据")

            # HIPAA 检查
            elif compliance_standard.upper() == "HIPAA":
                phi_indicators = ["diagnosis", "treatment", "patient", "medical_record"]
                if any(p in str(sample).lower() for p in phi_indicators):
                    issues.append("可能包含受保护的健康信息(PHI)")
                    recommendations.append("必须进行去标识化处理")

            # CCPA 检查
            elif compliance_standard.upper() == "CCPA":
                if "consumer" in str(sample).lower() or "california" in str(sample).lower():
                    issues.append("涉及加州消费者数据")
                    recommendations.append("需提供数据披露和删除机制")

            return {
                "success": True,
                "compliant": len(issues) == 0,
                "standard": compliance_standard,
                "issues": issues,
                "recommendations": recommendations,
                "risk_level": "high" if len(issues) > 2 else "medium" if issues else "low",
            }

        except Exception as e:
            logger.error(f"Failed to check compliance: {e}")
            return {
                "success": False,
                "error": str(e),
                "compliant": False,
            }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _parse_sensitivity(self, sensitivity: str) -> DataSensitivityLevel:
        """解析敏感度字符串"""
        mapping = {
            "low": DataSensitivityLevel.LOW,
            "medium": DataSensitivityLevel.MEDIUM,
            "high": DataSensitivityLevel.HIGH,
            "critical": DataSensitivityLevel.CRITICAL,
        }
        return mapping.get(sensitivity.lower(), DataSensitivityLevel.MEDIUM)

    def _parse_anonymization_level(self, level: str) -> AnonymizationLevel:
        """解析脱敏级别字符串"""
        mapping = {
            "raw": AnonymizationLevel.L1_RAW,
            "pseudonymized": AnonymizationLevel.L2_PSEUDONYMIZED,
            "k_anonymity": AnonymizationLevel.L3_K_ANONYMITY,
            "differential": AnonymizationLevel.L4_DIFFERENTIAL,
        }
        return mapping.get(level.lower(), AnonymizationLevel.L2_PSEUDONYMIZED)

    def _get_method_name(self, method: ComputationMethod) -> str:
        """获取方法显示名称"""
        names = {
            ComputationMethod.MULTI_PARTY_COMPUTATION: "多方安全计算(MPC)",
            ComputationMethod.TEE: "可信执行环境(TEE)",
            ComputationMethod.FEDERATED_LEARNING: "联邦学习",
            ComputationMethod.DIFFERENTIAL_PRIVACY: "差分隐私",
            ComputationMethod.RAW_DATA: "原始数据访问",
        }
        return names.get(method, method.value)

    def _get_anonymization_description(self, level: AnonymizationLevel) -> str:
        """获取脱敏级别描述"""
        descriptions = {
            AnonymizationLevel.L1_RAW: "原始数据，无脱敏",
            AnonymizationLevel.L2_PSEUDONYMIZED: "L2-假名化，替换直接标识符",
            AnonymizationLevel.L3_K_ANONYMITY: "L3-K匿名，泛化准标识符",
            AnonymizationLevel.L4_DIFFERENTIAL: "L4-差分隐私，数学保证",
        }
        return descriptions.get(level, "未知级别")
