"""
Neo4j Graph Data Loader

从Neo4j加载图数据并转换为PyTorch Geometric格式
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import torch
from torch_geometric.data import Data, Batch
import logging

logger = logging.getLogger(__name__)


class Neo4jGraphLoader:
    """
    Neo4j图数据加载器

    负责：
    1. 从Neo4j查询图结构
    2. 节点/边特征编码
    3. 构建PyG Data对象
    """

    def __init__(
        self,
        neo4j_driver,
        node_encoder,
        edge_encoder,
        max_hops: int = 2,
        max_nodes: int = 1000,
    ):
        self.driver = neo4j_driver
        self.node_encoder = node_encoder
        self.edge_encoder = edge_encoder
        self.max_hops = max_hops
        self.max_nodes = max_nodes

    async def load_asset_subgraph(
        self,
        asset_id: str,
        node_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
    ) -> Optional[Data]:
        """
        加载指定资产的k-hop子图

        Args:
            asset_id: 资产ID
            node_types: 限制的节点类型
            relation_types: 限制的关系类型

        Returns:
            PyG Data对象
        """
        try:
            # 1. 查询子图
            subgraph_data = await self._query_subgraph(
                asset_id, node_types, relation_types
            )

            if not subgraph_data or not subgraph_data.get("nodes"):
                logger.warning(f"No subgraph found for asset {asset_id}")
                return None

            # 2. 构建节点映射和特征
            node_mapping = {}  # neo4j_id -> index
            node_features = []
            node_types_list = []

            for idx, node in enumerate(subgraph_data["nodes"]):
                neo4j_id = node.get("id")
                node_mapping[neo4j_id] = idx

                # 编码节点特征
                node_feat = self.node_encoder.encode(node.get("properties", {}))
                node_features.append(node_feat)
                node_types_list.append(node.get("type", "Unknown"))

            # 3. 构建边索引和特征
            edge_list = []
            edge_features = []

            for edge in subgraph_data.get("edges", []):
                src_id = edge.get("source")
                dst_id = edge.get("target")

                if src_id in node_mapping and dst_id in node_mapping:
                    src_idx = node_mapping[src_id]
                    dst_idx = node_mapping[dst_id]

                    edge_list.append([src_idx, dst_idx])

                    # 编码边特征
                    edge_feat = self.edge_encoder.encode(edge.get("properties", {}))
                    edge_features.append(edge_feat)

            # 4. 转换为PyG Data
            if not node_features:
                return None

            x = torch.tensor(np.stack(node_features), dtype=torch.float32)
            edge_index = torch.tensor(edge_list, dtype=torch.long).t().contiguous() if edge_list else torch.zeros((2, 0), dtype=torch.long)

            data = Data(
                x=x,
                edge_index=edge_index,
                asset_id=asset_id,
                node_types=node_types_list,
            )

            if edge_features:
                data.edge_attr = torch.tensor(np.stack(edge_features), dtype=torch.float32)

            # 记录中心节点索引
            center_neo4j_id = subgraph_data.get("center_node_id")
            if center_neo4j_id in node_mapping:
                data.center_node_idx = node_mapping[center_neo4j_id]

            return data

        except Exception as e:
            logger.exception(f"Failed to load subgraph for {asset_id}: {e}")
            return None

    async def _query_subgraph(
        self,
        asset_id: str,
        node_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
    ) -> Dict:
        """
        查询Neo4j获取子图数据
        """
        # 构建类型过滤条件
        node_filter = ""
        if node_types:
            node_labels = "|".join(f"{t}" for t in node_types)
            node_filter = f"AND (n:{node_labels} OR m:{node_labels})"

        rel_filter = ""
        if relation_types:
            rel_types = "|".join(f"`{r}`" for r in relation_types)
            rel_quoted = [f"'{r}'" for r in relation_types]
            rel_filter = f"AND type(r) IN [{', '.join(rel_quoted)}]"

        query = f"""
        MATCH path = (center:DataAsset {{asset_id: $asset_id}})-[r*1..{self.max_hops}]-(n)
        WHERE ALL(rel IN r WHERE type(rel) IS NOT NULL {rel_filter})
        WITH center, nodes(path) as path_nodes, relationships(path) as path_rels
        UNWIND path_nodes as node
        UNWIND path_rels as rel
        WITH center,
             collect(DISTINCT node) as all_nodes,
             collect(DISTINCT rel) as all_rels
        RETURN
            center.id as center_node_id,
            center {{.*}} as center_properties,
            [n in all_nodes | {{
                id: id(n),
                type: labels(n)[0],
                properties: properties(n)
            }}] as nodes,
            [r in all_rels | {{
                source: id(startNode(r)),
                target: id(endNode(r)),
                type: type(r),
                properties: properties(r)
            }}] as edges
        LIMIT {self.max_nodes}
        """

        async with self.driver.session() as session:
            result = await session.run(query, asset_id=asset_id)
            record = await result.single()

            if not record:
                return {}

            return {
                "center_node_id": record["center_node_id"],
                "center_properties": record["center_properties"],
                "nodes": record["nodes"],
                "edges": record["edges"],
            }

    async def load_batch(
        self,
        asset_ids: List[str],
        batch_size: int = 32,
    ) -> List[Optional[Data]]:
        """批量加载多个资产的子图"""
        tasks = [self.load_asset_subgraph(aid) for aid in asset_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for aid, result in zip(asset_ids, results):
            if isinstance(result, Exception):
                logger.error(f"Error loading {aid}: {result}")
                processed.append(None)
            else:
                processed.append(result)

        return processed

    async def get_graph_statistics(self) -> Dict[str, Any]:
        """获取图统计信息"""
        query = """
        MATCH (n)
        WITH labels(n)[0] as node_type, count(n) as count
        RETURN collect({type: node_type, count: count}) as node_stats
        """

        rel_query = """
        MATCH ()-[r]->()
        WITH type(r) as rel_type, count(r) as count
        RETURN collect({type: rel_type, count: count}) as rel_stats
        """

        async with self.driver.session() as session:
            node_result = await session.run(query)
            node_record = await node_result.single()

            rel_result = await session.run(rel_query)
            rel_record = await rel_result.single()

            return {
                "nodes": node_record["node_stats"] if node_record else [],
                "relationships": rel_record["rel_stats"] if rel_record else [],
            }


class AssetSubgraphSampler:
    """
    资产子图采样器

    用于训练时生成正负样本
    """

    def __init__(
        self,
        neo4j_driver,
        node_encoder,
        edge_encoder,
        neg_samples_ratio: float = 1.0,
    ):
        self.loader = Neo4jGraphLoader(
            neo4j_driver, node_encoder, edge_encoder
        )
        self.neg_samples_ratio = neg_samples_ratio

    async def sample_training_pairs(
        self,
        asset_id: str,
        num_negatives: int = 5,
    ) -> Tuple[Optional[Data], List[Data]]:
        """
        采样正负样本对

        Args:
            asset_id: 中心资产ID
            num_negatives: 负样本数量

        Returns:
            (positive_subgraph, negative_subgraphs)
        """
        # 正样本：真实子图
        positive = await self.loader.load_asset_subgraph(asset_id)
        if positive is None:
            return None, []

        # 负样本：通过节点扰动或边删除生成
        negatives = []

        # 方法1：边扰动
        if positive.edge_index.size(1) > 0:
            edge_mask = torch.rand(positive.edge_index.size(1)) > 0.3
            perturbed = Data(
                x=positive.x,
                edge_index=positive.edge_index[:, edge_mask],
                edge_attr=positive.edge_attr[edge_mask] if hasattr(positive, 'edge_attr') else None,
            )
            negatives.append(perturbed)

        # 方法2：特征掩码
        if positive.x.size(0) > 0:
            mask = torch.rand_like(positive.x) > 0.2
            masked_x = positive.x * mask
            masked = Data(
                x=masked_x,
                edge_index=positive.edge_index,
                edge_attr=positive.edge_attr if hasattr(positive, 'edge_attr') else None,
            )
            negatives.append(masked)

        # 方法3：随机采样其他不相关资产作为负样本
        # 这里简化处理，实际应该查询不相关的资产
        while len(negatives) < num_negatives:
            noise = torch.randn_like(positive.x) * 0.1
            noisy = Data(
                x=positive.x + noise,
                edge_index=positive.edge_index,
                edge_attr=positive.edge_attr if hasattr(positive, 'edge_attr') else None,
            )
            negatives.append(noisy)

        return positive, negatives[:num_negatives]

    async def sample_contrastive_pairs(
        self,
        asset_id: str,
        similar_asset_ids: List[str],
        dissimilar_asset_ids: List[str],
    ) -> Tuple[Optional[Data], List[Data], List[Data]]:
        """
        采样对比学习对

        Returns:
            (anchor, positive_samples, negative_samples)
        """
        anchor = await self.loader.load_asset_subgraph(asset_id)
        if anchor is None:
            return None, [], []

        positives = await self.loader.load_batch(similar_asset_ids)
        positives = [p for p in positives if p is not None]

        negatives = await self.loader.load_batch(dissimilar_asset_ids)
        negatives = [n for n in negatives if n is not None]

        return anchor, positives, negatives
