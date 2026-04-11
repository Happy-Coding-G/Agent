"""
Graph Embedding Module Usage Example

展示如何使用GNN模块进行图嵌入训练和推理
"""

import asyncio
import torch
import numpy as np
from pathlib import Path

# 导入GNN模块
from app.services.gnn.models.graphsage import AssetGraphSAGE, MultiTaskGraphSAGE
from app.services.gnn.models.encoders import NodeEncoder, EdgeEncoder
from app.services.gnn.data.neo4j_loader import Neo4jGraphLoader, AssetSubgraphSampler
from app.services.gnn.inference.embedder import AssetGraphEmbedder, GraphFeatureExtractor
from app.services.gnn.training.trainer import GraphSAGETrainer, TrainingConfig


async def example_train():
    """训练示例"""
    print("=" * 60)
    print("GraphSAGE Training Example")
    print("=" * 60)

    # 1. 配置训练
    config = TrainingConfig(
        in_channels=128,
        hidden_channels=256,
        out_channels=128,
        num_layers=3,
        dropout=0.3,
        batch_size=32,
        learning_rate=1e-3,
        num_epochs=50,
        checkpoint_dir="./checkpoints/graphsage",
        log_dir="./logs/graphsage",
    )

    # 2. 初始化编码器
    node_encoder = NodeEncoder()
    edge_encoder = EdgeEncoder()

    print(f"Node feature dimension: {node_encoder.feature_dim}")
    print(f"Edge feature dimension: {edge_encoder.feature_dim}")

    # 3. 创建数据集（这里简化，实际应从Neo4j加载）
    # train_dataset = AssetGraphDataset(
    #     root="./data/graph_train",
    #     neo4j_loader=neo4j_loader,
    #     asset_ids=["asset_001", "asset_002", ...],
    # )

    # 4. 训练模型
    # trainer = GraphSAGETrainer(config, train_dataset, val_dataset)
    # history = trainer.train()

    print("\nTraining configuration:")
    print(f"  Hidden channels: {config.hidden_channels}")
    print(f"  Output dimension: {config.out_channels}")
    print(f"  Number of layers: {config.num_layers}")


async def example_inference():
    """推理示例"""
    print("\n" + "=" * 60)
    print("Graph Embedding Inference Example")
    print("=" * 60)

    # 1. 初始化模型（实际使用时从检查点加载）
    node_encoder = NodeEncoder()

    model = AssetGraphSAGE(
        in_channels=node_encoder.feature_dim,
        hidden_channels=256,
        out_channels=128,
        num_layers=3,
        dropout=0.0,
    )

    # 2. 模拟输入数据
    num_nodes = 10
    x = torch.randn(num_nodes, node_encoder.feature_dim)
    edge_index = torch.tensor([
        [0, 1, 1, 2, 2, 3, 3, 4, 4, 0, 5, 6, 6, 7, 7, 8, 8, 9, 9, 5],
        [1, 0, 2, 1, 3, 2, 4, 3, 0, 4, 6, 5, 7, 6, 8, 7, 9, 8, 5, 9],
    ], dtype=torch.long)

    # 3. 前向传播
    model.eval()
    with torch.no_grad():
        node_embeddings = model.get_node_embedding(x, edge_index)

    print(f"\nNode embeddings shape: {node_embeddings.shape}")
    print(f"Embedding dimension: {node_embeddings.shape[1]}")

    # 4. 计算图级嵌入（模拟batch）
    batch = torch.zeros(num_nodes, dtype=torch.long)  # 所有节点属于同一个图
    with torch.no_grad():
        graph_embedding = model.get_graph_embedding(x, edge_index, batch)

    print(f"Graph embedding shape: {graph_embedding.shape}")

    # 5. 计算相似度
    similarity = torch.cosine_similarity(
        node_embeddings[0].unsqueeze(0),
        node_embeddings[1].unsqueeze(0)
    )
    print(f"\nSimilarity between node 0 and 1: {similarity.item():.4f}")


async def example_pricing_integration():
    """与定价系统集成示例"""
    print("\n" + "=" * 60)
    print("Pricing Integration Example")
    print("=" * 60)

    # 1. 初始化嵌入服务
    # embedder = AssetGraphEmbedder(
    #     model_path="./checkpoints/graphsage/best.pt",
    #     neo4j_driver=neo4j_driver,
    #     node_encoder=NodeEncoder(),
    #     edge_encoder=EdgeEncoder(),
    # )

    # 2. 获取资产嵌入
    # asset_id = "asset_001"
    # embedding = await embedder.embed(asset_id)

    # 模拟嵌入
    embedding = np.random.randn(128).astype(np.float32)
    embedding = embedding / np.linalg.norm(embedding)

    print(f"Asset embedding shape: {embedding.shape}")
    print(f"Embedding norm: {np.linalg.norm(embedding):.4f}")

    # 3. 构建定价特征
    graph_features = {
        "embedding": embedding,
        "network_value": np.linalg.norm(embedding) * 10,
        "scarcity_score": 0.7,
        "centrality": 0.5,
        "community_density": 0.6,
    }

    print("\nPricing features:")
    for key, value in graph_features.items():
        if isinstance(value, np.ndarray):
            print(f"  {key}: {value.shape}")
        else:
            print(f"  {key}: {value:.4f}")

    # 4. 多维度特征融合
    # 与其他特征（血缘、质量、市场）融合
    lineage_features = np.random.randn(12).astype(np.float32)
    quality_features = np.random.randn(6).astype(np.float32)
    market_features = np.random.randn(32).astype(np.float32)

    fused_features = np.concatenate([
        embedding,           # 128-dim
        lineage_features,    # 12-dim
        quality_features,    # 6-dim
        market_features,     # 32-dim
    ])

    print(f"\nFused feature dimension: {fused_features.shape[0]}")

    # 5. 输入到定价模型
    # price_prediction = pricing_model.predict(fused_features)
    print("\nFeatures ready for pricing model input")


def example_contrastive_learning():
    """对比学习示例"""
    print("\n" + "=" * 60)
    print("Contrastive Learning Example")
    print("=" * 60)

    model = AssetGraphSAGE(
        in_channels=128,
        hidden_channels=256,
        out_channels=128,
        num_layers=3,
    )

    # 模拟数据
    anchor = torch.randn(32, 128)  # batch_size=32
    positive = anchor + torch.randn(32, 128) * 0.1  # 正样本（带噪声）
    negative = torch.randn(32, 128)  # 负样本（随机）

    # 计算对比损失
    loss = model.contrastive_loss(anchor, positive, negative, temperature=0.5)

    print(f"Contrastive loss: {loss.item():.4f}")


async def main():
    """主函数"""
    await example_train()
    await example_inference()
    await example_pricing_integration()
    example_contrastive_learning()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
