"""
DeepFM Feature Fusion - 多维度特征融合网络

基于DeepFM架构的多维度特征联合建模：
1. FM组件：捕获低阶特征交互
2. DNN组件：学习高阶非线性特征交互
3. Field-aware机制：区分不同特征域

支持特征域：
- 图特征 (Graph): 128-dim embedding + 5-dim topology
- 血缘特征 (Lineage): 10-dim
- 质量特征 (Quality): 6-dim
- 市场特征 (Market): 16-dim
- 权益特征 (Rights): 8-dim
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


@dataclass
class MultiDimensionalFeatures:
    """
    多维度特征集合

    整合所有定价相关的特征维度
    """
    # 1. 图特征 (133-dim)
    graph_embedding: np.ndarray  # 128-dim GNN嵌入
    graph_topology: np.ndarray   # 5-dim: [network_value, scarcity, centrality, density, norm]

    # 2. 血缘特征 (10-dim)
    lineage_features: np.ndarray  # [completeness, upstream_quality, degradation, provenance,
                                  #  risk, spf_risk, complexity, uniqueness, alternative, overall_quality]

    # 3. 质量特征 (6-dim)
    quality_dimensions: np.ndarray  # [completeness, accuracy, timeliness, consistency, uniqueness, overall]

    # 4. 市场特征 (16-dim)
    market_dynamics: np.ndarray    # [demand, competition, trend, volatility, seasonality, ...]
    comparable_prices: np.ndarray  # 竞品价格特征

    # 5. 权益特征 (8-dim)
    rights_features: np.ndarray    # [usage, analysis, derivative, sub_license, duration, computation, exclusivity, transferability]

    def to_dict(self) -> Dict[str, np.ndarray]:
        """转换为字典格式"""
        return {
            "graph_embedding": self.graph_embedding,
            "graph_topology": self.graph_topology,
            "lineage_features": self.lineage_features,
            "quality_dimensions": self.quality_dimensions,
            "market_dynamics": self.market_dynamics,
            "comparable_prices": self.comparable_prices,
            "rights_features": self.rights_features,
        }

    def validate(self) -> bool:
        """验证特征维度"""
        expected_dims = {
            "graph_embedding": 128,
            "graph_topology": 5,
            "lineage_features": 10,
            "quality_dimensions": 6,
            "market_dynamics": 8,
            "comparable_prices": 8,
            "rights_features": 8,
        }

        actual_dims = {
            "graph_embedding": len(self.graph_embedding),
            "graph_topology": len(self.graph_topology),
            "lineage_features": len(self.lineage_features),
            "quality_dimensions": len(self.quality_dimensions),
            "market_dynamics": len(self.market_dynamics),
            "comparable_prices": len(self.comparable_prices),
            "rights_features": len(self.rights_features),
        }

        for name, expected in expected_dims.items():
            actual = actual_dims[name]
            if actual != expected:
                logger.warning(f"Feature {name} dimension mismatch: expected {expected}, got {actual}")
                return False

        return True

    def concat_all(self) -> np.ndarray:
        """拼接所有特征"""
        return np.concatenate([
            self.graph_embedding,      # 128
            self.graph_topology,       # 5
            self.lineage_features,     # 10
            self.quality_dimensions,   # 6
            self.market_dynamics,      # 8
            self.comparable_prices,    # 8
            self.rights_features,      # 8
        ])  # Total: 173-dim


class FieldAwareFactorizationMachine(nn.Module):
    """
    Field-aware Factorization Machine (FFM)

    改进的FM，不同特征域使用不同的隐向量
    """

    def __init__(self, field_dims: List[int], embed_dim: int = 16):
        super().__init__()

        self.field_dims = field_dims
        self.num_fields = len(field_dims)
        self.embed_dim = embed_dim

        # 一阶权重
        self.first_order_weights = nn.ModuleList([
            nn.Embedding(dim, 1) for dim in field_dims
        ])

        # 二阶Field-aware embedding: V_{f1,f2}
        # 对于每个特征域f1，它对其他每个域f2都有一个隐向量
        self.field_embeddings = nn.ModuleList([
            nn.ModuleList([
                nn.Embedding(field_dims[i], embed_dim)
                for _ in range(self.num_fields)
            ])
            for i in range(self.num_fields)
        ])

        # 偏置
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: [batch_size, num_fields] 特征索引

        Returns:
            output: [batch_size, 1]
        """
        batch_size = x.size(0)

        # 一阶项
        first_order = sum([
            self.first_order_weights[i](x[:, i])
            for i in range(self.num_fields)
        ])  # [batch_size, 1]

        # 二阶Field-aware交叉
        second_order = 0
        for i in range(self.num_fields):
            for j in range(i + 1, self.num_fields):
                # 域i对域j的隐向量
                v_i_j = self.field_embeddings[i][j](x[:, i])  # [batch_size, embed_dim]
                # 域j对域i的隐向量
                v_j_i = self.field_embeddings[j][i](x[:, j])  # [batch_size, embed_dim]

                # 点积
                interaction = torch.sum(v_i_j * v_j_i, dim=1, keepdim=True)
                second_order += interaction

        output = first_order + second_order + self.bias
        return output


class DeepFMFeatureFusion(nn.Module):
    """
    DeepFM多维度特征融合网络

    架构:
    - 输入层: 连续特征直接输入，离散特征Embedding
    - FM层: 捕获低阶特征交互
    - Deep层: DNN学习高阶特征交互
    - 融合层: FM + Deep组合输出
    """

    def __init__(
        self,
        continuous_dim: int = 173,  # 拼接后的连续特征维度
        field_dims: Optional[List[int]] = None,
        embed_dim: int = 16,
        mlp_dims: List[int] = [256, 128, 64],
        dropout: float = 0.3,
        use_fm: bool = True,
        use_deep: bool = True,
    ):
        super().__init__()

        self.continuous_dim = continuous_dim
        self.use_fm = use_fm
        self.use_deep = use_deep

        # 连续特征处理
        self.continuous_proj = nn.Sequential(
            nn.Linear(continuous_dim, 128),
            nn.LayerNorm(128),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

        # FM组件
        if use_fm:
            # 简化的FM: 使用隐向量内积
            self.fm_embedding = nn.Linear(continuous_dim, embed_dim)
            self.fm_bias = nn.Parameter(torch.zeros(1))

        # Deep组件
        if use_deep:
            layers = []
            input_dim = 128  # 来自continuous_proj

            for dim in mlp_dims:
                layers.extend([
                    nn.Linear(input_dim, dim),
                    nn.LayerNorm(dim),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                ])
                input_dim = dim

            layers.append(nn.Linear(input_dim, 1))
            self.deep_layers = nn.Sequential(*layers)

        # 输出融合权重（可学习）
        if use_fm and use_deep:
            self.fusion_weights = nn.Parameter(torch.tensor([0.5, 0.5]))

        self._init_weights()

    def _init_weights(self):
        """Xavier初始化"""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, continuous_x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            continuous_x: [batch_size, continuous_dim] 连续特征

        Returns:
            output: [batch_size, 1] 预测输出
        """
        # 连续特征投影
        cont_proj = self.continuous_proj(continuous_x)  # [batch_size, 128]

        outputs = []

        # FM输出
        if self.use_fm:
            # FM二阶交互: sum((sum(v_i * x_i))^2 - sum(v_i^2 * x_i^2))
            fm_emb = self.fm_embedding(continuous_x)  # [batch_size, embed_dim]

            square_of_sum = torch.sum(fm_emb, dim=1) ** 2
            sum_of_square = torch.sum(fm_emb ** 2, dim=1)
            fm_out = 0.5 * torch.sum(square_of_sum - sum_of_square, dim=-1, keepdim=True)
            fm_out = fm_out + self.fm_bias

            outputs.append(fm_out)

        # Deep输出
        if self.use_deep:
            deep_out = self.deep_layers(cont_proj)  # [batch_size, 1]
            outputs.append(deep_out)

        # 融合
        if len(outputs) == 1:
            return outputs[0]
        else:
            # 使用softmax归一化权重
            weights = F.softmax(self.fusion_weights, dim=0)
            return weights[0] * outputs[0] + weights[1] * outputs[1]


class MultiTaskPricingHead(nn.Module):
    """
    多任务定价预测头

    同时预测:
    1. 基础价格 (回归)
    2. 价格置信度 (回归)
    3. 成交概率分布 (分类: P10/P50/P90)
    4. 稀缺性等级 (分类)
    """

    def __init__(
        self,
        input_dim: int = 64,
        num_price_bins: int = 10,
    ):
        super().__init__()

        # 共享层
        self.shared = nn.Sequential(
            nn.Linear(input_dim, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
        )

        # 任务1: 基础价格预测 (对数正态分布的mu)
        self.price_mu_head = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

        # 任务2: 价格sigma (不确定性)
        self.price_sigma_head = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Softplus(),  # 确保sigma > 0
        )

        # 任务3: 成交概率分布 (P10, P50, P90)
        self.deal_prob_head = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 3),
            nn.Softmax(dim=-1),
        )

        # 任务4: 稀缺性等级
        self.scarcity_head = nn.Sequential(
            nn.Linear(64, 16),
            nn.ReLU(),
            nn.Linear(16, 3),  # low, medium, high
        )

        # 任务5: 质量评分
        self.quality_head = nn.Sequential(
            nn.Linear(64, 16),
            nn.ReLU(),
            nn.Linear(16, 5),  # 5个质量维度
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Args:
            x: [batch_size, input_dim]

        Returns:
            dict: 各任务预测结果
        """
        shared_features = self.shared(x)

        return {
            "price_mu": self.price_mu_head(shared_features),  # [batch_size, 1]
            "price_sigma": self.price_sigma_head(shared_features),  # [batch_size, 1]
            "deal_probs": self.deal_prob_head(shared_features),  # [batch_size, 3]
            "scarcity_logits": self.scarcity_head(shared_features),  # [batch_size, 3]
            "quality_scores": self.quality_head(shared_features),  # [batch_size, 5]
        }


class PricingPredictor(nn.Module):
    """
    统一定价预测器

    整合特征融合和多任务预测
    """

    def __init__(
        self,
        continuous_dim: int = 173,
        embed_dim: int = 16,
        mlp_dims: List[int] = [256, 128, 64],
        dropout: float = 0.3,
    ):
        super().__init__()

        # 特征融合
        self.feature_fusion = DeepFMFeatureFusion(
            continuous_dim=continuous_dim,
            embed_dim=embed_dim,
            mlp_dims=mlp_dims,
            dropout=dropout,
        )

        # 多任务预测
        self.prediction_head = MultiTaskPricingHead(
            input_dim=mlp_dims[-1],
        )

    def forward(
        self,
        features: MultiDimensionalFeatures,
    ) -> Dict[str, torch.Tensor]:
        """
        前向传播

        Args:
            features: 多维度特征

        Returns:
            predictions: 预测结果字典
        """
        # 拼接特征
        x = torch.tensor(
            features.concat_all(),
            dtype=torch.float32,
        ).unsqueeze(0)  # [1, continuous_dim]

        # 特征融合
        if torch.cuda.is_available():
            x = x.cuda()
            self.cuda()

        fused = self.feature_fusion(x)  # [1, 1]

        # 多任务预测 (需要扩展维度)
        predictions = self.prediction_head(fused)

        return predictions

    def predict_price_distribution(
        self,
        features: MultiDimensionalFeatures,
    ) -> Dict[str, Any]:
        """
        预测价格分布

        返回三档价格的概率
        """
        self.eval()
        with torch.no_grad():
            predictions = self.forward(features)

        # 解析预测结果
        mu = predictions["price_mu"].item()
        sigma = predictions["price_sigma"].item()
        deal_probs = predictions["deal_probs"].squeeze().cpu().numpy()

        # 计算对数正态分布的三档价格
        # P10: 10%分位数
        # P50: 中位数
        # P90: 90%分位数
        p10 = np.exp(mu - 1.28 * sigma)  # 约10%分位数
        p50 = np.exp(mu)  # 中位数
        p90 = np.exp(mu + 1.28 * sigma)  # 约90%分位数

        return {
            "conservative_price": float(p10),
            "moderate_price": float(p50),
            "aggressive_price": float(p90),
            "price_mu": float(mu),
            "price_sigma": float(sigma),
            "p10_deal_prob": float(deal_probs[0]),
            "p50_deal_prob": float(deal_probs[1]),
            "p90_deal_prob": float(deal_probs[2]),
            "scarcity_level": self._get_scarcity_level(predictions["scarcity_logits"]),
            "quality_prediction": predictions["quality_scores"].squeeze().cpu().numpy().tolist(),
        }

    def _get_scarcity_level(self, scarcity_logits: torch.Tensor) -> str:
        """获取稀缺性等级"""
        level_idx = torch.argmax(scarcity_logits, dim=-1).item()
        levels = ["low", "medium", "high"]
        return levels[level_idx]

    def compute_loss(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor],
        task_weights: Optional[Dict[str, float]] = None,
    ) -> torch.Tensor:
        """
        计算多任务损失
        """
        if task_weights is None:
            task_weights = {
                "price": 1.0,
                "deal_prob": 0.5,
                "scarcity": 0.3,
                "quality": 0.3,
            }

        losses = {}

        # 1. 价格预测损失 (MSE on mu)
        if "price" in targets:
            price_loss = F.mse_loss(
                predictions["price_mu"].squeeze(),
                targets["price"],
            )
            losses["price"] = price_loss

        # 2. 成交概率损失 (KL散度)
        if "deal_probs" in targets:
            deal_loss = F.kl_div(
                predictions["deal_probs"].log(),
                targets["deal_probs"],
                reduction="batchmean",
            )
            losses["deal_prob"] = deal_loss

        # 3. 稀缺性分类损失
        if "scarcity" in targets:
            scarcity_loss = F.cross_entropy(
                predictions["scarcity_logits"],
                targets["scarcity"],
            )
            losses["scarcity"] = scarcity_loss

        # 4. 质量预测损失
        if "quality" in targets:
            quality_loss = F.mse_loss(
                predictions["quality_scores"],
                targets["quality"],
            )
            losses["quality"] = quality_loss

        # 加权总损失
        total_loss = sum(
            task_weights.get(task, 1.0) * loss
            for task, loss in losses.items()
        )

        return total_loss


class FeatureFusionPipeline:
    """
    特征融合管道

    整合来自各个Skill的特征，统一输出到定价模型
    """

    def __init__(
        self,
        gnn_embedder=None,
        lineage_engine=None,
        quality_service=None,
        market_service=None,
    ):
        self.gnn_embedder = gnn_embedder
        self.lineage_engine = lineage_engine
        self.quality_service = quality_service
        self.market_service = market_service

    async def extract_all_features(
        self,
        asset_id: str,
    ) -> Optional[MultiDimensionalFeatures]:
        """
        提取资产的所有维度特征
        """
        try:
            # 1. 图特征
            graph_features = await self._extract_graph_features(asset_id)

            # 2. 血缘特征
            lineage_features = await self._extract_lineage_features(asset_id)

            # 3. 质量特征
            quality_features = await self._extract_quality_features(asset_id)

            # 4. 市场特征
            market_features = await self._extract_market_features(asset_id)

            # 5. 权益特征（从请求中获取或使用默认）
            rights_features = self._get_default_rights_features()

            # 组装
            features = MultiDimensionalFeatures(
                graph_embedding=graph_features["embedding"],
                graph_topology=graph_features["topology"],
                lineage_features=lineage_features,
                quality_dimensions=quality_features,
                market_dynamics=market_features["dynamics"],
                comparable_prices=market_features["comparables"],
                rights_features=rights_features,
            )

            return features

        except Exception as e:
            logger.exception(f"Failed to extract features for {asset_id}: {e}")
            return None

    async def _extract_graph_features(self, asset_id: str) -> Dict:
        """提取图特征"""
        if self.gnn_embedder is None:
            return self._default_graph_features()

        from app.services.gnn.pricing_integration import GraphFeatureExtractor

        extractor = GraphFeatureExtractor(self.gnn_embedder)
        features = await extractor.extract_features(asset_id)

        if features is None:
            return self._default_graph_features()

        return {
            "embedding": features["embedding"],
            "topology": np.array([
                features.get("network_value", 50) / 100,
                features.get("scarcity_score", 0.5),
                features.get("centrality", 0.5),
                features.get("community_density", 0.5),
                features.get("embedding_norm", 10) / 20,
            ], dtype=np.float32),
        }

    async def _extract_lineage_features(self, asset_id: str) -> np.ndarray:
        """提取血缘特征"""
        if self.lineage_engine is None:
            return self._default_lineage_features()

        lineage_features = await self.lineage_engine.analyze_lineage_for_pricing(asset_id)

        return lineage_features.to_vector()

    async def _extract_quality_features(self, asset_id: str) -> np.ndarray:
        """提取质量特征"""
        if self.quality_service is None:
            return self._default_quality_features()

        # 这里简化处理，实际应该调用质量评估服务
        return np.array([0.7, 0.75, 0.8, 0.7, 0.85, 0.75], dtype=np.float32)

    async def _extract_market_features(self, asset_id: str) -> Dict:
        """提取市场特征"""
        if self.market_service is None:
            return self._default_market_features()

        # 简化处理
        return {
            "dynamics": np.array([0.5, 0.3, 0.0, 0.2, 0.1, 0.4, 0.6, 0.5], dtype=np.float32),
            "comparables": np.array([0.8, 0.9, 0.85, 0.75, 0.9, 0.8, 0.85, 0.9], dtype=np.float32),
        }

    def _get_default_rights_features(self) -> np.ndarray:
        """默认权益特征"""
        return np.array([1.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.0, 0.0], dtype=np.float32)

    def _default_graph_features(self) -> Dict:
        """默认图特征"""
        return {
            "embedding": np.zeros(128, dtype=np.float32),
            "topology": np.array([0.5, 0.5, 0.5, 0.5, 0.5], dtype=np.float32),
        }

    def _default_lineage_features(self) -> np.ndarray:
        """默认血缘特征"""
        return np.array([0.5] * 10, dtype=np.float32)

    def _default_quality_features(self) -> np.ndarray:
        """默认质量特征"""
        return np.array([0.7, 0.75, 0.8, 0.7, 0.85, 0.75], dtype=np.float32)

    def _default_market_features(self) -> Dict:
        """默认市场特征"""
        return {
            "dynamics": np.array([0.5] * 8, dtype=np.float32),
            "comparables": np.array([0.8] * 8, dtype=np.float32),
        }
