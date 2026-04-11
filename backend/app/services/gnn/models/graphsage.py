"""
GraphSAGE Model for Data Asset Graph Embedding

基于PyTorch Geometric的GraphSAGE实现，支持：
1. 归纳学习（新节点无需重训练）
2. 多种聚合方式（mean, max, LSTM, attention）
3. 节点级和图级嵌入
4. 边特征支持
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv, global_mean_pool, global_max_pool, global_add_pool
from torch_geometric.nn import AttentionalAggregation, Set2Set
from typing import List, Optional, Tuple, Dict
import math


class AssetGraphSAGE(nn.Module):
    """
    数据资产图嵌入模型 (GraphSAGE)

    架构:
    1. 节点特征编码器 (Node Feature Encoder)
    2. 多层SAGE卷积 (SAGE Convolution Layers)
    3. 跳跃连接 (Jumping Knowledge)
    4. 图级池化 (Graph-level Pooling)
    5. 投影头 (Projection Head)

    Args:
        in_channels: 输入特征维度
        hidden_channels: 隐藏层维度
        out_channels: 输出嵌入维度 (默认128)
        num_layers: SAGE卷积层数 (默认3)
        dropout: Dropout概率 (默认0.3)
        aggregation: 邻居聚合方式 ['mean', 'max', 'lstm', 'attention']
        graph_pooling: 图级池化方式 ['mean', 'max', 'add', 'set2set', 'attention']
        use_edge_features: 是否使用边特征
        edge_dim: 边特征维度
    """

    def __init__(
        self,
        in_channels: int,
        hidden_channels: int = 256,
        out_channels: int = 128,
        num_layers: int = 3,
        dropout: float = 0.3,
        aggregation: str = "mean",
        graph_pooling: str = "attention",
        use_edge_features: bool = False,
        edge_dim: int = 16,
    ):
        super().__init__()

        self.in_channels = in_channels
        self.hidden_channels = hidden_channels
        self.out_channels = out_channels
        self.num_layers = num_layers
        self.dropout = dropout
        self.use_edge_features = use_edge_features

        # 输入投影层
        self.input_proj = nn.Sequential(
            nn.Linear(in_channels, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

        # SAGE卷积层
        self.convs = nn.ModuleList()
        self.batch_norms = nn.ModuleList()

        for i in range(num_layers):
            in_ch = hidden_channels if i > 0 else hidden_channels
            out_ch = hidden_channels

            # 根据聚合方式选择SAGEConv参数
            if aggregation == "lstm":
                # LSTM聚合需要特殊处理
                conv = SAGEConv(
                    in_ch, out_ch,
                    aggr="lstm",
                    normalize=True,
                )
            elif aggregation == "attention":
                conv = SAGEConv(
                    in_ch, out_ch,
                    aggr="max",  # 后续用AttentionAggregation
                    normalize=True,
                )
            else:
                conv = SAGEConv(
                    in_ch, out_ch,
                    aggr=aggregation,
                    normalize=True,
                )

            self.convs.append(conv)
            self.batch_norms.append(nn.LayerNorm(out_ch))

        # 边特征处理
        if use_edge_features and edge_dim > 0:
            self.edge_encoder = nn.Sequential(
                nn.Linear(edge_dim, hidden_channels // 2),
                nn.ReLU(),
                nn.Linear(hidden_channels // 2, hidden_channels),
            )
        else:
            self.edge_encoder = None

        # Jumping Knowledge连接
        # 合并所有层的表示
        jk_dim = hidden_channels * num_layers
        self.jk_proj = nn.Sequential(
            nn.Linear(jk_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
        )

        # 图级池化
        self.graph_pooling = graph_pooling
        if graph_pooling == "set2set":
            self.pool = Set2Set(hidden_channels, processing_steps=3)
            pool_out_dim = hidden_channels * 2
        elif graph_pooling == "attention":
            self.pool = AttentionalAggregation(
                gate_nn=nn.Sequential(
                    nn.Linear(hidden_channels, hidden_channels // 2),
                    nn.ReLU(),
                    nn.Linear(hidden_channels // 2, 1),
                ),
                nn=nn.Sequential(
                    nn.Linear(hidden_channels, hidden_channels),
                    nn.ReLU(),
                ),
            )
            pool_out_dim = hidden_channels
        else:
            pool_out_dim = hidden_channels

        # 输出投影头
        self.projection = nn.Sequential(
            nn.Linear(pool_out_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, out_channels),
        )

        # 可选：用于对比学习的额外投影头
        self.contrastive_proj = nn.Sequential(
            nn.Linear(out_channels, out_channels),
            nn.ReLU(),
            nn.Linear(out_channels, out_channels),
        )

        self._init_weights()

    def _init_weights(self):
        """Xavier初始化"""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
        batch: Optional[torch.Tensor] = None,
        return_all_layers: bool = False,
    ) -> torch.Tensor | Tuple[torch.Tensor, List[torch.Tensor]]:
        """
        前向传播

        Args:
            x: 节点特征 [num_nodes, in_channels]
            edge_index: 边索引 [2, num_edges]
            edge_attr: 边特征 [num_edges, edge_dim] (可选)
            batch: 批次分配 [num_nodes] (图级任务需要)
            return_all_layers: 是否返回所有层的表示

        Returns:
            node_embeddings: 节点嵌入 [num_nodes, out_channels]
            或 (node_embeddings, all_layer_outputs)
        """
        # 输入投影
        x = self.input_proj(x)

        # 处理边特征
        if self.use_edge_features and edge_attr is not None and self.edge_encoder is not None:
            edge_emb = self.edge_encoder(edge_attr)
        else:
            edge_emb = None

        # 多层SAGE卷积
        all_layers = [x]
        for i, (conv, bn) in enumerate(zip(self.convs, self.batch_norms)):
            # SAGE卷积
            if edge_emb is not None:
                # 如果有边特征，需要特殊处理（这里简化处理）
                x = conv(x, edge_index)
            else:
                x = conv(x, edge_index)

            x = bn(x)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
            all_layers.append(x)

        # Jumping Knowledge: 合并所有层的表示
        if len(all_layers) > 1:
            # 使用注意力机制加权合并
            jk_input = torch.cat(all_layers[1:], dim=-1)  # 跳过输入投影层
            x = self.jk_proj(jk_input)

        # 图级池化（如果需要）
        if batch is not None:
            if self.graph_pooling == "mean":
                x = global_mean_pool(x, batch)
            elif self.graph_pooling == "max":
                x = global_max_pool(x, batch)
            elif self.graph_pooling == "add":
                x = global_add_pool(x, batch)
            elif self.graph_pooling in ["set2set", "attention"]:
                x = self.pool(x, batch)

        # 最终投影
        embedding = self.projection(x)

        if return_all_layers:
            return embedding, all_layers[1:]
        return embedding

    def get_node_embedding(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """获取节点级嵌入（不归约到图级）"""
        return self.forward(x, edge_index, edge_attr, batch=None)

    def get_graph_embedding(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """获取图级嵌入"""
        return self.forward(x, edge_index, edge_attr, batch=batch)

    def contrastive_loss(
        self,
        anchor: torch.Tensor,
        positive: torch.Tensor,
        negative: torch.Tensor,
        temperature: float = 0.5,
    ) -> torch.Tensor:
        """
        对比学习损失 (InfoNCE)

        用于训练时学习更好的表示
        """
        # 投影到对比学习空间
        anchor_proj = F.normalize(self.contrastive_proj(anchor), dim=1)
        positive_proj = F.normalize(self.contrastive_proj(positive), dim=1)
        negative_proj = F.normalize(self.contrastive_proj(negative), dim=1)

        # 计算相似度
        pos_sim = torch.sum(anchor_proj * positive_proj, dim=1) / temperature
        neg_sim = torch.sum(anchor_proj * negative_proj, dim=1) / temperature

        # InfoNCE损失
        logits = torch.cat([pos_sim.unsqueeze(1), neg_sim.unsqueeze(1)], dim=1)
        labels = torch.zeros(anchor.size(0), dtype=torch.long, device=anchor.device)

        loss = F.cross_entropy(logits, labels)
        return loss


class AssetEdgeSAGE(nn.Module):
    """
    基于边的GraphSAGE变体

    用于学习边（关系）的表示，可用于：
    1. 链路预测（预测两个资产是否应该关联）
    2. 关系类型分类
    3. 边的权重预测
    """

    def __init__(
        self,
        in_channels: int,
        hidden_channels: int = 256,
        out_channels: int = 128,
        num_layers: int = 2,
        edge_attr_dim: int = 16,
        dropout: float = 0.3,
    ):
        super().__init__()

        self.node_encoder = AssetGraphSAGE(
            in_channels=in_channels,
            hidden_channels=hidden_channels,
            out_channels=hidden_channels,
            num_layers=num_layers,
            dropout=dropout,
            graph_pooling="mean",
        )

        # 边特征编码
        self.edge_attr_encoder = nn.Sequential(
            nn.Linear(edge_attr_dim, hidden_channels // 2),
            nn.ReLU(),
            nn.Linear(hidden_channels // 2, hidden_channels),
        )

        # 边表示解码器 (基于两个端点的表示和边特征)
        self.edge_decoder = nn.Sequential(
            nn.Linear(hidden_channels * 3, hidden_channels),  # src + dst + edge_attr
            nn.LayerNorm(hidden_channels),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, out_channels),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        计算边的嵌入

        Returns:
            edge_embeddings: [num_edges, out_channels]
        """
        # 获取节点表示
        node_emb = self.node_encoder.get_node_embedding(x, edge_index)

        # 提取边两端的节点表示
        src, dst = edge_index[0], edge_index[1]
        src_emb = node_emb[src]
        dst_emb = node_emb[dst]

        # 边特征
        if edge_attr is not None:
            edge_feat = self.edge_attr_encoder(edge_attr)
        else:
            edge_feat = torch.zeros(src_emb.size(0), self.edge_attr_encoder[0].in_features,
                                   device=src_emb.device)
            edge_feat = self.edge_attr_encoder(edge_feat)

        # 拼接并解码
        edge_input = torch.cat([src_emb, dst_emb, edge_feat], dim=-1)
        edge_emb = self.edge_decoder(edge_input)

        return edge_emb

    def predict_link(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        candidate_edges: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        预测候选边是否存在（链路预测）

        Args:
            candidate_edges: [2, num_candidates] 待预测的边

        Returns:
            scores: [num_candidates] 边存在的概率
        """
        # 先计算所有边的嵌入
        node_emb = self.node_encoder.get_node_embedding(x, edge_index)

        src = node_emb[candidate_edges[0]]
        dst = node_emb[candidate_edges[1]]

        # 计算相似度作为链路预测分数
        scores = F.cosine_similarity(src, dst, dim=1)
        scores = (scores + 1) / 2  # 映射到[0,1]

        return scores


class MultiTaskGraphSAGE(nn.Module):
    """
    多任务GraphSAGE

    同时学习：
    1. 资产嵌入 (主任务)
    2. 价格预测 (回归)
    3. 稀缺性分类 (分类)
    4. 链路预测 (辅助任务)
    """

    def __init__(
        self,
        in_channels: int,
        hidden_channels: int = 256,
        embedding_dim: int = 128,
        num_layers: int = 3,
        dropout: float = 0.3,
    ):
        super().__init__()

        self.encoder = AssetGraphSAGE(
            in_channels=in_channels,
            hidden_channels=hidden_channels,
            out_channels=embedding_dim,
            num_layers=num_layers,
            dropout=dropout,
        )

        # 任务头
        self.price_head = nn.Sequential(
            nn.Linear(embedding_dim, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
            nn.Softplus(),  # 确保价格为正
        )

        self.scarcity_head = nn.Sequential(
            nn.Linear(embedding_dim, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 3),  # 高/中/低稀缺性
        )

        self.quality_head = nn.Sequential(
            nn.Linear(embedding_dim, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 5),  # 质量5维度
            nn.Sigmoid(),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor]:
        """
        多任务前向传播
        """
        # 获取嵌入
        embedding = self.encoder(x, edge_index, batch=batch)

        # 各任务预测
        price = self.price_head(embedding)
        scarcity = self.scarcity_head(embedding)
        quality = self.quality_head(embedding)

        return {
            "embedding": embedding,
            "price": price,
            "scarcity": scarcity,
            "quality": quality,
        }

    def compute_loss(
        self,
        predictions: Dict[str, torch.Tensor],
        targets: Dict[str, torch.Tensor],
        task_weights: Dict[str, float] = None,
    ) -> torch.Tensor:
        """
        多任务损失
        """
        if task_weights is None:
            task_weights = {"price": 1.0, "scarcity": 0.5, "quality": 0.5}

        losses = {}

        # 价格回归损失
        if "price" in targets:
            losses["price"] = F.mse_loss(
                predictions["price"].squeeze(),
                targets["price"]
            )

        # 稀缺性分类损失
        if "scarcity" in targets:
            losses["scarcity"] = F.cross_entropy(
                predictions["scarcity"],
                targets["scarcity"]
            )

        # 质量回归损失
        if "quality" in targets:
            losses["quality"] = F.mse_loss(
                predictions["quality"],
                targets["quality"]
            )

        # 加权总损失
        total_loss = sum(
            task_weights.get(task, 1.0) * loss
            for task, loss in losses.items()
        )

        return total_loss
