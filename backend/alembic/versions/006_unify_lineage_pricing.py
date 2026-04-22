"""unify lineage and pricing services

Revision ID: 006_unify_lineage_pricing
Revises: 005_add_users_is_admin
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_unify_lineage_pricing"
down_revision = "005_add_users_is_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 为 data_lineage 新增列
    op.add_column("data_lineage", sa.Column("relationship", sa.String(32), nullable=True))
    op.add_column("data_lineage", sa.Column("transformation_logic", sa.Text(), nullable=True))
    op.add_column(
        "data_lineage",
        sa.Column("confidence_score", sa.Float(), nullable=True, server_default="1.0"),
    )
    op.add_column(
        "data_lineage",
        sa.Column("quality_metrics", postgresql.JSONB(), server_default="'{}'"),
    )
    op.add_column("data_lineage", sa.Column("lineage_hash", sa.String(64), nullable=True))
    op.add_column("data_lineage", sa.Column("parent_hash", sa.String(64), nullable=True))
    op.add_column(
        "data_lineage",
        sa.Column("step_index", sa.Integer(), server_default="0"),
    )
    op.add_column("data_lineage", sa.Column("space_id", sa.String(32), nullable=True))
    op.add_column(
        "data_lineage",
        sa.Column("extra_metadata", postgresql.JSONB(), server_default="'{}'"),
    )

    # 2. 创建新索引
    op.create_index("idx_lineage_space", "data_lineage", ["space_id"])
    op.create_index("idx_lineage_hash", "data_lineage", ["lineage_hash"])

    # 3. 将 data_lineage_nodes 的数据迁移到 data_lineage（若存在旧数据）
    op.execute(
        """
        INSERT INTO data_lineage (
            lineage_id,
            source_type,
            source_id,
            source_metadata,
            transformations,
            current_entity_type,
            current_entity_id,
            relationship,
            lineage_hash,
            parent_hash,
            quality_metrics,
            step_index,
            extra_metadata,
            created_at
        )
        SELECT
            'lin_' || substr(md5(random()::text), 1, 16),
            'unknown',
            asset_id,
            '{}',
            '[]',
            'asset',
            asset_id,
            node_type,
            provenance_hash,
            CASE WHEN array_length(parent_nodes, 1) > 0 THEN parent_nodes[0] ELSE NULL END,
            COALESCE(quality_metrics, '{}'),
            0,
            jsonb_build_object('migrated_from', 'data_lineage_nodes', 'processing_logic_hash', processing_logic_hash),
            created_at
        FROM data_lineage_nodes
        """
    )

    # 4. 删除 data_lineage_nodes 表
    op.drop_table("data_lineage_nodes")


def downgrade() -> None:
    # 1. 恢复 data_lineage_nodes 表（空表）
    op.create_table(
        "data_lineage_nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("node_type", sa.String(50), nullable=False),
        sa.Column("parent_nodes", postgresql.JSONB(), nullable=True),
        sa.Column("processing_logic_hash", sa.String(64), nullable=False),
        sa.Column("quality_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("provenance_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id"),
    )
    op.create_index("ix_lineage_asset", "data_lineage_nodes", ["asset_id"])
    op.create_index("ix_lineage_type", "data_lineage_nodes", ["node_type"])

    # 2. 删除新索引
    op.drop_index("idx_lineage_space", table_name="data_lineage")
    op.drop_index("idx_lineage_hash", table_name="data_lineage")

    # 3. 删除 data_lineage 新增列
    op.drop_column("data_lineage", "extra_metadata")
    op.drop_column("data_lineage", "space_id")
    op.drop_column("data_lineage", "step_index")
    op.drop_column("data_lineage", "parent_hash")
    op.drop_column("data_lineage", "lineage_hash")
    op.drop_column("data_lineage", "quality_metrics")
    op.drop_column("data_lineage", "confidence_score")
    op.drop_column("data_lineage", "transformation_logic")
    op.drop_column("data_lineage", "relationship")
