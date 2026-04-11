# Graph Neural Network (GNN) Module for Asset Pricing

基于PyTorch Geometric的图神经网络模块，为数据资产定价提供知识图谱嵌入和图特征提取能力。

## 目录结构

```
gnn/
├── __init__.py                 # 模块入口
├── models/                     # 模型定义
│   ├── graphsage.py           # GraphSAGE模型
│   ├── encoders.py            # 节点/边编码器
│   └── __init__.py
├── data/                       # 数据加载
│   ├── neo4j_loader.py        # Neo4j数据加载器
│   ├── pyg_dataset.py         # PyG数据集
│   └── __init__.py
├── inference/                  # 推理服务
│   ├── embedder.py            # 嵌入推理服务
│   └── __init__.py
├── training/                   # 训练
│   ├── trainer.py             # 训练器
│   └── __init__.py
├── example_usage.py           # 使用示例
└── README.md                  # 本文档
```

## 核心特性

### 1. GraphSAGE模型

- **归纳学习**: 新节点无需重训练
- **多聚合方式**: mean, max, LSTM, attention
- **跳跃连接**: Jumping Knowledge聚合多层表示
- **多任务学习**: 同时学习嵌入、价格预测、稀缺性分类

### 2. 特征编码

- **节点编码**: 支持DataAsset/DataSource/Entity等多种节点类型
- **边编码**: 支持多种关系类型
- **时间编码**: 循环编码处理时间特征
- **自动归一化**: FeatureNormalizer处理数值特征

### 3. 数据加载

- **Neo4j集成**: 异步从Neo4j加载子图
- **采样策略**: k-hop子图采样
- **正负样本**: 支持对比学习采样
- **缓存机制**: 本地缓存避免重复查询

### 4. 推理服务

- **单例模式**: 全局共享模型实例
- **嵌入缓存**: LRU缓存降低延迟
- **批量推理**: 支持批量资产嵌入
- **特征提取**: 拓扑特征+网络价值计算

## 快速开始

### 安装依赖

```bash
pip install torch torch-geometric neo4j numpy
```

### 训练模型

```python
from app.services.gnn.training.trainer import GraphSAGETrainer, TrainingConfig

config = TrainingConfig(
    in_channels=128,
    hidden_channels=256,
    out_channels=128,
    num_epochs=100,
)

trainer = GraphSAGETrainer(config, train_dataset, val_dataset)
history = trainer.train()
```

### 推理嵌入

```python
from app.services.gnn.inference.embedder import AssetGraphEmbedder

embedder = AssetGraphEmbedder(
    model_path="./checkpoints/best.pt",
    neo4j_driver=neo4j_driver,
    node_encoder=NodeEncoder(),
    edge_encoder=EdgeEncoder(),
)

# 获取单个资产嵌入
embedding = await embedder.embed("asset_001")

# 批量获取
embeddings = await embedder.embed_batch(["asset_001", "asset_002"])
```

### 特征提取

```python
from app.services.gnn.inference.embedder import GraphFeatureExtractor

extractor = GraphFeatureExtractor(embedder)
features = await extractor.extract_features("asset_001")

# features = {
#     "embedding": np.ndarray,      # 128-dim
#     "network_value": float,       # 网络价值
#     "scarcity_score": float,      # 稀缺性
#     "centrality": float,          # 中心性
#     ...
# }
```

## 与PricingSkill集成

```python
from app.services.skills.pricing_skill import PricingSkill
from app.services.gnn.inference.embedder import AssetGraphEmbedder

class EnhancedPricingSkill(PricingSkill):
    def __init__(self, db, graph_embedder: AssetGraphEmbedder):
        super().__init__(db)
        self.graph_embedder = graph_embedder
        self.feature_extractor = GraphFeatureExtractor(graph_embedder)

    async def calculate_price(self, asset_id: str) -> Dict:
        # 1. 获取图特征
        graph_features = await self.feature_extractor.extract_features(asset_id)

        # 2. 与其他特征融合
        lineage_features = await self._get_lineage_features(asset_id)
        quality_features = await self._get_quality_features(asset_id)
        market_features = await self._get_market_features(asset_id)

        # 3. 联合建模
        fused = self._fuse_features(
            graph_features,
            lineage_features,
            quality_features,
            market_features
        )

        # 4. 价格预测
        price = self.pricing_model.predict(fused)

        return {
            "price": price,
            "graph_embedding": graph_features["embedding"],
            "network_value": graph_features["network_value"],
        }
```

## 模型配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| in_channels | 128 | 输入特征维度 |
| hidden_channels | 256 | 隐藏层维度 |
| out_channels | 128 | 输出嵌入维度 |
| num_layers | 3 | SAGE卷积层数 |
| dropout | 0.3 | Dropout概率 |
| aggregation | "mean" | 邻居聚合方式 |
| graph_pooling | "attention" | 图级池化方式 |

## 性能指标

- **推理延迟**: <50ms (单资产)
- **批处理吞吐量**: >100 assets/sec (batch_size=32)
- **内存占用**: ~500MB (模型+缓存)
- **嵌入维度**: 128-dim (可配置)

## TODO

- [ ] 实现Graph Attention Network (GAT)变体
- [ ] 支持异构图 (Heterogeneous Graph)
- [ ] 模型量化加速推理
- [ ] 在线学习 (Online Learning)
- [ ] 模型可解释性 (GNNExplainer)

## 参考

- GraphSAGE: [Inductive Representation Learning on Large Graphs](https://arxiv.org/abs/1706.02216)
- PyTorch Geometric: https://pytorch-geometric.readthedocs.io/
