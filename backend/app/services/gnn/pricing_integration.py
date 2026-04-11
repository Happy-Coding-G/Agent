"""
GNN与PricingSkill集成模块

将图嵌入集成到动态定价流程中
"""

from typing import Dict, Any, Optional, List
import numpy as np
import asyncio
import logging

from app.services.gnn.inference.embedder import AssetGraphEmbedder, GraphFeatureExtractor
from app.services.gnn.models.encoders import NodeEncoder, EdgeEncoder

logger = logging.getLogger(__name__)


class GNNPricingIntegration:
    """
    GNN定价集成器

    将图神经网络特征集成到定价流程
    """

    def __init__(
        self,
        embedder: Optional[AssetGraphEmbedder] = None,
        feature_extractor: Optional[GraphFeatureExtractor] = None,
    ):
        self.embedder = embedder
        self.feature_extractor = feature_extractor

        # 如果没有提供，创建默认实例
        if self.embedder is None:
            self.embedder = self._create_default_embedder()

        if self.feature_extractor is None:
            self.feature_extractor = GraphFeatureExtractor(self.embedder)

    def _create_default_embedder(self) -> AssetGraphEmbedder:
        """创建默认嵌入器"""
        # 实际使用时应该从配置加载
        from app.core.config import settings
        from neo4j import AsyncGraphDatabase

        # 创建Neo4j驱动
        neo4j_driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )

        # 创建编码器
        node_encoder = NodeEncoder()
        edge_encoder = EdgeEncoder()

        # 创建嵌入器
        embedder = AssetGraphEmbedder(
            model_path="./checkpoints/graphsage/best.pt",
            neo4j_driver=neo4j_driver,
            node_encoder=node_encoder,
            edge_encoder=edge_encoder,
        )

        return embedder

    async def get_graph_pricing_features(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        获取图相关的定价特征

        Returns:
            {
                "embedding": np.ndarray,  # 128维图嵌入
                "embedding_norm": float,  # 嵌入范数
                "network_value": float,   # 网络价值得分
                "scarcity_score": float,  # 稀缺性得分
                "centrality": float,      # 中心性
                "community_density": float,  # 社区密度
                "similarity_vector": np.ndarray,  # 与竞品的相似度
            }
        """
        try:
            features = await self.feature_extractor.extract_features(asset_id)
            if features is None:
                return None

            # 计算嵌入范数
            embedding = features["embedding"]
            embedding_norm = np.linalg.norm(embedding)

            return {
                "embedding": embedding,
                "embedding_norm": float(embedding_norm),
                "network_value": features["network_value"],
                "scarcity_score": features["scarcity_score"],
                "centrality": features["centrality"],
                "community_density": features["community_density"],
                "community_id": features.get("community_id", -1),
                "similarity_vector": features.get("similarity_vector", np.array([])),
            }

        except Exception as e:
            logger.exception(f"Failed to extract graph features for {asset_id}: {e}")
            return None

    async def calculate_similarity_adjustment(
        self,
        asset_id: str,
        comparable_assets: List[str],
    ) -> Dict[str, float]:
        """
        基于图嵌入计算相似性调整因子

        Returns:
            {
                "similarity_boost": float,  # 相似度溢价/折价
                "differentiation_score": float,  # 差异化得分
                "market_position": str,  # 市场定位
            }
        """
        # 获取相似资产
        similar_assets = await self.feature_extractor.find_similar_assets(
            asset_id, comparable_assets, top_k=5
        )

        if not similar_assets:
            return {
                "similarity_boost": 0.0,
                "differentiation_score": 0.5,
                "market_position": "unknown",
            }

        # 计算平均相似度
        avg_similarity = sum(sim for _, sim in similar_assets) / len(similar_assets)

        # 差异化得分（与竞品越不相似，差异化越高）
        differentiation = 1 - avg_similarity

        # 市场定位
        if differentiation > 0.7:
            position = "differentiated"  # 差异化定位，可溢价
        elif differentiation > 0.3:
            position = "competitive"     # 竞争定位，跟随市场价
        else:
            position = "commodity"       # 同质化，价格竞争

        # 相似度调整（差异化高可溢价，同质化需折价）
        if position == "differentiated":
            boost = 0.15  # 15%溢价
        elif position == "competitive":
            boost = 0.0
        else:
            boost = -0.1  # 10%折价

        return {
            "similarity_boost": boost,
            "differentiation_score": differentiation,
            "market_position": position,
            "top_similar": similar_assets,
        }

    def fuse_features_for_pricing(
        self,
        graph_features: Dict[str, Any],
        lineage_features: Dict[str, float],
        quality_features: Dict[str, float],
        market_features: Dict[str, float],
        rights_features: Dict[str, Any],
    ) -> np.ndarray:
        """
        融合多维度特征用于定价

        Returns:
            融合后的特征向量
        """
        # 各维度特征
        graph_emb = graph_features.get("embedding", np.zeros(128))
        graph_topo = np.array([
            graph_features.get("network_value", 0) / 100,  # 归一化
            graph_features.get("scarcity_score", 0.5),
            graph_features.get("centrality", 0.5),
            graph_features.get("community_density", 0.5),
            graph_features.get("embedding_norm", 1.0) / 10,
        ], dtype=np.float32)

        lineage_vec = np.array([
            lineage_features.get("lineage_completeness", 0.5),
            lineage_features.get("upstream_quality_score", 0.5),
            lineage_features.get("derivation_complexity", 0.5),
            lineage_features.get("alternative_sources", 0) / 10,
            lineage_features.get("data_provenance_score", 0.5),
        ], dtype=np.float32)

        quality_vec = np.array([
            quality_features.get("completeness", 0.5),
            quality_features.get("accuracy", 0.5),
            quality_features.get("timeliness", 0.5),
            quality_features.get("consistency", 0.5),
            quality_features.get("uniqueness", 0.5),
            quality_features.get("overall_score", 0.5),
        ], dtype=np.float32)

        market_vec = np.array([
            market_features.get("demand_score", 0.5),
            market_features.get("competition_level", 0.5),
            market_features.get("price_trend", 0),  # -1, 0, 1
            market_features.get("avg_price", 0) / 1000,
            market_features.get("transaction_volume", 0) / 100,
        ], dtype=np.float32)

        # 拼接所有特征
        fused = np.concatenate([
            graph_emb,      # 128-dim
            graph_topo,     # 5-dim
            lineage_vec,    # 5-dim
            quality_vec,    # 6-dim
            market_vec,     # 5-dim
        ])

        return fused

    async def get_pricing_context(self, asset_id: str) -> Dict[str, Any]:
        """
        获取完整的定价上下文（包含所有特征）

        Returns:
            {
                "asset_id": str,
                "graph_features": Dict,
                "fused_features": np.ndarray,
                "recommended_strategy": str,  # 推荐定价策略
                "confidence_factors": Dict,   # 各维度置信度
            }
        """
        # 1. 获取图特征
        graph_features = await self.get_graph_pricing_features(asset_id)

        if graph_features is None:
            logger.warning(f"Failed to get graph features for {asset_id}")
            # 返回默认特征
            graph_features = {
                "embedding": np.zeros(128),
                "embedding_norm": 0.0,
                "network_value": 50.0,
                "scarcity_score": 0.5,
                "centrality": 0.5,
                "community_density": 0.5,
            }

        # 2. 推荐定价策略
        strategy = self._recommend_strategy(graph_features)

        # 3. 计算各维度置信度
        confidence = self._calculate_confidence(graph_features)

        return {
            "asset_id": asset_id,
            "graph_features": graph_features,
            "recommended_strategy": strategy,
            "confidence_factors": confidence,
        }

    def _recommend_strategy(self, graph_features: Dict[str, Any]) -> str:
        """基于图特征推荐定价策略"""
        network_value = graph_features.get("network_value", 50)
        scarcity = graph_features.get("scarcity_score", 0.5)
        centrality = graph_features.get("centrality", 0.5)

        # 高价值 + 稀缺 = 溢价策略
        if network_value > 70 and scarcity > 0.7:
            return "premium"

        # 高中心性 = 领导地位，可溢价
        if centrality > 0.8:
            return "leader"

        # 低稀缺 + 低价值 = 渗透策略
        if scarcity < 0.3 and network_value < 30:
            return "penetration"

        # 默认竞争策略
        return "competitive"

    def _calculate_confidence(self, graph_features: Dict[str, Any]) -> Dict[str, float]:
        """计算各维度置信度"""
        # 基于特征完整性计算置信度
        embedding_norm = graph_features.get("embedding_norm", 0)

        # 嵌入范数过小可能表示节点孤立
        graph_confidence = min(1.0, embedding_norm / 10)

        return {
            "graph_confidence": graph_confidence,
            "embedding_quality": graph_confidence,
            "overall": graph_confidence * 0.8 + 0.2,  # 至少0.2基础置信度
        }


# 全局集成实例
_gnn_integration: Optional[GNNPricingIntegration] = None


def get_gnn_pricing_integration() -> GNNPricingIntegration:
    """获取全局GNN定价集成实例"""
    global _gnn_integration
    if _gnn_integration is None:
        _gnn_integration = GNNPricingIntegration()
    return _gnn_integration


async def enhance_pricing_with_graph_features(
    asset_id: str,
    base_price: float,
    base_confidence: float,
) -> Dict[str, Any]:
    """
    使用图特征增强定价结果

    便捷函数，无需手动初始化
    """
    integration = get_gnn_pricing_integration()

    # 获取图特征
    graph_features = await integration.get_graph_pricing_features(asset_id)

    if graph_features is None:
        return {
            "enhanced_price": base_price,
            "adjustment": 0.0,
            "graph_features": None,
        }

    # 基于图特征调整价格
    network_value = graph_features.get("network_value", 50)
    scarcity = graph_features.get("scarcity_score", 0.5)

    # 网络价值调整
    value_adjustment = (network_value - 50) / 100  # -0.5 to +0.5

    # 稀缺性调整
    scarcity_adjustment = (scarcity - 0.5) * 0.2  # -0.1 to +0.1

    # 综合调整
    total_adjustment = value_adjustment * 0.3 + scarcity_adjustment
    adjusted_price = base_price * (1 + total_adjustment)

    return {
        "enhanced_price": round(adjusted_price, 2),
        "adjustment": round(total_adjustment, 4),
        "adjustment_breakdown": {
            "network_value_adjustment": value_adjustment * 0.3,
            "scarcity_adjustment": scarcity_adjustment,
        },
        "graph_features": {
            "network_value": network_value,
            "scarcity_score": scarcity,
            "centrality": graph_features.get("centrality"),
        },
        "confidence": base_confidence * graph_features.get("embedding_norm", 1) / 10,
    }
