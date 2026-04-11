"""
GraphSAGE Training Pipeline

训练流程：
1. 从Neo4j加载数据
2. 构建训练/验证/测试集
3. 多任务训练（嵌入学习 + 价格预测）
4. 模型评估和保存
"""

import os
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR, ReduceLROnPlateau
from torch.utils.tensorboard import SummaryWriter
import numpy as np
from tqdm import tqdm
import logging

from app.services.gnn.models.graphsage import AssetGraphSAGE, MultiTaskGraphSAGE
from app.services.gnn.data.pyg_dataset import AssetGraphDataset

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """训练配置"""
    # 模型参数
    in_channels: int = 128
    hidden_channels: int = 256
    out_channels: int = 128
    num_layers: int = 3
    dropout: float = 0.3

    # 训练参数
    batch_size: int = 32
    learning_rate: float = 1e-3
    weight_decay: float = 1e-5
    num_epochs: int = 100
    warmup_epochs: int = 5

    # 损失权重
    embedding_loss_weight: float = 1.0
    price_loss_weight: float = 0.5
    scarcity_loss_weight: float = 0.3
    quality_loss_weight: float = 0.3

    # 优化参数
    use_lr_scheduler: bool = True
    scheduler_type: str = "cosine"  # "cosine" | "plateau"
    patience: int = 10  # 早停耐心值

    # 路径
    checkpoint_dir: str = "./checkpoints"
    log_dir: str = "./logs"
    save_interval: int = 10

    # 设备
    device: str = "auto"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GraphSAGETrainer:
    """
    GraphSAGE训练器
    """

    def __init__(
        self,
        config: TrainingConfig,
        train_dataset: Optional[AssetGraphDataset] = None,
        val_dataset: Optional[AssetGraphDataset] = None,
    ):
        self.config = config
        self.train_dataset = train_dataset
        self.val_dataset = val_dataset

        # 设备选择
        if config.device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(config.device)

        # 模型
        self.model: Optional[MultiTaskGraphSAGE] = None

        # 优化器
        self.optimizer: Optional[torch.optim.Optimizer] = None
        self.scheduler: Optional[Any] = None

        # 日志
        self.writer = SummaryWriter(log_dir=config.log_dir)

        # 训练状态
        self.current_epoch = 0
        self.best_val_loss = float("inf")
        self.patience_counter = 0

        # 指标记录
        self.history = {
            "train_loss": [],
            "val_loss": [],
            "learning_rate": [],
        }

        self._init_model()

    def _init_model(self):
        """初始化模型"""
        self.model = MultiTaskGraphSAGE(
            in_channels=self.config.in_channels,
            hidden_channels=self.config.hidden_channels,
            embedding_dim=self.config.out_channels,
            num_layers=self.config.num_layers,
            dropout=self.config.dropout,
        ).to(self.device)

        # 优化器
        self.optimizer = AdamW(
            self.model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )

        # 学习率调度器
        if self.config.use_lr_scheduler:
            if self.config.scheduler_type == "cosine":
                self.scheduler = CosineAnnealingLR(
                    self.optimizer,
                    T_max=self.config.num_epochs - self.config.warmup_epochs,
                    eta_min=1e-6,
                )
            elif self.config.scheduler_type == "plateau":
                self.scheduler = ReduceLROnPlateau(
                    self.optimizer,
                    mode="min",
                    factor=0.5,
                    patience=5,
                )

    def train(self) -> Dict[str, List[float]]:
        """
        主训练循环

        Returns:
            训练历史
        """
        logger.info(f"Starting training on {self.device}")
        logger.info(f"Model parameters: {sum(p.numel() for p in self.model.parameters()):,}")

        # 创建数据加载器
        from torch_geometric.loader import DataLoader

        train_loader = DataLoader(
            self.train_dataset,
            batch_size=self.config.batch_size,
            shuffle=True,
            num_workers=0,  # 异步Neo4j查询不支持多进程
        )

        if self.val_dataset:
            val_loader = DataLoader(
                self.val_dataset,
                batch_size=self.config.batch_size,
                shuffle=False,
            )
        else:
            val_loader = None

        # 训练循环
        for epoch in range(self.config.num_epochs):
            self.current_epoch = epoch

            # 训练
            train_metrics = self._train_epoch(train_loader)

            # 验证
            if val_loader:
                val_metrics = self._validate(val_loader)
            else:
                val_metrics = {"loss": train_metrics["loss"]}

            # 记录日志
            self._log_metrics(epoch, train_metrics, val_metrics)

            # 保存检查点
            if (epoch + 1) % self.config.save_interval == 0:
                self._save_checkpoint(epoch, is_best=False)

            # 早停检查
            if val_metrics["loss"] < self.best_val_loss:
                self.best_val_loss = val_metrics["loss"]
                self.patience_counter = 0
                self._save_checkpoint(epoch, is_best=True)
            else:
                self.patience_counter += 1
                if self.patience_counter >= self.config.patience:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break

            # 更新学习率
            if self.scheduler:
                if self.config.scheduler_type == "cosine":
                    if epoch >= self.config.warmup_epochs:
                        self.scheduler.step()
                elif self.config.scheduler_type == "plateau":
                    self.scheduler.step(val_metrics["loss"])

        self.writer.close()
        return self.history

    def _train_epoch(self, train_loader) -> Dict[str, float]:
        """训练一个epoch"""
        self.model.train()

        total_loss = 0.0
        total_samples = 0

        pbar = tqdm(train_loader, desc=f"Epoch {self.current_epoch}")

        for batch_idx, data in enumerate(pbar):
            if data is None:
                continue

            # 移动到设备
            data = data.to(self.device)

            # 前向传播
            predictions = self.model(data.x, data.edge_index, data.batch)

            # 构建目标（简化示例，实际需要真实标签）
            targets = self._build_targets(data)

            # 计算损失
            loss = self.model.compute_loss(predictions, targets, {
                "price": self.config.price_loss_weight,
                "scarcity": self.config.scarcity_loss_weight,
                "quality": self.config.quality_loss_weight,
            })

            # 反向传播
            self.optimizer.zero_grad()
            loss.backward()

            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)

            self.optimizer.step()

            # 记录
            total_loss += loss.item() * data.num_graphs
            total_samples += data.num_graphs

            # 更新进度条
            pbar.set_postfix({"loss": loss.item()})

        avg_loss = total_loss / max(total_samples, 1)

        return {"loss": avg_loss}

    def _validate(self, val_loader) -> Dict[str, float]:
        """验证"""
        self.model.eval()

        total_loss = 0.0
        total_samples = 0

        with torch.no_grad():
            for data in val_loader:
                if data is None:
                    continue

                data = data.to(self.device)

                predictions = self.model(data.x, data.edge_index, data.batch)
                targets = self._build_targets(data)

                loss = self.model.compute_loss(predictions, targets)

                total_loss += loss.item() * data.num_graphs
                total_samples += data.num_graphs

        avg_loss = total_loss / max(total_samples, 1)

        return {"loss": avg_loss}

    def _build_targets(self, data) -> Dict[str, torch.Tensor]:
        """
        构建训练目标

        实际应该从数据中读取，这里简化处理
        """
        batch_size = data.num_graphs if hasattr(data, 'num_graphs') else 1

        targets = {
            "price": torch.rand(batch_size, device=self.device) * 1000,  # 模拟价格
            "scarcity": torch.randint(0, 3, (batch_size,), device=self.device),  # 稀缺性类别
            "quality": torch.rand(batch_size, 5, device=self.device),  # 质量5维度
        }

        return targets

    def _log_metrics(
        self,
        epoch: int,
        train_metrics: Dict[str, float],
        val_metrics: Dict[str, float],
    ):
        """记录指标"""
        # TensorBoard
        self.writer.add_scalar("Loss/train", train_metrics["loss"], epoch)
        self.writer.add_scalar("Loss/val", val_metrics["loss"], epoch)

        lr = self.optimizer.param_groups[0]["lr"]
        self.writer.add_scalar("LearningRate", lr, epoch)

        # 历史记录
        self.history["train_loss"].append(train_metrics["loss"])
        self.history["val_loss"].append(val_metrics["loss"])
        self.history["learning_rate"].append(lr)

        # 日志
        logger.info(
            f"Epoch {epoch}: "
            f"train_loss={train_metrics['loss']:.4f}, "
            f"val_loss={val_metrics['loss']:.4f}, "
            f"lr={lr:.6f}"
        )

    def _save_checkpoint(self, epoch: int, is_best: bool = False):
        """保存检查点"""
        os.makedirs(self.config.checkpoint_dir, exist_ok=True)

        checkpoint = {
            "epoch": epoch,
            "model_state_dict": self.model.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "config": self.config.to_dict(),
            "history": self.history,
            "best_val_loss": self.best_val_loss,
        }

        if self.scheduler:
            checkpoint["scheduler_state_dict"] = self.scheduler.state_dict()

        # 保存最新
        latest_path = os.path.join(self.config.checkpoint_dir, "latest.pt")
        torch.save(checkpoint, latest_path)

        # 保存最佳
        if is_best:
            best_path = os.path.join(self.config.checkpoint_dir, "best.pt")
            torch.save(checkpoint, best_path)
            logger.info(f"Saved best model with val_loss={self.best_val_loss:.4f}")

        # 保存特定epoch
        epoch_path = os.path.join(self.config.checkpoint_dir, f"epoch_{epoch}.pt")
        torch.save(checkpoint, epoch_path)

    def load_checkpoint(self, checkpoint_path: str):
        """加载检查点"""
        checkpoint = torch.load(checkpoint_path, map_location=self.device)

        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

        if "scheduler_state_dict" in checkpoint and self.scheduler:
            self.scheduler.load_state_dict(checkpoint["scheduler_state_dict"])

        self.current_epoch = checkpoint["epoch"]
        self.history = checkpoint["history"]
        self.best_val_loss = checkpoint["best_val_loss"]

        logger.info(f"Loaded checkpoint from epoch {self.current_epoch}")


class ContrastiveTrainer(GraphSAGETrainer):
    """
    对比学习训练器

    使用对比损失训练更好的嵌入
    """

    def __init__(
        self,
        config: TrainingConfig,
        train_dataset: Optional[AssetGraphDataset] = None,
        val_dataset: Optional[AssetGraphDataset] = None,
    ):
        super().__init__(config, train_dataset, val_dataset)
        self.temperature = 0.5

    def _train_epoch(self, train_loader) -> Dict[str, float]:
        """对比学习训练"""
        self.model.train()

        total_loss = 0.0
        total_samples = 0

        for data in tqdm(train_loader, desc=f"Epoch {self.current_epoch}"):
            if data is None:
                continue

            data = data.to(self.device)

            # 生成正样本（数据增强）
            pos_data = self._augment_data(data)

            # 获取嵌入
            anchor_emb = self.model.encoder(data.x, data.edge_index)
            pos_emb = self.model.encoder(pos_data.x, pos_data.edge_index)

            # 负样本（从batch中其他样本）
            neg_emb = self._sample_negatives(anchor_emb)

            # 对比损失
            loss = self.model.encoder.contrastive_loss(
                anchor_emb, pos_emb, neg_emb, self.temperature
            )

            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            total_loss += loss.item() * data.num_graphs
            total_samples += data.num_graphs

        return {"loss": total_loss / max(total_samples, 1)}

    def _augment_data(self, data) -> Any:
        """数据增强生成正样本"""
        # 特征掩码
        mask = torch.rand_like(data.x) > 0.2
        aug_x = data.x * mask

        # 边扰动
        if data.edge_index.size(1) > 0:
            edge_mask = torch.rand(data.edge_index.size(1)) > 0.1
            aug_edge_index = data.edge_index[:, edge_mask]
        else:
            aug_edge_index = data.edge_index

        from torch_geometric.data import Data
        return Data(x=aug_x, edge_index=aug_edge_index)

    def _sample_negatives(self, anchor: torch.Tensor) -> torch.Tensor:
        """采样负样本"""
        # 随机打乱作为负样本
        neg_idx = torch.randperm(anchor.size(0))
        return anchor[neg_idx]
