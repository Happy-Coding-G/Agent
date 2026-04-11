"""
Data Rights Models - 数据权益相关数据库模型

Phase 1: 数据权益交易的数据库模型定义
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, String, Integer, DateTime, Float, ForeignKey, Text,
    JSON, Enum, Index, UniqueConstraint, Boolean
)
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum

# 假设 Base 从 models.py 导入
from app.db.models import Base


class DataSensitivityLevel(str, PyEnum):
    """数据敏感度级别"""
    LOW = "low"           # 公开数据
    MEDIUM = "medium"     # 内部数据
    HIGH = "high"         # 敏感数据
    CRITICAL = "critical" # 高度敏感数据


class ComputationMethod(str, PyEnum):
    """隐私计算方法"""
    FEDERATED_LEARNING = "federated_learning"
    MULTI_PARTY_COMPUTATION = "mpc"
    TEE = "trusted_execution_environment"
    DIFFERENTIAL_PRIVACY = "differential_privacy"
    RAW_DATA = "raw_data"


class DataRightsStatus(str, PyEnum):
    """数据权益交易状态"""
    PENDING = "pending"       # 待协商
    ACTIVE = "active"         # 协商中
    GRANTED = "granted"       # 权益已授予
    EXPIRED = "expired"       # 已过期
    REVOKED = "revoked"       # 已撤销
    VIOLATED = "violated"     # 存在违规


class DataAssets(Base):
    """
    数据资产表

    存储可信数据空间中的数据资产信息
    """
    __tablename__ = "data_assets"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(64), unique=True, nullable=False, index=True)

    # 所有者信息
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 基本信息
    asset_name = Column(String(200), nullable=False)
    asset_description = Column(Text, nullable=True)
    data_type = Column(String(50), nullable=False)  # medical, financial, behavioral, etc.

    # 敏感度与隐私
    sensitivity_level = Column(Enum(DataSensitivityLevel), nullable=False)
    default_anonymization_level = Column(Integer, default=2)  # 1-4

    # 质量评分
    quality_completeness = Column(Float, default=0.0)
    quality_accuracy = Column(Float, default=0.0)
    quality_timeliness = Column(Float, default=0.0)
    quality_consistency = Column(Float, default=0.0)
    quality_uniqueness = Column(Float, default=0.0)
    quality_overall_score = Column(Float, default=0.0)

    # 血缘信息
    raw_data_source = Column(String(500), nullable=False)
    lineage_root = Column(String(64), nullable=True)
    processing_chain_hash = Column(String(64), nullable=True)

    # 存储信息
    storage_location = Column(String(500), nullable=False)
    data_size_bytes = Column(Integer, default=0)
    record_count = Column(Integer, nullable=True)

    # 关联图谱实体
    related_entities = Column(JSON, default=list)  # 实体ID列表

    # 状态
    is_active = Column(Boolean, default=True)
    is_available_for_trade = Column(Boolean, default=True)

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # 关系
    owner = relationship("Users", back_populates="data_assets")
    rights_transactions = relationship("DataRightsTransactions", back_populates="data_asset")

    __table_args__ = (
        Index("ix_data_assets_owner", "owner_id"),
        Index("ix_data_assets_sensitivity", "sensitivity_level"),
        Index("ix_data_assets_type", "data_type"),
        Index("ix_data_assets_quality", "quality_overall_score"),
    )


class DataRightsTransactions(Base):
    """
    数据权益交易表

    记录数据权益的授予与流转
    """
    __tablename__ = "data_rights_transactions"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(64), unique=True, nullable=False, index=True)
    negotiation_id = Column(String(64), ForeignKey("negotiation_sessions.negotiation_id"), nullable=True)

    # 参与方
    data_asset_id = Column(String(64), ForeignKey("data_assets.asset_id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 数据所有者
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 数据买方

    # 权益详情
    rights_types = Column(JSON, nullable=False)  # 权益类型列表
    usage_scope = Column(JSON, nullable=False)   # 使用范围定义
    restrictions = Column(JSON, default=list)    # 附加限制

    # 隐私计算
    computation_method = Column(Enum(ComputationMethod), nullable=False)
    anonymization_level = Column(Integer, nullable=False)
    computation_constraints = Column(JSON, default=dict)

    # 有效期
    valid_from = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)

    # 价格
    agreed_price = Column(Float, nullable=True)
    currency = Column(String(10), default="CNY")

    # 状态
    status = Column(Enum(DataRightsStatus), default=DataRightsStatus.PENDING)

    # 结算信息
    settlement_tx_hash = Column(String(128), nullable=True)
    settlement_time = Column(DateTime, nullable=True)

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # 关系
    data_asset = relationship("DataAssets", back_populates="rights_transactions")
    owner = relationship("Users", foreign_keys=[owner_id], back_populates="rights_granted")
    buyer = relationship("Users", foreign_keys=[buyer_id], back_populates="rights_received")
    audit_logs = relationship("DataAccessAuditLogs", back_populates="transaction")

    __table_args__ = (
        Index("ix_rights_tx_asset", "data_asset_id"),
        Index("ix_rights_tx_owner", "owner_id"),
        Index("ix_rights_tx_buyer", "buyer_id"),
        Index("ix_rights_tx_status", "status"),
        Index("ix_rights_tx_validity", "valid_from", "valid_until"),
    )


class DataAccessAuditLogs(Base):
    """
    数据访问审计日志表

    记录数据使用过程中的详细访问日志
    """
    __tablename__ = "data_access_audit_logs"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(String(64), unique=True, nullable=False, index=True)

    # 关联信息
    transaction_id = Column(String(64), ForeignKey("data_rights_transactions.transaction_id"), nullable=False)
    negotiation_id = Column(String(64), nullable=True)
    data_asset_id = Column(String(64), nullable=False)

    # 访问者
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 访问详情
    access_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    access_purpose = Column(String(200), nullable=False)
    computation_method_used = Column(Enum(ComputationMethod), nullable=False)

    # 查询信息
    query_fingerprint = Column(String(64), nullable=False)  # 查询哈希
    query_complexity_score = Column(Float, nullable=True)

    # 结果信息
    result_size_bytes = Column(Integer, default=0)
    result_row_count = Column(Integer, nullable=True)
    result_aggregation_level = Column(String(50), nullable=False)

    # 合规与风险
    policy_compliance_check = Column(JSON, default=dict)
    risk_score = Column(Float, nullable=True)
    anomaly_flags = Column(JSON, default=list)

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 关系
    transaction = relationship("DataRightsTransactions", back_populates="audit_logs")
    buyer = relationship("Users", back_populates="access_logs")

    __table_args__ = (
        Index("ix_audit_tx", "transaction_id"),
        Index("ix_audit_buyer", "buyer_id"),
        Index("ix_audit_timestamp", "access_timestamp"),
        Index("ix_audit_risk", "risk_score"),
    )


class PolicyViolations(Base):
    """
    策略违规记录表

    记录数据使用过程中的违规行为
    """
    __tablename__ = "policy_violations"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    violation_id = Column(String(64), unique=True, nullable=False, index=True)

    # 关联信息
    transaction_id = Column(String(64), ForeignKey("data_rights_transactions.transaction_id"), nullable=False)
    negotiation_id = Column(String(64), nullable=True)
    data_asset_id = Column(String(64), nullable=False)

    # 违规详情
    violation_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)  # low, medium, high, critical

    # 详细信息
    violation_details = Column(JSON, nullable=False)
    evidence = Column(JSON, nullable=False)

    # 影响评估
    potential_data_exposure = Column(Float, nullable=True)
    affected_records_estimate = Column(Integer, nullable=True)

    # 响应措施
    automatic_action_taken = Column(String(200), nullable=True)
    manual_review_status = Column(String(50), default="pending")
    resolution_notes = Column(Text, nullable=True)

    # 时间戳
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)

    # 关系
    transaction = relationship("DataRightsTransactions")

    __table_args__ = (
        Index("ix_violation_tx", "transaction_id"),
        Index("ix_violation_type", "violation_type"),
        Index("ix_violation_severity", "severity"),
        Index("ix_violation_status", "manual_review_status"),
    )


class DataLineageNodes(Base):
    """
    数据血缘节点表

    存储数据资产的完整处理链
    """
    __tablename__ = "data_lineage_nodes"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String(64), unique=True, nullable=False, index=True)

    # 关联资产
    asset_id = Column(String(64), ForeignKey("data_assets.asset_id"), nullable=False)

    # 节点信息
    node_type = Column(String(50), nullable=False)  # raw, processed, aggregated, derived
    parent_nodes = Column(JSON, default=list)  # 父节点ID列表
    processing_logic_hash = Column(String(64), nullable=False)

    # 质量指标
    quality_metrics = Column(JSON, default=dict)

    # 完整性校验
    provenance_hash = Column(String(64), nullable=False)

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_lineage_asset", "asset_id"),
        Index("ix_lineage_type", "node_type"),
    )
