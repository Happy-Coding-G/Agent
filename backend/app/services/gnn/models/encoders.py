"""
Node and Edge Encoders for Graph Data

将原始节点/边属性编码为模型可用的特征向量
"""

import torch
import torch.nn as nn
from typing import Dict, List, Any, Optional
import numpy as np


class NodeEncoder:
    """
    节点特征编码器

    将Neo4j节点属性转换为数值特征向量
    """

    # 节点类型编码
    NODE_TYPE_ENCODING = {
        "DataAsset": 0,
        "DataSource": 1,
        "ProcessingStep": 2,
        "Entity": 3,
        "User": 4,
        "Tag": 5,
    }

    # 数据类型编码
    DATA_TYPE_ENCODING = {
        "medical": 0,
        "financial": 1,
        "geographic": 2,
        "behavioral": 3,
        "iot": 4,
        "text": 5,
        "image": 6,
        "other": 7,
    }

    def __init__(self, embedding_dim: int = 64):
        self.embedding_dim = embedding_dim
        self.feature_dim = self._calculate_feature_dim()

    def _calculate_feature_dim(self) -> int:
        """计算输出特征维度"""
        return (
            len(self.NODE_TYPE_ENCODING) +      # one-hot节点类型
            len(self.DATA_TYPE_ENCODING) +      # one-hot数据类型
            10 +                                 # 数值特征（质量分数等）
            8 +                                  # 统计特征
            16                                   # 时间编码
        )

    def encode(self, node_data: Dict[str, Any]) -> np.ndarray:
        """
        编码单个节点

        Args:
            node_data: 节点属性字典，来自Neo4j
                {
                    "type": "DataAsset",
                    "data_type": "medical",
                    "quality_score": 0.85,
                    "completeness": 0.9,
                    ...
                }

        Returns:
            feature_vector: 编码后的特征向量
        """
        features = []

        # 1. 节点类型 one-hot
        node_type = node_data.get("type", "Other")
        type_onehot = self._one_hot(
            node_type,
            self.NODE_TYPE_ENCODING,
            len(self.NODE_TYPE_ENCODING)
        )
        features.extend(type_onehot)

        # 2. 数据类型 one-hot (仅DataAsset)
        data_type = node_data.get("data_type", "other")
        data_type_onehot = self._one_hot(
            data_type,
            self.DATA_TYPE_ENCODING,
            len(self.DATA_TYPE_ENCODING)
        )
        features.extend(data_type_onehot)

        # 3. 数值特征（归一化到[0,1]）
        numeric_features = [
            node_data.get("quality_score", 0.5),
            node_data.get("completeness", 0.5),
            node_data.get("accuracy", 0.5),
            node_data.get("timeliness", 0.5),
            node_data.get("consistency", 0.5),
            node_data.get("uniqueness", 0.5),
            node_data.get("overall_score", 0.5),
            node_data.get("record_count", 0) / 1e6,  # 归一化
            node_data.get("size_bytes", 0) / 1e9,
            node_data.get("entity_count", 0) / 1000,
        ]
        features.extend([self._clip(f) for f in numeric_features])

        # 4. 统计特征
        stats_features = [
            node_data.get("is_active", 1),
            node_data.get("is_available_for_trade", 0),
            node_data.get("transaction_count", 0) / 100,
            node_data.get("view_count", 0) / 1000,
            node_data.get("favorite_count", 0) / 100,
            len(node_data.get("tags", [])) / 20,  # 标签数量
            len(node_data.get("related_entities", [])) / 50,  # 关联实体数
            node_data.get("price_history_count", 0) / 10,
        ]
        features.extend([self._clip(f) for f in stats_features])

        # 5. 时间特征（循环编码）
        time_features = self._encode_time_features(
            node_data.get("created_at"),
            node_data.get("updated_at")
        )
        features.extend(time_features)

        return np.array(features, dtype=np.float32)

    def encode_batch(self, nodes_data: List[Dict[str, Any]]) -> torch.Tensor:
        """批量编码节点"""
        encoded = [self.encode(node) for node in nodes_data]
        return torch.tensor(np.stack(encoded), dtype=torch.float32)

    def _one_hot(self, value: str, encoding_map: Dict[str, int], dim: int) -> List[float]:
        """One-hot编码"""
        vec = [0.0] * dim
        idx = encoding_map.get(value, dim - 1)
        vec[idx] = 1.0
        return vec

    def _clip(self, value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """裁剪数值"""
        return max(min_val, min(max_val, float(value)))

    def _encode_time_features(
        self,
        created_at: Optional[str],
        updated_at: Optional[str]
    ) -> List[float]:
        """编码时间特征（循环编码）"""
        import datetime

        features = []

        for timestamp in [created_at, updated_at]:
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        dt = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    else:
                        dt = datetime.datetime.fromtimestamp(timestamp)

                    # 月、日、小时的正弦/余弦编码
                    month = dt.month
                    day = dt.day
                    hour = dt.hour

                    features.extend([
                        np.sin(2 * np.pi * month / 12),
                        np.cos(2 * np.pi * month / 12),
                        np.sin(2 * np.pi * day / 31),
                        np.cos(2 * np.pi * day / 31),
                        np.sin(2 * np.pi * hour / 24),
                        np.cos(2 * np.pi * hour / 24),
                    ])
                except:
                    features.extend([0.0] * 6)
            else:
                features.extend([0.0] * 6)

        # 计算时间差（天数）
        if created_at and updated_at:
            try:
                if isinstance(created_at, str):
                    created = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    updated = datetime.datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                else:
                    created = datetime.datetime.fromtimestamp(created_at)
                    updated = datetime.datetime.fromtimestamp(updated_at)
                age_days = (updated - created).days
                features.append(self._clip(age_days / 365, 0, 5))  # 归一化到5年
            except:
                features.append(0.0)
        else:
            features.append(0.0)

        # 总长度应该是16，补充到16
        while len(features) < 16:
            features.append(0.0)

        return features[:16]


class EdgeEncoder:
    """
    边特征编码器
    """

    # 关系类型编码
    RELATION_ENCODING = {
        "DERIVED_FROM": 0,
        "PROCESSED_BY": 1,
        "CONTAINS_ENTITY": 2,
        "OWNED_BY": 3,
        "TAGGED_WITH": 4,
        "SIMILAR_TO": 5,
        "DEPENDS_ON": 6,
        "REFERENCES": 7,
    }

    def __init__(self, embedding_dim: int = 16):
        self.embedding_dim = embedding_dim
        self.feature_dim = self._calculate_feature_dim()

    def _calculate_feature_dim(self) -> int:
        return (
            len(self.RELATION_ENCODING) +  # one-hot关系类型
            4 +                             # 权重、强度等
            4                               # 时间特征
        )

    def encode(self, edge_data: Dict[str, Any]) -> np.ndarray:
        """
        编码单条边

        Args:
            edge_data: 边属性
                {
                    "relation_type": "DERIVED_FROM",
                    "weight": 0.8,
                    "strength": 0.9,
                    ...
                }
        """
        features = []

        # 1. 关系类型 one-hot
        rel_type = edge_data.get("relation_type", "UNKNOWN")
        rel_onehot = self._one_hot(
            rel_type,
            self.RELATION_ENCODING,
            len(self.RELATION_ENCODING)
        )
        features.extend(rel_onehot)

        # 2. 边权重特征
        weight_features = [
            edge_data.get("weight", 1.0),
            edge_data.get("strength", 0.5),
            edge_data.get("confidence", 0.5),
            edge_data.get("frequency", 1) / 100,  # 使用频率
        ]
        features.extend([self._clip(f) for f in weight_features])

        # 3. 时间特征
        time_feats = self._encode_edge_time(
            edge_data.get("created_at"),
            edge_data.get("last_used")
        )
        features.extend(time_feats)

        return np.array(features, dtype=np.float32)

    def encode_batch(self, edges_data: List[Dict[str, Any]]) -> torch.Tensor:
        """批量编码边"""
        encoded = [self.encode(edge) for edge in edges_data]
        return torch.tensor(np.stack(encoded), dtype=torch.float32)

    def _one_hot(self, value: str, encoding_map: Dict[str, int], dim: int) -> List[float]:
        vec = [0.0] * dim
        idx = encoding_map.get(value, dim - 1)
        vec[idx] = 1.0
        return vec

    def _clip(self, value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        return max(min_val, min(max_val, float(value)))

    def _encode_edge_time(
        self,
        created_at: Optional[str],
        last_used: Optional[str]
    ) -> List[float]:
        """编码边的时间特征"""
        import datetime

        features = []

        # 边存在时长
        if created_at:
            try:
                if isinstance(created_at, str):
                    created = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                else:
                    created = datetime.datetime.fromtimestamp(created_at)
                age_days = (datetime.datetime.now(datetime.timezone.utc) - created.replace(tzinfo=datetime.timezone.utc)).days
                features.append(self._clip(age_days / 365, 0, 3))
            except:
                features.append(0.0)
        else:
            features.append(0.0)

        # 最后使用时间
        if last_used:
            try:
                if isinstance(last_used, str):
                    last = datetime.datetime.fromisoformat(last_used.replace('Z', '+00:00'))
                else:
                    last = datetime.datetime.fromtimestamp(last_used)
                recency_days = (datetime.datetime.now(datetime.timezone.utc) - last.replace(tzinfo=datetime.timezone.utc)).days
                features.append(self._clip(1 - recency_days / 365, 0, 1))  # 越新越高
            except:
                features.append(0.0)
        else:
            features.append(0.0)

        # 使用频率正弦编码
        frequency = features[0] if features else 0
        features.extend([
            np.sin(2 * np.pi * frequency),
            np.cos(2 * np.pi * frequency),
        ])

        return features


class FeatureNormalizer:
    """
    特征归一化器
    用于在线推理时对输入特征进行归一化
    """

    def __init__(self):
        self.mean = None
        self.std = None
        self.fitted = False

    def fit(self, features: np.ndarray):
        """拟合归一化参数"""
        self.mean = np.mean(features, axis=0)
        self.std = np.std(features, axis=0)
        # 避免除零
        self.std[self.std == 0] = 1.0
        self.fitted = True

    def transform(self, features: np.ndarray) -> np.ndarray:
        """归一化特征"""
        if not self.fitted:
            raise RuntimeError("Normalizer must be fitted before transform")
        return (features - self.mean) / self.std

    def fit_transform(self, features: np.ndarray) -> np.ndarray:
        """拟合并转换"""
        self.fit(features)
        return self.transform(features)

    def inverse_transform(self, normalized_features: np.ndarray) -> np.ndarray:
        """反归一化"""
        if not self.fitted:
            raise RuntimeError("Normalizer must be fitted before inverse_transform")
        return normalized_features * self.std + self.mean

    def save(self, path: str):
        """保存归一化参数"""
        np.savez(path, mean=self.mean, std=self.std)

    def load(self, path: str):
        """加载归一化参数"""
        data = np.load(path)
        self.mean = data['mean']
        self.std = data['std']
        self.fitted = True
