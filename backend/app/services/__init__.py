"""Services package.

业务逻辑层的统一导出入口。
采用惰性导出，避免仅导入轻量模块时也提前触发交易、定价、GNN 等重型依赖。
"""

from importlib import import_module

_EXPORTS = {
    "SpaceAwareService": ("app.services.base", "SpaceAwareService"),
    "LLMGateway": ("app.services.llm_gateway", "LLMGateway"),
    "PersonalLLMClient": ("app.services.llm_gateway", "PersonalLLMClient"),
    "SystemLLMClient": ("app.services.llm_gateway", "SystemLLMClient"),
    "SystemFeatureType": ("app.services.llm_gateway", "SystemFeatureType"),
    "LLMTaskClassifier": ("app.services.llm_gateway", "LLMTaskClassifier"),
    "get_personal_llm": ("app.services.llm_gateway", "get_personal_llm"),
    "get_system_llm": ("app.services.llm_gateway", "get_system_llm"),
    "llm_route_and_invoke": ("app.services.llm_gateway", "llm_route_and_invoke"),
    "AssetService": ("app.services.asset_service", "AssetService"),
    "AuthService": ("app.services.auth_service", "AuthService"),
    "CollaborationService": ("app.services.collaboration_service", "CollaborationService"),
    "FileService": ("app.services.file", "FileService"),
    "KnowledgeGraphService": ("app.services.graph", "KnowledgeGraphService"),
    "IngestService": ("app.services.ingest_service", "IngestService"),
    "LineageService": ("app.services.lineage_service", "LineageService"),
    "MarkdownService": ("app.services.markdown_service", "MarkdownDocumentService"),
    "SpaceService": ("app.services.space", "SpaceService"),
    "TradeService": ("app.services.trade", "TradeService"),
    "TradeAgentService": ("app.services.trade", "TradeAgentService"),
    "UnifiedTradeService": ("app.services.trade", "UnifiedTradeService"),
    "TradeActionService": ("app.services.trade.trade_action_service", "TradeActionService"),
    "TradeAction": ("app.services.trade.trade_action_service", "TradeAction"),
    "TradeActionResult": ("app.services.trade.trade_action_service", "TradeActionResult"),
    "execute_trade_action": ("app.services.trade.trade_action_service", "execute_trade_action"),
    "TradeBatchOperationsService": ("app.services.trade.batch_operations_service", "TradeBatchOperationsService"),
    "BatchOperationResult": ("app.services.trade.batch_operations_service", "BatchOperationResult"),
    "RightsEnforcementEngine": ("app.services.data_rights", "RightsEnforcementEngine"),
    "RightEnforcementType": ("app.services.data_rights", "RightEnforcementType"),
    "EnforcementPolicy": ("app.services.data_rights", "EnforcementPolicy"),
    "ENFORCEMENT_POLICIES": ("app.services.data_rights", "ENFORCEMENT_POLICIES"),
    "enforce_data_access": ("app.services.data_rights", "enforce_data_access"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Trade services
from .trade import (
    TradeAgentService,
    TradeService,
)

__all__ = [
    # Base
    "SpaceAwareService",
    # Domain
    "AssetService",
    "AuthService",
    "CollaborationService",
    "FileService",
    "KnowledgeGraphService",
    "IngestService",
    "LineageService",
    "MarkdownService",
    "SpaceService",
    # Trade
    "TradeService",
    "TradeAgentService",
]
