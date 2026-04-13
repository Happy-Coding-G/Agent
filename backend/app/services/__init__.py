"""
Services package

业务逻辑层 - 实现核心业务功能
"""

# Base
from .base import SpaceAwareService

# LLM Gateway - 个人LLM与系统LLM功能划分
from .llm_gateway import (
    LLMGateway,
    PersonalLLMClient,
    SystemLLMClient,
    SystemFeatureType,
    LLMTaskClassifier,
    get_personal_llm,
    get_system_llm,
    llm_route_and_invoke,
)

# Domain services
from .asset_service import AssetService
from .auth_service import AuthService
from .collaboration_service import CollaborationService
from .ingest_service import IngestService
from .lineage_service import LineageService
from .markdown_service import MarkdownDocumentService as MarkdownService

# File service from submodule
from .file import FileService

# Graph service from submodule
from .graph import KnowledgeGraphService

# Space service from submodule
from .space import SpaceService

# Trade services
from .trade import (
    TradeAgentService,
    TradeNegotiationService,
    TradeService,
    UnifiedTradeService,
)

__all__ = [
    # Base
    "SpaceAwareService",
    # LLM Gateway
    "LLMGateway",
    "PersonalLLMClient",
    "SystemLLMClient",
    "SystemFeatureType",
    "LLMTaskClassifier",
    "get_personal_llm",
    "get_system_llm",
    "llm_route_and_invoke",
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
    "TradeNegotiationService",
    "UnifiedTradeService",
]
