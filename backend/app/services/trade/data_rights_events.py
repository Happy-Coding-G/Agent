"""
Data Rights Events - 数据权益事件定义

Phase 1: 扩展事件类型以支持数据权益交易

定义数据权益交易相关的事件载荷模型，包括：
- 数据资产登记
- 数据权益授予
- 使用范围定义
- 计算协议达成
- 数据访问审计
- 策略违规
- 权益撤销
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, validator


# ============================================================================
# Enums - 枚举类型定义
# ============================================================================

class DataRightsType(str, Enum):
    """数据权益类型"""
    USAGE_RIGHT = "usage_right"           # 使用权
    ANALYSIS_RIGHT = "analysis_right"     # 分析权
    DERIVATIVE_RIGHT = "derivative_right" # 衍生权
    SUB_LICENSE_RIGHT = "sub_license_right"  # 再授权权


class ComputationMethod(str, Enum):
    """隐私计算方法"""
    FEDERATED_LEARNING = "federated_learning"
    MULTI_PARTY_COMPUTATION = "mpc"
    TEE = "trusted_execution_environment"
    DIFFERENTIAL_PRIVACY = "differential_privacy"
    RAW_DATA = "raw_data"  # 仅用于低敏感度数据


class DataSensitivityLevel(int, Enum):
    """数据敏感度级别"""
    LOW = 1      # 公开数据
    MEDIUM = 2   # 内部数据
    HIGH = 3     # 敏感数据
    CRITICAL = 4 # 高度敏感数据


class AnonymizationLevel(int, Enum):
    """脱敏级别"""
    L1_RAW = 1              # 原始数据（仅限低敏感度）
    L2_PSEUDONYMIZED = 2    # 假名化（去除直接标识符）
    L3_K_ANONYMITY = 3      # K-匿名（泛化、抑制）
    L4_DIFFERENTIAL = 4     # 差分隐私（添加噪声）


# ============================================================================
# Base Models - 基础模型
# ============================================================================

class UsageScope(BaseModel):
    """使用范围定义"""
    time_range: Dict[str, str] = Field(
        ...,
        description="时间范围，如 {'start': '2026-01-01', 'end': '2026-12-31'}"
    )
    purposes: List[str] = Field(
        ...,
        description="允许用途列表，如 ['research', 'commercial_analysis']"
    )
    algorithms: Optional[List[str]] = Field(
        None,
        description="允许使用的算法列表"
    )
    output_constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="输出约束，如 {'max_rows': 1000, 'aggregation_required': True}"
    )
    aggregation_required: bool = Field(
        True,
        description="是否仅允许聚合输出（禁止原始数据导出）"
    )
    geographic_restriction: Optional[List[str]] = Field(
        None,
        description="地理限制，如 ['CN', 'US']"
    )


class QualityMetrics(BaseModel):
    """数据质量指标"""
    completeness: float = Field(..., ge=0.0, le=1.0, description="完整性")
    accuracy: float = Field(..., ge=0.0, le=1.0, description="准确性")
    timeliness: float = Field(..., ge=0.0, le=1.0, description="时效性")
    consistency: float = Field(..., ge=0.0, le=1.0, description="一致性")
    uniqueness: float = Field(..., ge=0.0, le=1.0, description="唯一性")

    @property
    def overall_score(self) -> float:
        """综合质量分"""
        return (
            self.completeness * 0.25 +
            self.accuracy * 0.30 +
            self.timeliness * 0.20 +
            self.consistency * 0.15 +
            self.uniqueness * 0.10
        )


class ProcessingStep(BaseModel):
    """数据处理步骤"""
    index: int = Field(..., description="步骤序号")
    step_type: str = Field(..., description="处理类型，如 'anonymization', 'feature_extraction'")
    logic_code: str = Field(..., description="处理逻辑代码或配置")
    quality_report: Dict[str, float] = Field(default_factory=dict, description="质量报告")


# ============================================================================
# Event Payloads - 事件载荷模型
# ============================================================================

class DataAssetRegisterPayload(BaseModel):
    """数据资产登记事件载荷"""
    asset_id: str = Field(..., description="数据资产唯一标识")
    owner_id: int = Field(..., description="数据所有者ID")
    asset_name: str = Field(..., max_length=200, description="资产名称")
    asset_description: Optional[str] = Field(None, max_length=2000, description="资产描述")
    data_type: str = Field(..., description="数据类型，如 'medical', 'financial', 'behavioral'")
    sensitivity_level: DataSensitivityLevel = Field(
        ...,
        description="数据敏感度级别"
    )

    # 血缘信息
    raw_data_source: str = Field(..., description="原始数据来源")
    processing_chain: List[ProcessingStep] = Field(
        default_factory=list,
        description="数据处理链"
    )
    lineage_root: Optional[str] = Field(None, description="血缘根节点哈希")

    # 质量信息
    quality_metrics: Optional[QualityMetrics] = Field(None, description="质量指标")

    # 存储信息
    storage_location: str = Field(..., description="存储位置标识")
    data_size_bytes: int = Field(..., ge=0, description="数据大小（字节）")
    record_count: Optional[int] = Field(None, ge=0, description="记录数")

    # 关联实体
    related_entities: List[str] = Field(
        default_factory=list,
        description="关联的知识图谱实体ID列表"
    )

    @validator('sensitivity_level')
    def validate_sensitivity(cls, v):
        if v not in DataSensitivityLevel:
            raise ValueError(f"Invalid sensitivity level: {v}")
        return v


class DataRightsPayload(BaseModel):
    """数据权益授予事件载荷"""
    data_asset_id: str = Field(..., description="数据资产ID")
    rights_types: List[DataRightsType] = Field(
        ...,
        min_items=1,
        description="授予的权益类型列表"
    )
    usage_scope: UsageScope = Field(..., description="使用范围定义")
    computation_method: ComputationMethod = Field(
        ...,
        description="隐私计算方法"
    )
    anonymization_level: AnonymizationLevel = Field(
        ...,
        description="脱敏级别"
    )
    validity_period: int = Field(
        ...,
        ge=1,
        le=3650,  # 最大10年
        description="有效期（天）"
    )
    price: Optional[float] = Field(None, ge=0, description="交易价格")
    restrictions: List[str] = Field(
        default_factory=list,
        description="附加限制条款"
    )

    @validator('computation_method')
    def validate_computation_method(cls, v, values):
        """验证隐私计算方法与敏感度匹配"""
        sensitivity = values.get('sensitivity_level')
        if sensitivity and sensitivity >= DataSensitivityLevel.HIGH:
            if v == ComputationMethod.RAW_DATA:
                raise ValueError(
                    "高敏感度数据不允许使用 RAW_DATA 计算方式"
                )
        return v


class DataRightsCounterPayload(BaseModel):
    """数据权益反报价事件载荷"""
    original_rights_id: str = Field(..., description="原始权益报价ID")
    data_asset_id: str = Field(..., description="数据资产ID")

    # 可协商的字段
    requested_rights_types: List[DataRightsType] = Field(
        ...,
        description="请求的权益类型（可能比原报价更多或更少）"
    )
    proposed_usage_scope: UsageScope = Field(..., description="提议的使用范围")
    proposed_computation_method: ComputationMethod = Field(..., description="提议的隐私计算方法")
    proposed_validity_period: int = Field(..., ge=1, le=3650, description="提议的有效期")
    counter_price: Optional[float] = Field(None, ge=0, description="反报价价格")

    message: Optional[str] = Field(None, max_length=2000, description="协商消息")


class ComputationAgreementPayload(BaseModel):
    """计算协议达成事件载荷"""
    negotiation_id: str = Field(..., description="协商会话ID")
    computation_method: ComputationMethod = Field(..., description="约定的隐私计算方法")

    # 计算约束
    constraints: Dict[str, Any] = Field(
        ...,
        description="计算约束，如 {'epsilon': 0.1, 'min_participants': 3}"
    )

    # 验证机制
    verification_mechanism: str = Field(
        ...,
        description="验证机制，如 'tee_attestation', 'zk_proof', 'third_party_audit'"
    )

    # 成本分摊
    cost_allocation: Dict[str, float] = Field(
        ...,
        description="成本分摊，如 {'buyer': 0.7, 'seller': 0.3}"
    )

    # 预期计算逻辑哈希（用于完整性验证）
    expected_logic_hash: Optional[str] = Field(None, description="预期计算逻辑哈希")


class DataAccessAuditPayload(BaseModel):
    """数据访问审计事件载荷"""
    negotiation_id: str = Field(..., description="协商会话ID")
    data_asset_id: str = Field(..., description="数据资产ID")
    data_buyer: int = Field(..., description="数据买方ID")

    # 访问详情
    access_timestamp: datetime = Field(..., description="访问时间")
    access_purpose: str = Field(..., description="访问目的")
    computation_method_used: ComputationMethod = Field(..., description="实际使用的计算方法")

    # 查询信息
    query_fingerprint: str = Field(..., description="查询指纹（哈希）")
    query_complexity_score: Optional[float] = Field(None, ge=0, le=1, description="查询复杂度评分")

    # 结果信息
    result_size_bytes: int = Field(..., ge=0, description="结果大小")
    result_row_count: Optional[int] = Field(None, ge=0, description="结果行数")
    result_aggregation_level: str = Field(..., description="聚合级别")

    # 合规检查
    policy_compliance_check: Dict[str, Any] = Field(
        ...,
        description="策略合规检查结果"
    )

    # 风险评估
    risk_score: Optional[float] = Field(None, ge=0, le=1, description="风险评分")
    anomaly_flags: List[str] = Field(default_factory=list, description="异常标记")


class PolicyViolationPayload(BaseModel):
    """策略违规事件载荷"""
    negotiation_id: str = Field(..., description="协商会话ID")
    violation_type: str = Field(
        ...,
        description="违规类型，如 'EXCESSIVE_ACCESS', 'RECONSTRUCTION_ATTEMPT', 'OUTPUT_SIZE_VIOLATION'"
    )
    severity: str = Field(
        ...,
        description="严重程度：'low', 'medium', 'high', 'critical'"
    )

    # 违规详情
    violation_details: Dict[str, Any] = Field(..., description="违规详情")
    evidence: Dict[str, Any] = Field(..., description="证据")

    # 影响评估
    potential_data_exposure: Optional[float] = Field(None, ge=0, le=1, description="潜在数据泄露风险")
    affected_records_estimate: Optional[int] = Field(None, ge=0, description="估计影响记录数")

    # 响应措施
    automatic_action_taken: Optional[str] = Field(None, description="自动采取的措施")

    @validator('severity')
    def validate_severity(cls, v):
        allowed = ['low', 'medium', 'high', 'critical']
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class RightsRevokePayload(BaseModel):
    """权益撤销事件载荷"""
    negotiation_id: str = Field(..., description="协商会话ID")
    rights_id: str = Field(..., description="被撤销的权益ID")
    revoked_by: int = Field(..., description="撤销操作者ID")

    # 撤销原因
    revoke_reason: str = Field(..., description="撤销原因")
    revoke_type: str = Field(
        ...,
        description="撤销类型：'expiration'（到期）, 'breach'（违约）, 'voluntary'（自愿）, 'force_majeure'（不可抗力）"
    )

    # 结算信息
    settlement_details: Optional[Dict[str, Any]] = Field(None, description="结算详情")

    @validator('revoke_type')
    def validate_revoke_type(cls, v):
        allowed = ['expiration', 'breach', 'voluntary', 'force_majeure']
        if v not in allowed:
            raise ValueError(f"revoke_type must be one of {allowed}")
        return v


# ============================================================================
# Event Type Registry - 事件类型注册表
# ============================================================================

# 数据权益相关事件类型列表
DATA_RIGHTS_EVENT_TYPES = [
    "DATA_ASSET_REGISTER",      # 数据资产登记
    "DATA_RIGHTS_NEGOTIATION_INIT",  # 数据权益协商发起
    "DATA_RIGHTS_GRANT",        # 数据权益授予
    "DATA_RIGHTS_COUNTER",      # 数据权益反报价
    "USAGE_SCOPE_DEFINE",       # 使用范围定义
    "COMPUTATION_AGREEMENT",    # 计算协议达成
    "DATA_ACCESS_AUDIT",        # 数据访问审计
    "POLICY_VIOLATION",         # 策略违规
    "RIGHTS_REVOKE",            # 权益撤销
]

# 事件载荷映射（用于验证）
DATA_RIGHTS_PAYLOADS = {
    "DATA_ASSET_REGISTER": DataAssetRegisterPayload,
    "DATA_RIGHTS_GRANT": DataRightsPayload,
    "DATA_RIGHTS_COUNTER": DataRightsCounterPayload,
    "USAGE_SCOPE_DEFINE": UsageScope,
    "COMPUTATION_AGREEMENT": ComputationAgreementPayload,
    "DATA_ACCESS_AUDIT": DataAccessAuditPayload,
    "POLICY_VIOLATION": PolicyViolationPayload,
    "RIGHTS_REVOKE": RightsRevokePayload,
}


def get_all_data_rights_event_types() -> List[str]:
    """获取所有数据权益事件类型"""
    return DATA_RIGHTS_EVENT_TYPES.copy()


def get_data_rights_payload_model(event_type: str) -> Optional[type]:
    """获取指定事件类型的载荷模型"""
    return DATA_RIGHTS_PAYLOADS.get(event_type)
