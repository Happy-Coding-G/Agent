"""remove_unused_models_and_tables

Revision ID: e4b825175a0b
Revises: 006_unify_lineage_pricing
Create Date: 2026-04-23 07:37:07.798162+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4b825175a0b'
down_revision: Union[str, None] = '006_unify_lineage_pricing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop orphaned tables (no corresponding model in codebase)
    # CASCADE removes dependent FK constraints without deleting the referencing tables
    op.execute("DROP TABLE IF EXISTS agent_message_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS escrow_transaction_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS negotiation_history_summaries CASCADE")
    op.execute("DROP TABLE IF EXISTS negotiation_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS escrow_records CASCADE")

    # Drop unused models with FK constraints first (child before parent)
    op.execute("DROP TABLE IF EXISTS asset_cluster_memberships CASCADE")
    op.execute("DROP TABLE IF EXISTS asset_clusters CASCADE")
    op.execute("DROP TABLE IF EXISTS review_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS asset_provenance CASCADE")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE")

    # Drop unused enum types
    op.execute("DROP TYPE IF EXISTS review_status")


def downgrade() -> None:
    # Recreate review_status enum
    review_status_enum = sa.Enum(
        "pending", "approved", "rejected", "manual_review", name="review_status"
    )
    review_status_enum.create(op.get_bind())

    # Recreate asset_clusters
    op.create_table(
        "asset_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("public_id", sa.String(32), unique=True, nullable=False),
        sa.Column("space_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("summary_report", sa.Text(), nullable=True),
        sa.Column("graph_cluster_id", sa.String(128), nullable=True),
        sa.Column("cluster_method", sa.String(32), nullable=True),
        sa.Column("asset_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("publication_ready", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("idx_asset_clusters_space", "space_id"),
        sa.Index("idx_asset_clusters_graph_id", "graph_cluster_id"),
    )

    # Recreate asset_cluster_memberships
    op.create_table(
        "asset_cluster_memberships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("cluster_role", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("cluster_id", "asset_id", name="uk_cluster_asset"),
        sa.Index("idx_cluster_membership_asset", "asset_id"),
    )

    # Recreate review_logs
    op.create_table(
        "review_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("public_id", sa.String(32), unique=True, nullable=False),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_type", sa.String(32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("issues", postgresql.JSONB(), nullable=True),
        sa.Column("recommendations", postgresql.JSONB(), nullable=True),
        sa.Column("rework_needed", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("rework_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("max_rework", sa.Integer(), server_default=sa.text("3")),
        sa.Column("final_status", review_status_enum, server_default=sa.text("'pending'")),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("idx_review_logs_doc", "doc_id"),
        sa.Index("idx_review_logs_status", "final_status"),
    )

    # Recreate asset_provenance
    op.create_table(
        "asset_provenance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("provenance_id", sa.String(32), unique=True, nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False, index=True),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(32), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("origin_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creator_name", sa.String(255), nullable=True),
        sa.Column("license_type", sa.String(64), nullable=True),
        sa.Column("verification_hash", sa.String(64), nullable=True),
        sa.Column("verification_method", sa.String(32), nullable=True),
        sa.Column("record_metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("idx_prov_asset", "asset_id"),
        sa.Index("idx_prov_source", "source_type", "source_id"),
    )

    # Recreate outbox_events
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(32), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("3")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("processor_id", sa.String(64), nullable=True),
        sa.Index("idx_outbox_status_created", "status", "created_at"),
        sa.Index("idx_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )
