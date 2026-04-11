# 数据血缘驱动的动态定价系统架构设计

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          智能定价引擎 (Pricing Engine)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   图特征提取   │  │   血缘分析    │  │   市场情报    │  │   质量评估    │    │
│  │  (GNN/GraphSAGE)│  │(Lineage Graph)│  │(Market Data) │  │(Quality Score)│    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │             │
│         └─────────────────┴────────┬────────┴─────────────────┘             │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    特征融合与联合建模层 (Feature Fusion)                  │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │  图谱嵌入特征  │  │  血缘结构特征  │  │  市场时序特征  │  │  质量维度特征  │ │   │
│  │  │ (128-dim)   │  │ (64-dim)    │  │ (32-dim)    │  │ (32-dim)    │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │              联合建模网络 (Ensemble/DeepFM/XGBoost)               │ │   │
│  │  │                   输出: 基础价格 + 置信度分数                      │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      三档价格阈值生成器                                  │   │
│  │                                                                     │   │
│  │   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │   │
│  │   │   保守价格 (P10)  │  │   适中价格 (P50)  │  │   激进价格 (P90)  │ │   │
│  │   │   μ - 1.28σ      │  │   μ (公允价值)    │  │   μ + 1.28σ      │ │   │
│  │   │   成交概率: 10%   │  │   成交概率: 50%   │  │   成交概率: 90%  │ │   │
│  │   └──────────────────┘  └──────────────────┘  └──────────────────┘ │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         博弈策略引擎                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │                    对手建模 (Opponent Modeling)                    │ │   │
│  │  │  - 历史出价模式分析  - 价格敏感度估计  - 成交概率预测              │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │                    让步策略优化 (Concession Strategy)              │ │   │
│  │  │  - 时间压力函数    - 替代方案评估    - 效用最大化求解             │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  │                              │                                       │   │
│  │                              ▼                                       │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│  │  │                    强化学习决策 (RL Policy)                        │ │   │
│  │  │  State → Policy Network → Action (Accept/Counter/Reject)         │ │   │
│  │  └─────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│                         最终定价决策 + 置信度报告                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. 核心模块详细设计

### 2.1 知识图谱图特征提取 (Graph Feature Extractor)

#### 2.1.1 图谱结构定义

```python
# 知识图谱中的实体和关系类型
EntityTypes = {
    "DataAsset": "数据资产节点",
    "DataSource": "数据源节点",
    "ProcessingStep": "处理步骤节点",
    "Entity": "业务实体",
    "User": "用户节点",
    "Tag": "标签节点"
}

RelationTypes = {
    "DERIVED_FROM": "派生自",
    "PROCESSED_BY": "经过处理",
    "CONTAINS_ENTITY": "包含实体",
    "OWNED_BY": "归属于",
    "TAGGED_WITH": "标签关联",
    "SIMILAR_TO": "相似于"
}
```

#### 2.1.2 图嵌入模型选择

**方案A: GraphSAGE (推荐)**
- 适合动态图（资产持续上架）
- 支持归纳学习（新节点无需重新训练）
- 计算效率适合在线服务

**方案B: GAT (Graph Attention Network)**
- 捕获邻居重要性权重
- 可解释性更强
- 计算开销较大

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv, GATConv

class AssetGraphEmbedding(nn.Module):
    """
    数据资产图嵌入模型
    输入: 资产子图（资产节点 + 邻居）
    输出: 128维资产嵌入向量
    """
    def __init__(self, in_channels: int, hidden_channels: int = 256, out_channels: int = 128):
        super().__init__()
        # GraphSAGE层
        self.conv1 = SAGEConv(in_channels, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, hidden_channels)
        self.conv3 = SAGEConv(hidden_channels, out_channels)

        # 注意力池化
        self.attention = nn.MultiheadAttention(out_channels, num_heads=4)

        # 投影层
        self.project = nn.Sequential(
            nn.Linear(out_channels, out_channels),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(out_channels, out_channels)
        )

    def forward(self, x, edge_index, batch=None):
        # 多层图卷积
        x = F.relu(self.conv1(x, edge_index))
        x = F.dropout(x, p=0.3, training=self.training)
        x = F.relu(self.conv2(x, edge_index))
        x = F.dropout(x, p=0.3, training=self.training)
        x = self.conv3(x, edge_index)

        # 全局池化得到图级表示
        x = self.project(x)

        return x
```

#### 2.1.3 特征工程

```python
from dataclasses import dataclass
from typing import List, Dict
import numpy as np

@dataclass
class GraphFeatures:
    """图结构特征集合"""
    # 节点级特征
    embedding: np.ndarray           # 128维图嵌入
    centrality: float               # 中心性分数 (PageRank)
    betweenness: float              # 中介中心性
    clustering_coeff: float         # 聚类系数

    # 社区级特征
    community_id: int               # 所属社区
    community_size: int             # 社区大小
    community_density: float        # 社区密度

    # 网络级特征
    network_value: float            # 网络价值得分
    scarcity_score: float           # 稀缺性得分
    similarity_vector: np.ndarray   # 与竞品的相似度向量

class GraphFeatureExtractor:
    """图特征提取服务"""

    def __init__(self, neo4j_driver, embedding_model: AssetGraphEmbedding):
        self.driver = neo4j_driver
        self.model = embedding_model
        self.model.eval()

    async def extract_features(self, asset_id: str) -> GraphFeatures:
        """提取指定资产的完整图特征"""
        # 1. 从Neo4j获取子图
        subgraph = await self._get_subgraph(asset_id, depth=2)

        # 2. 计算图嵌入
        embedding = self._compute_embedding(subgraph)

        # 3. 计算拓扑特征
        centrality = await self._compute_centrality(asset_id)
        betweenness = await self._compute_betweenness(asset_id)
        clustering = await self._compute_clustering(asset_id)

        # 4. 社区发现
        community_info = await self._detect_community(asset_id)

        # 5. 网络价值
        network_value = self._calculate_network_value(
            embedding, centrality, community_info
        )

        # 6. 稀缺性分析
        scarcity = await self._analyze_scarcity(asset_id, embedding)

        return GraphFeatures(
            embedding=embedding,
            centrality=centrality,
            betweenness=betweenness,
            clustering_coeff=clustering,
            community_id=community_info['id'],
            community_size=community_info['size'],
            community_density=community_info['density'],
            network_value=network_value,
            scarcity_score=scarcity,
            similarity_vector=await self._compute_similarity_vector(asset_id)
        )

    async def _get_subgraph(self, asset_id: str, depth: int = 2) -> Dict:
        """获取资产的k-hop子图"""
        query = """
        MATCH path = (a:DataAsset {asset_id: $asset_id})-[:DERIVED_FROM|PROCESSED_BY|CONTAINS_ENTITY*1..%d]-(n)
        WITH a, n, length(path) as depth
        RETURN a, collect({node: n, depth: depth}) as neighbors
        """ % depth

        async with self.driver.session() as session:
            result = await session.run(query, asset_id=asset_id)
            record = await result.single()
            return self._build_subgraph(record)

    def _compute_embedding(self, subgraph: Dict) -> np.ndarray:
        """计算图嵌入"""
        # 构建PyG数据对象
        data = self._subgraph_to_pyg(subgraph)

        with torch.no_grad():
            embedding = self.model(data.x, data.edge_index)
            # 获取中心节点（资产节点）的嵌入
            asset_embedding = embedding[0].cpu().numpy()

        return asset_embedding
```

### 2.2 数据血缘驱动的定价模型

#### 2.2.1 血缘图特征

```python
@dataclass
class LineagePricingFeatures:
    """血缘相关的定价特征"""
    # 完整性特征
    lineage_depth: int              # 血缘链深度
    lineage_breadth: int            # 血缘树宽度
    lineage_completeness: float     # 血缘完整度 [0,1]

    # 质量传播特征
    upstream_quality_score: float   # 上游质量分数
    processing_quality_loss: float  # 处理过程质量损失
    overall_lineage_score: float    # 综合血缘分数

    # 风险特征
    upstream_risk_score: float      # 上游依赖风险
    single_point_failure: bool      # 是否存在单点故障
    alternative_sources: int        # 替代数据源数量

    # 价值特征
    derivation_complexity: float    # 派生复杂度
    lineage_uniqueness: float       # 血缘路径独特性
    data_provenance_score: float    # 数据溯源可信度

class LineageDrivenPricing:
    """血缘驱动定价引擎"""

    def __init__(self, lineage_tracker, quality_assessor):
        self.lineage_tracker = lineage_tracker
        self.quality_assessor = quality_assessor

    async def calculate_lineage_features(self, asset_id: str) -> LineagePricingFeatures:
        """计算血缘定价特征"""
        # 1. 获取血缘树
        tree = await self.lineage_tracker.get_lineage_tree(asset_id)

        # 2. 分析血缘结构
        depth = self._calculate_depth(tree)
        breadth = self._calculate_breadth(tree)
        completeness = self._assess_completeness(tree)

        # 3. 质量传播分析
        upstream_quality = await self._compute_upstream_quality(tree)
        quality_loss = self._estimate_quality_loss(tree)

        # 4. 风险分析
        risk_score = await self._compute_dependency_risk(tree)
        has_spf = self._detect_single_point_failure(tree)
        alternatives = await self._count_alternative_sources(asset_id)

        # 5. 价值分析
        complexity = self._calculate_derivation_complexity(tree)
        uniqueness = self._calculate_path_uniqueness(tree)
        provenance = self._calculate_provenance_score(tree)

        return LineagePricingFeatures(
            lineage_depth=depth,
            lineage_breadth=breadth,
            lineage_completeness=completeness,
            upstream_quality_score=upstream_quality,
            processing_quality_loss=quality_loss,
            overall_lineage_score=upstream_quality * (1 - quality_loss),
            upstream_risk_score=risk_score,
            single_point_failure=has_spf,
            alternative_sources=alternatives,
            derivation_complexity=complexity,
            lineage_uniqueness=uniqueness,
            data_provenance_score=provenance
        )

    def apply_lineage_adjustment(self, base_price: float, features: LineagePricingFeatures) -> float:
        """应用血缘调整到基础价格"""
        # 血缘质量乘数
        quality_multiplier = features.overall_lineage_score

        # 稀缺性乘数
        scarcity_multiplier = 1 + (1 / (1 + features.alternative_sources))

        # 风险调整（风险高则降价）
        risk_multiplier = 1 - (features.upstream_risk_score * 0.2)

        # 复杂度溢价
        complexity_multiplier = 1 + (features.derivation_complexity * 0.1)

        adjusted_price = base_price * quality_multiplier * scarcity_multiplier * risk_multiplier * complexity_multiplier

        return max(base_price * 0.5, min(base_price * 2.0, adjusted_price))
```

### 2.3 多维度特征联合建模

#### 2.3.1 特征定义

```python
from typing import TypedDict
import numpy as np

class MultiDimensionalFeatures(TypedDict):
    """多维度特征集合"""
    # 1. 图特征 (128维)
    graph_embedding: np.ndarray
    graph_topology: np.ndarray      # 拓扑特征 [中心性, 聚类系数, ...]

    # 2. 血缘特征 (12维)
    lineage_features: np.ndarray    # [深度, 宽度, 完整度, 质量分数, ...]

    # 3. 质量特征 (6维)
    quality_dimensions: np.ndarray  # [完整性, 准确性, 时效性, 一致性, 唯一性, 总体分]

    # 4. 市场特征 (32维)
    market_dynamics: np.ndarray     # 时序特征编码
    competition_vector: np.ndarray  # 竞品特征

    # 5. 权益特征 (8维)
    rights_features: np.ndarray     # 权益范围、期限、计算方式等编码

class FeatureFusionNetwork(nn.Module):
    """
    多维度特征融合网络
    使用DeepFM架构：结合FM（显式特征交互）和DNN（隐式高阶交互）
    """
    def __init__(self, field_dims: List[int], embed_dim: int = 16, mlp_dims: List[int] = [256, 128, 64]):
        super().__init__()

        # 各维度特征输入大小
        self.graph_dim = 128 + 8          # 图嵌入 + 拓扑
        self.lineage_dim = 12             # 血缘特征
        self.quality_dim = 6              # 质量特征
        self.market_dim = 32 + 16         # 市场动态 + 竞争
        self.rights_dim = 8               # 权益特征

        total_dim = self.graph_dim + self.lineage_dim + self.quality_dim + self.market_dim + self.rights_dim

        # FM部分（一阶+二阶交互）
        self.fm_first_order = nn.Linear(total_dim, 1)
        self.fm_embedding = nn.ModuleList([
            nn.Embedding(dim, embed_dim) for dim in field_dims
        ])

        # DNN部分（高阶隐式交互）
        layers = []
        input_dim = len(field_dims) * embed_dim
        for dim in mlp_dims:
            layers.append(nn.Linear(input_dim, dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(0.3))
            input_dim = dim
        layers.append(nn.Linear(input_dim, 1))
        self.mlp = nn.Sequential(*layers)

        # 特征投影层（将连续特征映射到embedding空间）
        self.graph_proj = nn.Sequential(
            nn.Linear(self.graph_dim, 64),
            nn.ReLU(),
            nn.Linear(64, embed_dim * 4)  # 4个field
        )
        self.lineage_proj = nn.Linear(self.lineage_dim, embed_dim)
        self.quality_proj = nn.Linear(self.quality_dim, embed_dim)
        self.market_proj = nn.Linear(self.market_dim, embed_dim * 2)  # 2个field
        self.rights_proj = nn.Linear(self.rights_dim, embed_dim)

    def forward(self, features: MultiDimensionalFeatures) -> torch.Tensor:
        # 特征投影
        graph_emb = self.graph_proj(features['graph_embedding'])
        lineage_emb = self.lineage_proj(features['lineage_features'])
        quality_emb = self.quality_proj(features['quality_dimensions'])
        market_emb = self.market_proj(features['market_dynamics'])
        rights_emb = self.rights_proj(features['rights_features'])

        # 拼接所有embeddings
        embeddings = torch.cat([
            graph_emb, lineage_emb, quality_emb, market_emb, rights_emb
        ], dim=-1)

        # FM一阶
        fm_first = self.fm_first_order(embeddings)

        # FM二阶（简化版）
        square_of_sum = torch.sum(embeddings, dim=1) ** 2
        sum_of_square = torch.sum(embeddings ** 2, dim=1)
        fm_second = 0.5 * (square_of_sum - sum_of_square).sum(dim=1, keepdim=True)

        # DNN部分
        dnn_output = self.mlp(embeddings)

        # 融合输出（基础价格预测）
        output = fm_first + fm_second + dnn_output

        return output
```

#### 2.3.2 联合训练框架

```python
class JointPricingModel:
    """
    联合定价模型
    同时预测：基础价格 + 置信度 + 成交概率分布
    """
    def __init__(self, feature_network: FeatureFusionNetwork):
        self.feature_network = feature_network

        # 多任务输出头
        self.price_head = nn.Sequential(
            nn.Linear(1, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Softplus()  # 确保价格>0
        )

        self.confidence_head = nn.Sequential(
            nn.Linear(1, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()  # 置信度 [0,1]
        )

        self.probability_head = nn.Sequential(
            nn.Linear(1, 64),
            nn.ReLU(),
            nn.Linear(64, 3),  # 三档价格的成交概率
            nn.Softmax(dim=-1)
        )

    def forward(self, features: MultiDimensionalFeatures):
        # 特征融合
        fused = self.feature_network(features)

        # 多任务预测
        base_price = self.price_head(fused)
        confidence = self.confidence_head(fused)
        deal_probs = self.probability_head(fused)

        return {
            'base_price': base_price,
            'confidence': confidence,
            'deal_probabilities': deal_probs  # [P10_prob, P50_prob, P90_prob]
        }

    def compute_loss(self, predictions, targets):
        """多任务损失函数"""
        # 价格回归损失
        price_loss = F.mse_loss(predictions['base_price'], targets['price'])

        # 置信度校准损失
        confidence_loss = F.binary_cross_entropy(
            predictions['confidence'],
            targets['price_accuracy']
        )

        # 成交概率分布损失
        prob_loss = F.kl_div(
            predictions['deal_probabilities'].log(),
            targets['empirical_distribution'],
            reduction='batchmean'
        )

        # 联合损失
        total_loss = price_loss + 0.5 * confidence_loss + 0.3 * prob_loss

        return total_loss
```

### 2.4 三档价格阈值机制

#### 2.4.1 价格分布建模

```python
from scipy import stats
import numpy as np
from dataclasses import dataclass

@dataclass
class PriceThresholds:
    """三档价格阈值"""
    conservative: float    # P10: 保守价，成交概率10%（卖方有利）
    moderate: float        # P50: 适中价，成交概率50%（公允价值）
    aggressive: float      # P90: 激进价，成交概率90%（买方有利）

    # 元信息
    confidence_interval: float  # 置信区间宽度
    distribution_type: str      # 价格分布类型

class PriceDistributionEstimator:
    """价格分布估计器"""

    def __init__(self):
        self.distribution_families = {
            'lognormal': stats.lognorm,
            'gamma': stats.gamma,
            'weibull': stats.weibull_min,
            'normal': stats.norm
        }

    async def estimate_distribution(
        self,
        asset_features: MultiDimensionalFeatures,
        comparable_transactions: List[Dict]
    ) -> PriceThresholds:
        """
        基于特征和可比交易估计价格分布
        """
        # 1. 获取可比交易价格
        prices = [tx['price'] for tx in comparable_transactions]

        # 2. 如果没有历史数据，基于特征预测
        if len(prices) < 5:
            return await self._estimate_from_features(asset_features)

        # 3. 拟合最佳分布
        best_dist, params = self._fit_distribution(prices)

        # 4. 计算三档阈值
        p10 = best_dist.ppf(0.10, *params)  # 10%分位数（高价区）
        p50 = best_dist.ppf(0.50, *params)  # 中位数
        p90 = best_dist.ppf(0.90, *params)  # 90%分位数（低价区）

        # 5. 根据当前市场条件调整
        market_adjustment = self._compute_market_adjustment(asset_features)

        return PriceThresholds(
            conservative=p10 * market_adjustment,
            moderate=p50 * market_adjustment,
            aggressive=p90 * market_adjustment,
            confidence_interval=(p90 - p10) / p50,
            distribution_type=best_dist.name
        )

    async def _estimate_from_features(
        self,
        features: MultiDimensionalFeatures
    ) -> PriceThresholds:
        """基于特征预测价格（冷启动）"""
        # 使用联合模型预测基础价格
        base_price = self.joint_model.predict_base_price(features)

        # 根据特征不确定性估计分布宽度
        uncertainty = self._compute_uncertainty(features)

        # 假设对数正态分布
        log_mean = np.log(base_price)
        log_std = uncertainty

        conservative = np.exp(log_mean + 1.28 * log_std)  # ~90th percentile
        moderate = base_price
        aggressive = np.exp(log_mean - 1.28 * log_std)    # ~10th percentile

        return PriceThresholds(
            conservative=conservative,
            moderate=moderate,
            aggressive=aggressive,
            confidence_interval=uncertainty * 2.56,  # 1.28 * 2
            distribution_type='lognormal_predicted'
        )

    def _fit_distribution(self, prices: List[float]) -> Tuple[stats.rv_continuous, Tuple]:
        """拟合最佳分布"""
        best_aic = float('inf')
        best_dist = None
        best_params = None

        for name, dist in self.distribution_families.items():
            try:
                params = dist.fit(prices)
                # 计算AIC
                log_likelihood = np.sum(dist.logpdf(prices, *params))
                k = len(params)
                aic = 2 * k - 2 * log_likelihood

                if aic < best_aic:
                    best_aic = aic
                    best_dist = dist
                    best_params = params
            except Exception:
                continue

        return best_dist or stats.norm, best_params or (np.mean(prices), np.std(prices))

class ThresholdWithConfidence:
    """带置信度的价格阈值"""

    def __init__(self, thresholds: PriceThresholds, confidence: float):
        self.thresholds = thresholds
        self.confidence = confidence

    def select_threshold(self, strategy: str = "auto") -> float:
        """
        根据策略和置信度选择价格

        Args:
            strategy: "conservative" | "moderate" | "aggressive" | "auto"
        """
        if strategy == "conservative":
            return self.thresholds.conservative
        elif strategy == "aggressive":
            return self.thresholds.aggressive
        elif strategy == "moderate":
            return self.thresholds.moderate
        else:  # auto
            # 根据置信度动态选择
            if self.confidence >= 0.8:
                return self.thresholds.conservative
            elif self.confidence >= 0.5:
                return self.thresholds.moderate
            else:
                return self.thresholds.aggressive
```

### 2.5 Agent博弈与让步策略

#### 2.5.1 对手建模

```python
from collections import deque
from typing import Dict, List, Optional
import numpy as np

class OpponentModel:
    """
    对手建模器
    估计对手的价格敏感度、时间偏好、BATNA（最佳替代方案）
    """

    def __init__(self, opponent_id: str):
        self.opponent_id = opponent_id

        # 历史出价序列
        self.offer_history: deque = deque(maxlen=20)
        self.response_history: deque = deque(maxlen=20)

        # 模型参数
        self.price_sensitivity: float = 0.5  # [0,1], 越高越敏感
        self.time_pressure: float = 0.5      # [0,1], 越高越急于成交
        self.patience: float = 0.5           # [0,1], 越高愿意协商越久

        # 估计的BATNA
        self.estimated_batna: Optional[float] = None

        # 行为模式
        self.concession_pattern: List[float] = []
        self.is_strategic: bool = True       # 是否策略性出价

    def record_interaction(self, offer: float, response: str, round_num: int):
        """记录一次交互"""
        self.offer_history.append({
            'offer': offer,
            'response': response,
            'round': round_num,
            'timestamp': time.time()
        })

        # 更新让步模式
        if len(self.offer_history) >= 2:
            prev_offer = self.offer_history[-2]['offer']
            concession = abs(offer - prev_offer) / prev_offer
            self.concession_pattern.append(concession)

    def update_model(self):
        """基于历史更新对手模型"""
        if len(self.offer_history) < 3:
            return

        # 分析让步模式
        if len(self.concession_pattern) >= 2:
            # 计算让步速度
            avg_concession = np.mean(self.concession_pattern)

            if avg_concession > 0.15:
                self.patience = 0.3  # 快速让步 = 低耐心
            elif avg_concession > 0.05:
                self.patience = 0.6
            else:
                self.patience = 0.9  # 慢速让步 = 高耐心

        # 估计价格敏感度
        price_variance = np.var([h['offer'] for h in self.offer_history])
        self.price_sensitivity = min(1.0, price_variance / 1000)

        # 估计BATNA（保留价格）
        offers = [h['offer'] for h in self.offer_history]
        if self._is_seller():
            self.estimated_batna = min(offers) * 0.9
        else:
            self.estimated_batna = max(offers) * 1.1

    def predict_acceptance_probability(self, price: float, round_num: int) -> float:
        """预测对手接受价格的概率"""
        if self.estimated_batna is None:
            return 0.5

        # 基于价格差距计算
        if self._is_seller():
            # 卖方：价格越高越可能接受
            gap = (price - self.estimated_batna) / self.estimated_batna
        else:
            # 买方：价格越低越可能接受
            gap = (self.estimated_batna - price) / self.estimated_batna

        # 逻辑函数映射
        base_prob = 1 / (1 + np.exp(-5 * gap))

        # 时间压力调整（越到后期越可能接受）
        time_factor = 1 + (self.time_pressure * round_num / 10)

        return min(1.0, base_prob * time_factor)

    def predict_counter_offer(self, current_offer: float) -> float:
        """预测对手的反报价"""
        if not self.offer_history:
            return current_offer * 0.9 if self._is_seller() else current_offer * 1.1

        # 基于历史让步模式
        avg_concession = np.mean(self.concession_pattern) if self.concession_pattern else 0.1

        if self._is_seller():
            return current_offer * (1 - avg_concession)
        else:
            return current_offer * (1 + avg_concession)
```

#### 2.5.2 强化学习决策

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple

class NegotiationState:
    """协商状态表示"""
    def __init__(self,
                 current_price: float,
                 round_num: int,
                 max_rounds: int,
                 price_thresholds: PriceThresholds,
                 opponent_model: OpponentModel,
                 my_reserve_price: float,
                 time_pressure: float):
        self.current_price = current_price
        self.round_num = round_num
        self.max_rounds = max_rounds
        self.price_thresholds = price_thresholds
        self.opponent_model = opponent_model
        self.my_reserve_price = my_reserve_price
        self.time_pressure = time_pressure

    def to_tensor(self) -> torch.Tensor:
        """转换为神经网络输入"""
        return torch.tensor([
            self.current_price / 1000,  # 归一化
            self.round_num / self.max_rounds,
            self.price_thresholds.conservative / 1000,
            self.price_thresholds.moderate / 1000,
            self.price_thresholds.aggressive / 1000,
            self.opponent_model.price_sensitivity,
            self.opponent_model.patience,
            self.my_reserve_price / 1000,
            self.time_pressure,
        ], dtype=torch.float32)

class NegotiationPolicy(nn.Module):
    """
    协商策略网络 (Actor-Critic架构)
    """
    def __init__(self, state_dim: int = 9, action_dim: int = 5):
        super().__init__()

        # Actor网络（策略）
        self.actor = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, action_dim),
            nn.Softmax(dim=-1)
        )

        # Critic网络（价值）
        self.critic = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, 1)
        )

        # 动作空间定义
        self.actions = ['accept', 'reject', 'counter_conservative', 'counter_moderate', 'counter_aggressive']

    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        action_probs = self.actor(state)
        state_value = self.critic(state)
        return action_probs, state_value

    def select_action(self, state: NegotiationState) -> Tuple[str, float]:
        """选择动作并返回置信度"""
        state_tensor = state.to_tensor().unsqueeze(0)

        with torch.no_grad():
            action_probs, _ = self.forward(state_tensor)

        # 采样动作
        action_idx = torch.multinomial(action_probs, 1).item()
        confidence = action_probs[0][action_idx].item()

        return self.actions[action_idx], confidence

class ConcessionStrategy:
    """
    让步策略优化器
    基于时间压力和替代方案动态调整让步曲线
    """

    def __init__(self,
                 initial_price: float,
                 reserve_price: float,
                 max_rounds: int,
                 concession_type: str = "logarithmic"):
        self.initial_price = initial_price
        self.reserve_price = reserve_price
        self.max_rounds = max_rounds
        self.concession_type = concession_type

        # 效用函数参数
        self.risk_aversion = 0.5
        self.time_discount = 0.95  # 每轮时间折扣

    def calculate_concession_curve(self) -> List[float]:
        """计算让步曲线"""
        curve = []

        for t in range(self.max_rounds + 1):
            progress = t / self.max_rounds

            if self.concession_type == "linear":
                alpha = progress
            elif self.concession_type == "logarithmic":
                # 先慢后快
                alpha = np.log(1 + progress * 9) / np.log(10)
            elif self.concession_type == "exponential":
                # 先快后慢
                alpha = 1 - np.exp(-3 * progress)
            elif self.concession_type == "boulware":
                # Boulware策略：坚定到最后才让步
                alpha = progress ** 4
            elif self.concession_type == "conceder":
                # Conceder策略：早期快速让步
                alpha = 1 - (1 - progress) ** 3
            else:
                alpha = progress

            price = self.initial_price + alpha * (self.reserve_price - self.initial_price)
            curve.append(price)

        return curve

    def get_round_price(self, round_num: int, time_pressure: float = 0.5) -> float:
        """获取指定轮次的价格"""
        curve = self.calculate_concession_curve()
        base_price = curve[min(round_num, self.max_rounds)]

        # 时间压力调整
        if time_pressure > 0.5:
            # 压力高，向reserve price靠拢
            adjustment = (self.reserve_price - base_price) * (time_pressure - 0.5)
            return base_price + adjustment

        return base_price

    def calculate_utility(self, price: float, round_num: int) -> float:
        """计算给定价格的效用"""
        # 价格效用（离目标越近效用越高）
        if self._is_seller():
            price_utility = (price - self.reserve_price) / (self.initial_price - self.reserve_price)
        else:
            price_utility = (self.reserve_price - price) / (self.reserve_price - self.initial_price)

        # 时间效用（越早成交效用越高）
        time_utility = self.time_discount ** round_num

        # 综合效用
        utility = price_utility * 0.7 + time_utility * 0.3

        return max(0, utility)

class AutonomousNegotiationAgent:
    """
    自主协商Agent
    整合所有组件实现智能博弈
    """

    def __init__(self,
                 policy: NegotiationPolicy,
                 pricing_engine: JointPricingModel,
                 is_seller: bool = True):
        self.policy = policy
        self.pricing_engine = pricing_engine
        self.is_seller = is_seller

        self.opponent_models: Dict[str, OpponentModel] = {}
        self.concession_strategies: Dict[str, ConcessionStrategy] = {}

    async def negotiate_round(self,
                              negotiation_id: str,
                              opponent_id: str,
                              current_offer: float,
                              round_num: int,
                              asset_features: MultiDimensionalFeatures) -> Dict:
        """
        执行一轮协商
        """
        # 1. 获取或创建对手模型
        if opponent_id not in self.opponent_models:
            self.opponent_models[opponent_id] = OpponentModel(opponent_id)
        opponent = self.opponent_models[opponent_id]

        # 2. 更新对手模型
        opponent.record_interaction(current_offer, "pending", round_num)
        opponent.update_model()

        # 3. 计算价格阈值
        thresholds = await self._calculate_thresholds(asset_features)

        # 4. 构建当前状态
        reserve_price = thresholds.conservative if self.is_seller else thresholds.aggressive
        state = NegotiationState(
            current_price=current_offer,
            round_num=round_num,
            max_rounds=10,
            price_thresholds=thresholds,
            opponent_model=opponent,
            my_reserve_price=reserve_price,
            time_pressure=self._calculate_time_pressure(round_num, opponent)
        )

        # 5. 策略网络决策
        action, confidence = self.policy.select_action(state)

        # 6. 执行决策
        if action == 'accept':
            return await self._execute_accept(negotiation_id, current_offer)
        elif action == 'reject':
            return await self._execute_reject(negotiation_id)
        else:  # counter
            counter_price = self._calculate_counter_price(action, state)
            return await self._execute_counter(negotiation_id, counter_price, confidence)

    def _calculate_counter_price(self, action: str, state: NegotiationState) -> float:
        """计算反报价"""
        if action == 'counter_conservative':
            base = state.price_thresholds.conservative
        elif action == 'counter_moderate':
            base = state.price_thresholds.moderate
        else:  # aggressive
            base = state.price_thresholds.aggressive

        # 根据对手模型微调
        if state.opponent_model.predict_acceptance_probability(base, state.round_num) < 0.3:
            # 预测接受概率低，向对手预期靠拢
            predicted_counter = state.opponent_model.predict_counter_offer(state.current_price)
            base = (base + predicted_counter) / 2

        return round(base, 2)

    def _calculate_time_pressure(self, round_num: int, opponent: OpponentModel) -> float:
        """计算时间压力"""
        # 基于轮次进度
        round_pressure = round_num / 10

        # 基于对手行为
        opponent_pressure = opponent.time_pressure

        # 综合压力
        return 0.6 * round_pressure + 0.4 * opponent_pressure
```

## 3. 系统数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                        定价请求流程                              │
└─────────────────────────────────────────────────────────────────┘

用户请求定价
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. 特征收集阶段 (Feature Collection)                          │
│    ├─ 从Neo4j获取资产知识图谱子图                              │
│    ├─ 从Lineage服务获取血缘树                                  │
│    ├─ 从Quality服务获取质量评分                                │
│    ├─ 从Market服务获取竞品和交易数据                           │
│    └─ 从Rights服务获取权益范围                                 │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. 并行特征提取 (Parallel Feature Extraction)                 │
│    ├─ Graph Feature Extractor (GNN推理)                       │
│    ├─ Lineage Feature Calculator                              │
│    ├─ Market Dynamics Analyzer                                │
│    └─ Quality Dimension Aggregator                            │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. 特征融合与建模 (Feature Fusion)                            │
│    ├─ DeepFM联合建模网络前向传播                              │
│    ├─ 输出: 基础价格 + 置信度 + 成交概率分布                  │
│    └─ 缓存结果到Redis                                         │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. 阈值生成 (Threshold Generation)                            │
│    ├─ 拟合价格分布 (或基于置信度推断)                         │
│    ├─ 计算 P10 / P50 / P90 三档阈值                           │
│    └─ 应用市场调整因子                                        │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. 结果组装 (Result Assembly)                                 │
│    ├─ 三档价格 + 置信度分数                                   │
│    ├─ 特征解释 (为什么是这个价格)                              │
│    ├─ 市场定位分析                                            │
│    └─ 推荐策略 (保守/适中/激进)                                │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
返回定价结果给用户


┌─────────────────────────────────────────────────────────────────┐
│                       协商博弈流程                               │
└─────────────────────────────────────────────────────────────────┘

收到对方出价
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 1. 状态更新 (State Update)                                    │
│    ├─ 记录对方出价历史                                        │
│    ├─ 更新对手模型                                            │
│    └─ 重新评估时间压力                                        │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. 决策推理 (Decision Making)                                 │
│    ├─ 构建当前协商状态向量                                    │
│    ├─ Policy Network前向传播                                  │
│    ├─ 采样或贪心选择动作                                      │
│    └─ (训练时) 存储Transition到Replay Buffer                 │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. 动作执行 (Action Execution)                                │
│    ├─ Accept: 达成交易，记录结果                               │
│    ├─ Reject: 终止协商，记录原因                               │
│    └─ Counter: 计算具体反报价，发送给对方                      │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
返回协商动作
```

## 4. 技术实现路线图

### Phase 1: 基础架构 (2周)
- [ ] GraphSAGE模型训练pipeline
- [ ] 特征提取服务实现
- [ ] 基础DeepFM模型
- [ ] 三档阈值生成器

### Phase 2: 血缘集成 (1周)
- [ ] LineageGraph特征计算
- [ ] 质量传播模型
- [ ] 血缘-定价联动

### Phase 3: 博弈系统 (2周)
- [ ] 对手建模器
- [ ] 策略网络(PPO/A3C)
- [ ] 让步策略优化
- [ ] 模拟训练环境

### Phase 4: 部署优化 (1周)
- [ ] 模型ONNX导出
- [ ] 推理加速(TensorRT)
- [ ] 缓存策略
- [ ] A/B测试框架

## 5. 关键技术指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 定价延迟 | <200ms | 99分位延迟 |
| 协商响应 | <100ms | 单轮决策时间 |
| 价格准确率 | >85% | 与最终成交价偏差<15% |
| 成交率提升 | +20% | 相比固定定价 |
| 模型AUC | >0.8 | 成交概率预测 |

---

*文档版本: 1.0*
*最后更新: 2026-04-11*
