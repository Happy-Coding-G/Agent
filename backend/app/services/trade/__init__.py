"""
Trade Services Package

数据权益交易服务（仅支持直接交易）
"""

from app.services.trade.trade_agent_service import TradeAgentService
from app.services.trade.trade_service import TradeService

# Phase 1: 数据权益基础
from app.services.trade.data_rights_events import (
    DataAssetRegisterPayload,
    DataRightsPayload,
    DataRightsCounterPayload,
    ComputationAgreementPayload,
    DataAccessAuditPayload,
    PolicyViolationPayload,
    RightsRevokePayload,
    DataRightsType,
    ComputationMethod,
    DataSensitivityLevel,
    AnonymizationLevel,
    QualityMetrics,
)
from app.services.trade.data_rights_service import DataRightsService

# Phase 2: 高级功能
from app.services.trade.privacy_computation import (
    PrivacyComputationNegotiator,
    AnonymizationService,
)
from app.services.trade.continuous_audit import (
    ContinuousAuditService,
    ViolationType,
    ViolationSeverity,
)
from app.services.trade.kg_integration import (
    DataAssetKGIntegration,
    BuyerProfilingService,
    RecommendationEngine,
)

from app.services.trade.unified_trade_service import UnifiedTradeService

__all__ = [
    # 核心服务
    "TradeService",
    "TradeAgentService",
    "UnifiedTradeService",
    "DataRightsService",

    # 数据权益事件
    "DataAssetRegisterPayload",
    "DataRightsPayload",
    "DataRightsCounterPayload",
    "ComputationAgreementPayload",
    "DataAccessAuditPayload",
    "PolicyViolationPayload",
    "RightsRevokePayload",
    "DataRightsType",
    "ComputationMethod",
    "DataSensitivityLevel",
    "AnonymizationLevel",
    "QualityMetrics",

    # Phase 2: 隐私计算
    "PrivacyComputationNegotiator",
    "AnonymizationService",

    # Phase 2: 审计
    "ContinuousAuditService",
    "ViolationType",
    "ViolationSeverity",

    # Phase 2: 知识图谱集成
    "DataAssetKGIntegration",
    "BuyerProfilingService",
    "RecommendationEngine",
]
