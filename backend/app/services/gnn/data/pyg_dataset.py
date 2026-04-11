"""
PyTorch Geometric Dataset for Asset Graph

用于训练GraphSAGE的数据集
"""

import os
import json
import torch
from torch_geometric.data import Dataset, Data
from typing import List, Optional, Callable
import numpy as np
import logging

logger = logging.getLogger(__name__)


class AssetGraphDataset(Dataset):
    """
    资产图数据集

    支持：
    1. 从Neo4j实时加载
    2. 从本地缓存加载
    3. 增量更新
    """

    def __init__(
        self,
        root: str,
        neo4j_loader=None,
        asset_ids: Optional[List[str]] = None,
        transform: Optional[Callable] = None,
        pre_transform: Optional[Callable] = None,
        pre_filter: Optional[Callable] = None,
        use_cache: bool = True,
    ):
        self.neo4j_loader = neo4j_loader
        self.asset_ids = asset_ids or []
        self.use_cache = use_cache

        super().__init__(root, transform, pre_transform, pre_filter)

        # 加载已处理的资产列表
        self.processed_asset_ids = self._load_processed_list()

    @property
    def raw_file_names(self):
        """原始数据文件名"""
        return ['asset_ids.json']

    @property
    def processed_file_names(self):
        """处理后数据文件名"""
        return [f'data_{i}.pt' for i in range(len(self.asset_ids))]

    def _load_processed_list(self) -> List[str]:
        """加载已处理的资产ID列表"""
        path = os.path.join(self.processed_dir, 'processed_assets.json')
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return []

    def download(self):
        """下载/准备原始数据"""
        if not self.asset_ids and self.neo4j_loader:
            # 从Neo4j获取所有资产ID
            # 这里简化处理，实际应该查询数据库
            pass

        # 保存资产ID列表
        os.makedirs(self.raw_dir, exist_ok=True)
        with open(os.path.join(self.raw_dir, 'asset_ids.json'), 'w') as f:
            json.dump(self.asset_ids, f)

    def process(self):
        """处理原始数据到PyG Data"""
        import asyncio

        if not self.neo4j_loader:
            logger.warning("No Neo4j loader provided, skipping processing")
            return

        async def _process_all():
            processed_ids = []

            for i, asset_id in enumerate(self.asset_ids):
                try:
                    # 检查缓存
                    cache_path = os.path.join(self.processed_dir, f'data_{asset_id}.pt')
                    if self.use_cache and os.path.exists(cache_path):
                        logger.debug(f"Using cached data for {asset_id}")
                        processed_ids.append(asset_id)
                        continue

                    # 从Neo4j加载
                    data = await self.neo4j_loader.load_asset_subgraph(asset_id)

                    if data is not None:
                        # 应用pre_transform
                        if self.pre_transform:
                            data = self.pre_transform(data)

                        # 保存
                        torch.save(data, cache_path)
                        processed_ids.append(asset_id)

                        if (i + 1) % 100 == 0:
                            logger.info(f"Processed {i + 1}/{len(self.asset_ids)} assets")

                except Exception as e:
                    logger.error(f"Failed to process {asset_id}: {e}")

            # 保存处理列表
            with open(os.path.join(self.processed_dir, 'processed_assets.json'), 'w') as f:
                json.dump(processed_ids, f)

        asyncio.run(_process_all())

    def len(self):
        """数据集长度"""
        return len(self.processed_asset_ids)

    def get(self, idx):
        """获取指定索引的数据"""
        asset_id = self.processed_asset_ids[idx]
        data_path = os.path.join(self.processed_dir, f'data_{asset_id}.pt')

        if not os.path.exists(data_path):
            # 尝试使用索引路径
            data_path = os.path.join(self.processed_dir, f'data_{idx}.pt')

        data = torch.load(data_path)

        # 应用transform
        if self.transform:
            data = self.transform(data)

        return data

    def add_asset(self, asset_id: str, data: Data):
        """添加新资产到数据集"""
        if asset_id in self.processed_asset_ids:
            return

        cache_path = os.path.join(self.processed_dir, f'data_{asset_id}.pt')

        # 应用pre_transform
        if self.pre_transform:
            data = self.pre_transform(data)

        torch.save(data, cache_path)
        self.processed_asset_ids.append(asset_id)

        # 更新列表
        with open(os.path.join(self.processed_dir, 'processed_assets.json'), 'w') as f:
            json.dump(self.processed_asset_ids, f)

    def get_by_asset_id(self, asset_id: str) -> Optional[Data]:
        """通过资产ID获取数据"""
        if asset_id not in self.processed_asset_ids:
            return None

        data_path = os.path.join(self.processed_dir, f'data_{asset_id}.pt')
        if not os.path.exists(data_path):
            return None

        data = torch.load(data_path)

        if self.transform:
            data = self.transform(data)

        return data

    def clear_cache(self):
        """清除缓存"""
        import shutil

        if os.path.exists(self.processed_dir):
            shutil.rmtree(self.processed_dir)
        os.makedirs(self.processed_dir, exist_ok=True)
        self.processed_asset_ids = []


class InMemoryAssetDataset:
    """
    内存中的资产数据集

    适用于小规模数据，加载速度更快
    """

    def __init__(self, neo4j_loader, asset_ids: List[str]):
        self.neo4j_loader = neo4j_loader
        self.asset_ids = asset_ids
        self.data_list: List[Data] = []

    async def load_all(self):
        """加载所有数据到内存"""
        logger.info(f"Loading {len(self.asset_ids)} assets into memory...")

        self.data_list = await self.neo4j_loader.load_batch(self.asset_ids)
        self.data_list = [d for d in self.data_list if d is not None]

        logger.info(f"Successfully loaded {len(self.data_list)} assets")

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        return self.data_list[idx]

    def get_by_asset_id(self, asset_id: str) -> Optional[Data]:
        """通过资产ID获取数据"""
        for data in self.data_list:
            if hasattr(data, 'asset_id') and data.asset_id == asset_id:
                return data
        return None


def collate_graph_data(data_list: List[Data]) -> Data:
    """
    自定义collate函数用于批处理

    处理不同大小的图
    """
    from torch_geometric.data import Batch

    # 过滤None
    data_list = [d for d in data_list if d is not None]

    if not data_list:
        return None

    return Batch.from_data_list(data_list)


def create_train_val_split(
    dataset: AssetGraphDataset,
    train_ratio: float = 0.8,
    random_seed: int = 42,
) -> tuple:
    """
    划分训练集和验证集
    """
    import random

    random.seed(random_seed)

    indices = list(range(len(dataset)))
    random.shuffle(indices)

    split_idx = int(len(indices) * train_ratio)
    train_indices = indices[:split_idx]
    val_indices = indices[split_idx:]

    return train_indices, val_indices
