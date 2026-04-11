"""
Graph Embedding Inference Service

用于在线推理的图嵌入服务
"""

import torch
import numpy as np
from typing import Optional, Dict, List, Any, Tuple
import asyncio
import logging
from pathlib import Path
import time

from app.services.gnn.models.graphsage import AssetGraphSAGE
from app.services.gnn.data.neo4j_loader import Neo4jGraphLoader

logger = logging.getLogger(__name__)


class AssetGraphEmbedder:
    """
    资产图嵌入推理服务

    单例模式，维护预加载的模型
    提供低延迟的图嵌入推理
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_path: Optional[str] = None,
        neo4j_driver=None,
        node_encoder=None,
        edge_encoder=None,
        device: str = "auto",
        cache_size: int = 10000,
    ):
        if self._initialized:
            return

        self.model_path = model_path
        self.neo4j_driver = neo4j_driver
        self.node_encoder = node_encoder
        self.edge_encoder = edge_encoder
        self.cache_size = cache_size

        # 设备选择
        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # 模型和加载器
        self.model: Optional[AssetGraphSAGE] = None
        self.loader: Optional[Neo4jGraphLoader] = None

        # 嵌入缓存 {asset_id: (embedding, timestamp)}
        self._cache: Dict[str, Tuple[np.ndarray, float]] = {}
        self._cache_ttl = 3600  # 缓存1小时

        self._initialized = True

        logger.info(f"AssetGraphEmbedder initialized on {self.device}")

    async def initialize(self):
        """异步初始化模型和加载器"""
        if self.model is not None:
            return

        # 初始化Neo4j加载器
        if self.neo4j_driver and self.node_encoder and self.edge_encoder:
            self.loader = Neo4jGraphLoader(
                self.neo4j_driver,
                self.node_encoder,
                self.edge_encoder,
            )

        # 加载模型
        if self.model_path and Path(self.model_path).exists():
            await self._load_model()
        else:
            logger.warning(f"Model path not found: {self.model_path}, using random init")
            self._init_random_model()

    def _init_random_model(self):
        """初始化随机模型（用于测试）"""
        in_channels = self.node_encoder.feature_dim if self.node_encoder else 128

        self.model = AssetGraphSAGE(
            in_channels=in_channels,
            hidden_channels=256,
            out_channels=128,
            num_layers=3,
            dropout=0.0,  # 推理时不dropout
        ).to(self.device)

        self.model.eval()

    async def _load_model(self):
        """加载预训练模型"""
        try:
            checkpoint = torch.load(self.model_path, map_location=self.device)

            # 从checkpoint恢复模型配置
            model_config = checkpoint.get("model_config", {})
            in_channels = model_config.get("in_channels", 128)

            self.model = AssetGraphSAGE(
                in_channels=in_channels,
                hidden_channels=model_config.get("hidden_channels", 256),
                out_channels=model_config.get("out_channels", 128),
                num_layers=model_config.get("num_layers", 3),
                dropout=0.0,
            ).to(self.device)

            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.model.eval()

            logger.info(f"Model loaded from {self.model_path}")

        except Exception as e:
            logger.error(f"Failed to load model: {e}, using random init")
            self._init_random_model()

    async def embed(self, asset_id: str, use_cache: bool = True) -> Optional[np.ndarray]:
        """
        获取资产的图嵌入

        Args:
            asset_id: 资产ID
            use_cache: 是否使用缓存

        Returns:
            128维嵌入向量
        """
        if not self._initialized or self.model is None:
            await self.initialize()

        # 检查缓存
        if use_cache and asset_id in self._cache:
            embedding, timestamp = self._cache[asset_id]
            if time.time() - timestamp < self._cache_ttl:
                return embedding

        # 加载图数据
        if self.loader is None:
            logger.error("Neo4j loader not initialized")
            return None

        data = await self.loader.load_asset_subgraph(asset_id)
        if data is None:
            logger.warning(f"Failed to load subgraph for {asset_id}")
            return None

        # 推理
        embedding = self._infer(data)

        # 缓存结果
        if use_cache and embedding is not None:
            self._cache[asset_id] = (embedding, time.time())
            self._cleanup_cache()

        return embedding

    def _infer(self, data) -> Optional[np.ndarray]:
        """执行推理"""
        try:
            with torch.no_grad():
                # 准备输入
                x = data.x.to(self.device)
                edge_index = data.edge_index.to(self.device)
                edge_attr = data.edge_attr.to(self.device) if hasattr(data, 'edge_attr') else None

                # 前向传播
                node_embeddings = self.model.get_node_embedding(
                    x, edge_index, edge_attr
                )

                # 提取中心节点嵌入
                if hasattr(data, 'center_node_idx'):
                    center_embedding = node_embeddings[data.center_node_idx]
                else:
                    # 如果没有中心节点索引，使用平均池化
                    center_embedding = node_embeddings.mean(dim=0)

                # 转到CPU并转为numpy
                embedding = center_embedding.cpu().numpy()

                return embedding

        except Exception as e:
            logger.exception(f"Inference failed: {e}")
            return None

    async def embed_batch(
        self,
        asset_ids: List[str],
        batch_size: int = 32,
    ) -> Dict[str, Optional[np.ndarray]]:
        """
        批量获取嵌入

        Returns:
            {asset_id: embedding}
        """
        results = {}

        # 分批处理
        for i in range(0, len(asset_ids), batch_size):
            batch_ids = asset_ids[i:i + batch_size]

            # 并发获取嵌入
            tasks = [self.embed(aid) for aid in batch_ids]
            embeddings = await asyncio.gather(*tasks)

            for aid, emb in zip(batch_ids, embeddings):
                results[aid] = emb

        return results

    def _cleanup_cache(self):
        """清理过期缓存"""
        if len(self._cache) <= self.cache_size:
            return

        current_time = time.time()
        expired = [
            k for k, (_, ts) in self._cache.items()
            if current_time - ts > self._cache_ttl
        ]

        for k in expired:
            del self._cache[k]

        # 如果仍然超过限制，移除最旧的
        if len(self._cache) > self.cache_size:
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1][1]
            )
            to_remove = len(self._cache) - self.cache_size
            for k, _ in sorted_items[:to_remove]:
                del self._cache[k]

    def clear_cache(self):
        """清除所有缓存"""
        self._cache.clear()
        logger.info("Embedding cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self.cache_size,
            "cache_hits": getattr(self, '_cache_hits', 0),
            "cache_misses": getattr(self, '_cache_misses', 0),
        }


class GraphFeatureExtractor:
    """
    图特征提取器

    基于图嵌入提取下游任务可用的特征
    """

    def __init__(self, embedder: AssetGraphEmbedder):
        self.embedder = embedder

    async def extract_features(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """
        提取完整的图特征

        Returns:
            {
                "embedding": np.ndarray,  # 128维嵌入
                "topology_features": Dict,  # 拓扑特征
                "network_value": float,  # 网络价值
                "scarcity_score": float,  # 稀缺性
            }
        """
        # 获取嵌入
        embedding = await self.embedder.embed(asset_id)
        if embedding is None:
            return None

        # 提取拓扑特征
        topology = await self._extract_topology_features(asset_id)

        # 计算网络价值
        network_value = self._calculate_network_value(embedding, topology)

        # 计算稀缺性
        scarcity = topology.get("scarcity_score", 0.5)

        return {
            "embedding": embedding,
            "embedding_dim": len(embedding),
            "topology_features": topology,
            "network_value": network_value,
            "scarcity_score": scarcity,
            "centrality": topology.get("centrality", 0.0),
            "community_id": topology.get("community_id", -1),
            "community_density": topology.get("community_density", 0.0),
        }

    async def _extract_topology_features(self, asset_id: str) -> Dict[str, float]:
        """提取拓扑特征"""
        # 这里简化处理，实际应该查询Neo4j获取拓扑信息
        # 返回模拟数据
        return {
            "centrality": np.random.uniform(0, 1),
            "betweenness": np.random.uniform(0, 1),
            "clustering_coeff": np.random.uniform(0, 1),
            "community_id": np.random.randint(0, 10),
            "community_size": np.random.randint(5, 100),
            "community_density": np.random.uniform(0, 1),
            "scarcity_score": np.random.uniform(0, 1),
        }

    def _calculate_network_value(
        self,
        embedding: np.ndarray,
        topology: Dict[str, float]
    ) -> float:
        """计算网络价值"""
        # 基于嵌入范数和拓扑特征计算
        embed_norm = np.linalg.norm(embedding)
        centrality = topology.get("centrality", 0.5)
        density = topology.get("community_density", 0.5)

        # 加权组合
        network_value = (
            embed_norm * 0.4 +
            centrality * 100 * 0.3 +
            density * 100 * 0.3
        )

        return min(100, network_value)

    async def compute_similarity(
        self,
        asset_id1: str,
        asset_id2: str,
    ) -> Optional[float]:
        """计算两个资产的相似度"""
        emb1 = await self.embedder.embed(asset_id1)
        emb2 = await self.embedder.embed(asset_id2)

        if emb1 is None or emb2 is None:
            return None

        # 余弦相似度
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

        return float(similarity)

    async def find_similar_assets(
        self,
        asset_id: str,
        candidate_ids: List[str],
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """
        查找相似资产

        Returns:
            [(asset_id, similarity), ...]
        """
        target_emb = await self.embedder.embed(asset_id)
        if target_emb is None:
            return []

        # 批量获取候选嵌入
        candidate_embs = await self.embedder.embed_batch(candidate_ids)

        # 计算相似度
        similarities = []
        for cid, emb in candidate_embs.items():
            if emb is not None:
                sim = np.dot(target_emb, emb) / (np.linalg.norm(target_emb) * np.linalg.norm(emb))
                similarities.append((cid, float(sim)))

        # 排序返回top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
