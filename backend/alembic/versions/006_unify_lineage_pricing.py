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
        sa.Column("quality_metrics", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
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
        sa.Column("extra_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
    )

    # 2. 创建新索引
    op.create_index("idx_lineage_space", "data_lineage", ["space_id"])
    op.create_index("idx_lineage_hash", "data_lineage", ["lineage_hash"])

    # 3. 将 data_lineage_nodes 的数据迁移到 data_lineage（若存在旧数据）
    op.execute(
        """
        DO $$
        DECLARE
            missing_created_by_count integer;
            unresolved_parent_count integer;
        BEGIN
            IF to_regclass('public.data_lineage_nodes') IS NULL THEN
                RETURN;
            END IF;

            SELECT count(*)
              INTO missing_created_by_count
              FROM data_lineage_nodes n
              LEFT JOIN data_assets a ON a.asset_id = n.asset_id
             WHERE a.owner_id IS NULL;

            IF missing_created_by_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate data_lineage_nodes: % rows cannot resolve created_by from data_assets.owner_id',
                    missing_created_by_count;
            END IF;

            SELECT count(*)
              INTO unresolved_parent_count
              FROM data_lineage_nodes n
              CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(n.parent_nodes, '[]'::jsonb)) p(parent_node)
              LEFT JOIN data_lineage_nodes parent ON parent.node_id = p.parent_node
             WHERE parent.node_id IS NULL;

            IF unresolved_parent_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot migrate data_lineage_nodes: % parent node references cannot be resolved',
                    unresolved_parent_count;
            END IF;

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
                created_by,
                created_at
            )
            SELECT
                'lin_' || substr(md5(n.node_id || ':' || COALESCE(parent_ref.parent_node, 'root')), 1, 16),
                CASE WHEN parent_ref.parent_node IS NULL THEN 'unknown' ELSE 'asset' END,
                COALESCE(parent.asset_id, ''),
                jsonb_build_object(
                    'migrated_from', 'data_lineage_nodes',
                    'legacy_node_id', n.node_id,
                    'legacy_parent_node_id', parent_ref.parent_node
                ),
                '[]'::jsonb,
                'asset',
                n.asset_id,
                n.node_type,
                n.provenance_hash,
                parent.provenance_hash,
                COALESCE(n.quality_metrics, '{}'::jsonb),
                COALESCE(parent_ref.ordinality::integer - 1, 0),
                jsonb_build_object(
                    'migrated_from', 'data_lineage_nodes',
                    'hash_version', 'legacy',
                    'legacy_node_id', n.node_id,
                    'legacy_parent_node_id', parent_ref.parent_node,
                    'processing_logic_hash', n.processing_logic_hash,
                    'parent_hashes',
                    CASE
                        WHEN parent.provenance_hash IS NULL THEN '[]'::jsonb
                        ELSE jsonb_build_array(parent.provenance_hash)
                    END
                ),
                a.owner_id,
                n.created_at
            FROM data_lineage_nodes n
            JOIN data_assets a ON a.asset_id = n.asset_id
            LEFT JOIN LATERAL jsonb_array_elements_text(COALESCE(n.parent_nodes, '[]'::jsonb))
                WITH ORDINALITY AS parent_ref(parent_node, ordinality) ON true
            LEFT JOIN data_lineage_nodes parent ON parent.node_id = parent_ref.parent_node;
        END $$;
        """
    )

    # 4. 删除 data_lineage_nodes 表
    op.execute("DROP TABLE IF EXISTS data_lineage_nodes")


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
