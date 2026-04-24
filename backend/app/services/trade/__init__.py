"""Trade services package with lazy exports."""

from importlib import import_module

_EXPORTS = {
    "TradeService": ("app.services.trade.trade_service", "TradeService"),
    "TradeAgentService": ("app.services.trade.trade_agent_service", "TradeAgentService"),
    "UnifiedTradeService": ("app.services.trade.unified_trade_service", "UnifiedTradeService"),
    "DataRightsService": ("app.services.trade.data_rights_service", "DataRightsService"),
    "DataAssetRegisterPayload": ("app.services.trade.data_rights_events", "DataAssetRegisterPayload"),
    "DataRightsPayload": ("app.services.trade.data_rights_events", "DataRightsPayload"),
    "DataRightsCounterPayload": ("app.services.trade.data_rights_events", "DataRightsCounterPayload"),
    "ComputationAgreementPayload": ("app.services.trade.data_rights_events", "ComputationAgreementPayload"),
    "DataAccessAuditPayload": ("app.services.trade.data_rights_events", "DataAccessAuditPayload"),
    "PolicyViolationPayload": ("app.services.trade.data_rights_events", "PolicyViolationPayload"),
    "RightsRevokePayload": ("app.services.trade.data_rights_events", "RightsRevokePayload"),
    "DataRightsType": ("app.services.trade.data_rights_events", "DataRightsType"),
    "ComputationMethod": ("app.services.trade.data_rights_events", "ComputationMethod"),
    "DataSensitivityLevel": ("app.services.trade.data_rights_events", "DataSensitivityLevel"),
    "AnonymizationLevel": ("app.services.trade.data_rights_events", "AnonymizationLevel"),
    "QualityMetrics": ("app.services.trade.data_rights_events", "QualityMetrics"),
    "PrivacyComputationNegotiator": (
        "app.services.trade.privacy_computation",
        "PrivacyComputationNegotiator",
    ),
    "AnonymizationService": ("app.services.trade.privacy_computation", "AnonymizationService"),
    "ContinuousAuditService": ("app.services.trade.continuous_audit", "ContinuousAuditService"),
    "ViolationType": ("app.services.trade.continuous_audit", "ViolationType"),
    "ViolationSeverity": ("app.services.trade.continuous_audit", "ViolationSeverity"),
    "DataAssetKGIntegration": ("app.services.trade.kg_integration", "DataAssetKGIntegration"),
    "BuyerProfilingService": ("app.services.trade.kg_integration", "BuyerProfilingService"),
    "RecommendationEngine": ("app.services.trade.kg_integration", "RecommendationEngine"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
