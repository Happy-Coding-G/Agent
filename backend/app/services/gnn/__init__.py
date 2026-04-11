"""
GNN (Graph Neural Network) Module for Asset Pricing

提供数据资产的图嵌入学习、特征提取服务。
基于PyTorch Geometric实现。
"""

from app.services.gnn.models.graphsage import AssetGraphSAGE, AssetEdgeSAGE
from app.services.gnn.inference.embedder import AssetGraphEmbedder
from app.services.gnn.data.neo4j_loader import Neo4jGraphLoader

__all__ = [
    "AssetGraphSAGE",
    "AssetEdgeSAGE",
    "AssetGraphEmbedder",
    "Neo4jGraphLoader",
]
