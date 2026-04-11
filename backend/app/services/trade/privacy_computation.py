"""
Privacy Computation Service - 隐私计算协议协商与脱敏分级

Phase 2: 实现隐私计算方法协商、脱敏处理和数据安全
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.data_rights_events import (
    ComputationMethod,
    DataSensitivityLevel,
    AnonymizationLevel,
    ComputationAgreementPayload,
)

logger = logging.getLogger(__name__)


@dataclass
class ComputationMethodProfile:
    """隐私计算方法配置文件"""
    method: ComputationMethod
    data_exposure: str  # none, encrypted, aggregated
    precision: str      # exact, high, noisy
    overhead: str       # low, medium, high, very_high
    trust_requirement: str  # low, medium, high
    description: str
    use_cases: List[str]


@dataclass
class PrivacyRequirement:
    """隐私需求"""
    min_protection_level: int  # 1-4
    required_precision: str    # exact, high, medium
    max_computation_cost: Optional[float] = None
    latency_sensitive: bool = False


class PrivacyComputationNegotiator:
    """
    隐私计算协议协商器

    根据数据敏感度和买方需求，选择最合适的隐私计算方法
    """

    # 方法配置文件
    METHOD_PROFILES = {
        ComputationMethod.MULTI_PARTY_COMPUTATION: ComputationMethodProfile(
            method=ComputationMethod.MULTI_PARTY_COMPUTATION,
            data_exposure="none",
            precision="exact",
            overhead="very_high",
            trust_requirement="low",
            description="多方安全计算，多方在不暴露原始数据的情况下共同计算",
            use_cases=["金融风控", "医疗联合研究", "跨机构统计"],
        ),
        ComputationMethod.TEE: ComputationMethodProfile(
            method=ComputationMethod.TEE,
            data_exposure="encrypted",
            precision="exact",
            overhead="medium",
            trust_requirement="high",
            description="可信执行环境，在硬件隔离环境中处理加密数据",
            use_cases=["敏感数据处理", "模型训练", "实时计算"],
        ),
        ComputationMethod.FEDERATED_LEARNING: ComputationMethodProfile(
            method=ComputationMethod.FEDERATED_LEARNING,
            data_exposure="none",
            precision="high",
            overhead="high",
            trust_requirement="medium",
            description="联邦学习，多方共同训练模型而数据不出本地",
            use_cases=["分布式AI训练", "隐私保护建模", "跨设备学习"],
        ),
        ComputationMethod.DIFFERENTIAL_PRIVACY: ComputationMethodProfile(
            method=ComputationMethod.DIFFERENTIAL_PRIVACY,
            data_exposure="aggregated",
            precision="noisy",
            overhead="low",
            trust_requirement="low",
            description="差分隐私，向查询结果添加噪声保护个体隐私",
            use_cases=["统计发布", "聚合查询", "公开数据集生成"],
        ),
        ComputationMethod.RAW_DATA: ComputationMethodProfile(
            method=ComputationMethod.RAW_DATA,
            data_exposure="raw",
            precision="exact",
            overhead="low",
            trust_requirement="high",
            description="原始数据访问，仅在高度信任环境下使用",
            use_cases=["内部数据分析", "调试测试"],
        ),
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def negotiate_protocol(
        self,
        asset_id: str,
        data_sensitivity: DataSensitivityLevel,
        buyer_requirements: PrivacyRequirement,
    ) -> ComputationAgreementPayload:
        """
        协商隐私计算协议

        Args:
            asset_id: 数据资产ID
            data_sensitivity: 数据敏感度
            buyer_requirements: 买方隐私需求

        Returns:
            ComputationAgreementPayload: 协商后的协议
        """
        # 验证敏感度与方法的兼容性
        allowed_methods = self._get_allowed_methods(data_sensitivity)

        if not allowed_methods:
            raise ServiceError(
                400,
                f"No computation methods allowed for sensitivity level: {data_sensitivity}"
            )

        # 评分并排序
        method_scores = []
        for method in allowed_methods:
            profile = self.METHOD_PROFILES[method]
            score = self._score_method(profile, data_sensitivity, buyer_requirements)
            method_scores.append((method, profile, score))

        # 按评分排序
        method_scores.sort(key=lambda x: x[2], reverse=True)
        selected_method, selected_profile, _ = method_scores[0]

        # 生成约束条件
        constraints = self._generate_constraints(
            selected_method,
            data_sensitivity,
            buyer_requirements,
        )

        # 确定验证机制
        verification = self._get_verification_mechanism(selected_method)

        # 成本分摊（默认买方70%，卖方30%）
        cost_allocation = self._calculate_cost_allocation(
            selected_method,
            buyer_requirements,
        )

        # 生成协议
        agreement = ComputationAgreementPayload(
            negotiation_id=f"negotiation_placeholder",  # 应由上层填充
            computation_method=selected_method,
            constraints=constraints,
            verification_mechanism=verification,
            cost_allocation=cost_allocation,
        )

        logger.info(
            f"Negotiated protocol for {asset_id}: "
            f"method={selected_method.value}, "
            f"constraints={constraints}"
        )

        return agreement

    def _get_allowed_methods(
        self,
        sensitivity: DataSensitivityLevel,
    ) -> List[ComputationMethod]:
        """获取指定敏感度下允许的计算方法"""
        if sensitivity == DataSensitivityLevel.LOW:
            return [
                ComputationMethod.RAW_DATA,
                ComputationMethod.DIFFERENTIAL_PRIVACY,
                ComputationMethod.TEE,
                ComputationMethod.FEDERATED_LEARNING,
                ComputationMethod.MULTI_PARTY_COMPUTATION,
            ]
        elif sensitivity == DataSensitivityLevel.MEDIUM:
            return [
                ComputationMethod.DIFFERENTIAL_PRIVACY,
                ComputationMethod.TEE,
                ComputationMethod.FEDERATED_LEARNING,
                ComputationMethod.MULTI_PARTY_COMPUTATION,
            ]
        elif sensitivity == DataSensitivityLevel.HIGH:
            return [
                ComputationMethod.TEE,
                ComputationMethod.FEDERATED_LEARNING,
                ComputationMethod.MULTI_PARTY_COMPUTATION,
            ]
        elif sensitivity == DataSensitivityLevel.CRITICAL:
            return [
                ComputationMethod.MULTI_PARTY_COMPUTATION,
            ]
        else:
            return []

    def _score_method(
        self,
        profile: ComputationMethodProfile,
        sensitivity: DataSensitivityLevel,
        requirements: PrivacyRequirement,
    ) -> float:
        """
        为计算方法评分

        评分维度：
        1. 隐私保护强度（权重40%）
        2. 精度匹配度（权重30%）
        3. 成本效率（权重20%）
        4. 信任要求（权重10%）
        """
        score = 0.0

        # 1. 隐私保护强度评分
        exposure_scores = {
            "none": 100,
            "encrypted": 80,
            "aggregated": 60,
            "raw": 20,
        }
        privacy_score = exposure_scores.get(profile.data_exposure, 0)

        # 根据敏感度调整隐私要求
        if sensitivity in [DataSensitivityLevel.HIGH, DataSensitivityLevel.CRITICAL]:
            if profile.data_exposure != "none":
                privacy_score *= 0.5  # 高敏感度必须无暴露

        score += privacy_score * 0.4

        # 2. 精度匹配度评分
        precision_scores = {
            "exact": 100,
            "high": 85,
            "noisy": 50,
        }
        required_precision_scores = {
            "exact": {"exact": 100, "high": 60, "noisy": 20},
            "high": {"exact": 90, "high": 100, "noisy": 50},
            "medium": {"exact": 70, "high": 85, "noisy": 100},
        }
        precision_score = required_precision_scores.get(
            requirements.required_precision, {}
        ).get(profile.precision, 50)
        score += precision_score * 0.3

        # 3. 成本效率评分
        overhead_scores = {
            "low": 100,
            "medium": 70,
            "high": 40,
            "very_high": 20,
        }
        cost_score = overhead_scores.get(profile.overhead, 0)
        score += cost_score * 0.2

        # 4. 信任要求评分（越低越好）
        trust_scores = {
            "low": 100,
            "medium": 70,
            "high": 40,
        }
        trust_score = trust_scores.get(profile.trust_requirement, 0)
        score += trust_score * 0.1

        return score

    def _generate_constraints(
        self,
        method: ComputationMethod,
        sensitivity: DataSensitivityLevel,
        requirements: PrivacyRequirement,
    ) -> Dict[str, Any]:
        """生成计算约束"""
        constraints = {}

        if method == ComputationMethod.DIFFERENTIAL_PRIVACY:
            # 根据敏感度设置 epsilon
            if sensitivity == DataSensitivityLevel.CRITICAL:
                constraints["epsilon"] = 0.1
            elif sensitivity == DataSensitivityLevel.HIGH:
                constraints["epsilon"] = 0.5
            elif sensitivity == DataSensitivityLevel.MEDIUM:
                constraints["epsilon"] = 1.0
            else:
                constraints["epsilon"] = 2.0

            constraints["delta"] = 1e-5
            constraints["noise_mechanism"] = "gaussian"

        elif method == ComputationMethod.MULTI_PARTY_COMPUTATION:
            constraints["min_participants"] = 2
            constraints["corruption_threshold"] = 1  # 容忍的腐败方数量
            constraints["protocol"] = "SPDZ"  # 或 "BGW", "GMW"

        elif method == ComputationMethod.TEE:
            constraints["attestation_required"] = True
            constraints["secure_boot"] = True
            constraints["min_tee_version"] = "v2.0"
            constraints["allowed_platforms"] = ["Intel_SGX", "ARM_TrustZone", "AWS_Nitro"]

        elif method == ComputationMethod.FEDERATED_LEARNING:
            constraints["min_clients"] = 3
            constraints["aggregation_algorithm"] = "FedAvg"
            constraints["local_epochs"] = 5
            constraints["secure_aggregation"] = True

        elif method == ComputationMethod.RAW_DATA:
            # 严格限制
            constraints["max_access_duration"] = 3600  # 1小时
            constraints["audit_level"] = "comprehensive"
            constraints["require_approval"] = True

        return constraints

    def _get_verification_mechanism(self, method: ComputationMethod) -> str:
        """获取验证机制"""
        verification_map = {
            ComputationMethod.TEE: "tee_attestation",
            ComputationMethod.MULTI_PARTY_COMPUTATION: "protocol_verification",
            ComputationMethod.FEDERATED_LEARNING: "secure_aggregation_audit",
            ComputationMethod.DIFFERENTIAL_PRIVACY: "noise_verification",
            ComputationMethod.RAW_DATA: "comprehensive_audit",
        }
        return verification_map.get(method, "third_party_audit")

    def _calculate_cost_allocation(
        self,
        method: ComputationMethod,
        requirements: PrivacyRequirement,
    ) -> Dict[str, float]:
        """计算成本分摊"""
        # 基础分摊比例
        base_allocation = {"buyer": 0.7, "seller": 0.3}

        # 高成本方法，买方承担更多
        high_cost_methods = [
            ComputationMethod.MULTI_PARTY_COMPUTATION,
            ComputationMethod.FEDERATED_LEARNING,
        ]

        if method in high_cost_methods:
            base_allocation = {"buyer": 0.8, "seller": 0.2}

        return base_allocation


class AnonymizationService:
    """
    脱敏服务

    根据脱敏级别对数据进行匿名化处理
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def anonymize_data(
        self,
        data: List[Dict[str, Any]],
        level: AnonymizationLevel,
        sensitive_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        对数据进行脱敏处理

        Args:
            data: 原始数据
            level: 脱敏级别
            sensitive_fields: 敏感字段列表

        Returns:
            脱敏后的数据
        """
        if level == AnonymizationLevel.L1_RAW:
            return data

        elif level == AnonymizationLevel.L2_PSEUDONYMIZED:
            return await self._apply_pseudonymization(data, sensitive_fields)

        elif level == AnonymizationLevel.L3_K_ANONYMITY:
            return await self._apply_k_anonymity(data, sensitive_fields)

        elif level == AnonymizationLevel.L4_DIFFERENTIAL:
            return await self._apply_differential_privacy(data)

        else:
            raise ServiceError(400, f"Invalid anonymization level: {level}")

    async def _apply_pseudonymization(
        self,
        data: List[Dict],
        sensitive_fields: Optional[List[str]],
    ) -> List[Dict]:
        """
        L2: 假名化处理

        替换直接标识符为假名
        """
        import hashlib

        if not sensitive_fields:
            sensitive_fields = ["name", "email", "phone", "id_number"]

        result = []
        for record in data:
            anonymized = record.copy()
            for field in sensitive_fields:
                if field in anonymized and anonymized[field]:
                    # 使用哈希生成假名
                    original = str(anonymized[field])
                    pseudonym = f"PSEUDO_{hashlib.sha256(original.encode()).hexdigest()[:12]}"
                    anonymized[field] = pseudonym
            result.append(anonymized)

        return result

    async def _apply_k_anonymity(
        self,
        data: List[Dict],
        sensitive_fields: Optional[List[str]],
        k: int = 5,
    ) -> List[Dict]:
        """
        L3: K-匿名处理

        对数据进行泛化和抑制，确保每条记录至少与 k-1 条记录不可区分
        """
        # 简化的 K-匿名实现
        # 实际生产环境应使用专业库如: anonymity, ARX

        if not data:
            return data

        # 识别准标识符（用于分组的字段）
        quasi_identifiers = sensitive_fields or ["age", "zip_code", "gender"]

        # 泛化数值字段
        result = []
        for record in data:
            generalized = record.copy()

            # 年龄泛化到年龄段
            if "age" in generalized and generalized["age"]:
                age = generalized["age"]
                if isinstance(age, (int, float)):
                    generalized["age"] = f"{age // 10 * 10}-{age // 10 * 10 + 9}"

            # 邮编泛化
            if "zip_code" in generalized and generalized["zip_code"]:
                zip_code = str(generalized["zip_code"])
                generalized["zip_code"] = zip_code[:3] + "**"

            result.append(generalized)

        return result

    async def _apply_differential_privacy(
        self,
        data: List[Dict],
        epsilon: float = 1.0,
    ) -> List[Dict]:
        """
        L4: 差分隐私处理

        向聚合结果添加噪声
        """
        import random

        # 注意：这是简化实现
        # 实际应使用专业库如: diffpriv, Google's DP Library

        if not data:
            return data

        # 对于数值字段添加拉普拉斯噪声
        result = []
        for record in data:
            noisy_record = record.copy()

            for key, value in noisy_record.items():
                if isinstance(value, (int, float)):
                    # 添加拉普拉斯噪声
                    scale = 1.0 / epsilon
                    noise = random.choice([-1, 1]) * random.random() * scale
                    noisy_record[key] = value + noise

            result.append(noisy_record)

        return result

    def get_anonymization_requirements(
        self,
        sensitivity: DataSensitivityLevel,
    ) -> AnonymizationLevel:
        """根据敏感度获取默认脱敏级别"""
        mapping = {
            DataSensitivityLevel.LOW: AnonymizationLevel.L2_PSEUDONYMIZED,
            DataSensitivityLevel.MEDIUM: AnonymizationLevel.L3_K_ANONYMITY,
            DataSensitivityLevel.HIGH: AnonymizationLevel.L4_DIFFERENTIAL,
            DataSensitivityLevel.CRITICAL: AnonymizationLevel.L4_DIFFERENTIAL,
        }
        return mapping.get(sensitivity, AnonymizationLevel.L2_PSEUDONYMIZED)
