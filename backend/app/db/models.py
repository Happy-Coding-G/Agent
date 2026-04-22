from __future__ import annotations

import datetime
import uuid
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    LargeBinary,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    PrimaryKeyConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType


try:
    from pgvector.sqlalchemy import Vector  # type: ignore
except Exception:

    class Vector(UserDefinedType):
        cache_ok = True

        def __init__(self, dimensions: int | None = None):
            self.dimensions = dimensions

        def get_col_spec(self, **kw):
            if self.dimensions:
                return f"vector({self.dimensions})"
            return "vector"


# Python Enums (for Python code use)
from enum import Enum as PyEnum


class OperationType(PyEnum):
    """协作操作类型"""

    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    MOVE = "move"


class SpaceRole(PyEnum):
    """Space 成员角色"""

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class DataLineageType(PyEnum):
    """数据血缘类型"""

    UPLOAD = "upload"
    API = "api"
    AGENT_GENERATION = "agent_generation"
    IMPORT = "import"
    TRANSFORM = "transform"
    DERIVED = "derived"
    FILE = "file"
    ASSET = "asset"
    KNOWLEDGE = "knowledge"


identity_type_enum = Enum("password", "phone", "wechat", "github", name="identity_type")
file_status_enum = Enum("active", "archived", "deleted", name="file_status")
upload_status_enum = Enum(
    "init", "uploading", "completed", "failed", name="upload_status"
)
document_status_enum = Enum(
    "pending", "processing", "completed", "failed", name="document_status"
)
ingest_status_enum = Enum(
    "queued", "running", "succeeded", "failed", "cancelled", name="ingest_status"
)


class Base(DeclarativeBase):
    pass


class FileVersions(Base):
    __tablename__ = "file_versions"
    __table_args__ = (
        ForeignKeyConstraint(["file_id"], ["files.id"], name="fk_file_versions_file"),
        Index("fk_file_versions_file", "file_id"),
        UniqueConstraint("public_id", name="uk_version_public_id"),
        UniqueConstraint("file_id", "version_no", name="uk_file_version_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    file: Mapped["Files"] = relationship(
        "Files",
        foreign_keys=[file_id],
        back_populates="file_versions",
    )

    referenced_as_current: Mapped[List["Files"]] = relationship(
        "Files",
        foreign_keys="[Files.current_version_id]",
        back_populates="current_version",
    )


class Files(Base):
    __tablename__ = "files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["current_version_id"],
            ["file_versions.id"],
            name="fk_files_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("public_id", name="uk_file_public_id"),
        Index("fk_files_current_version", "current_version_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    folder_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        file_status_enum, server_default=text("'active'")
    )
    current_version_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    file_versions: Mapped[List["FileVersions"]] = relationship(
        "FileVersions",
        foreign_keys="[FileVersions.file_id]",
        back_populates="file",
        cascade="all, delete-orphan",
    )
    current_version: Mapped[Optional["FileVersions"]] = relationship(
        "FileVersions",
        foreign_keys=[current_version_id],
        back_populates="referenced_as_current",
        post_update=True,
    )


class Folders(Base):
    __tablename__ = "folders"
    __table_args__ = (
        UniqueConstraint("public_id", name="uk_folder_public_id"),
        UniqueConstraint(
            "space_id", "parent_id", "name", name="uk_folder_sibling_name"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    path_cache: Mapped[Optional[str]] = mapped_column(String(2048))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Uploads(Base):
    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("public_id", name="uk_upload_public_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    folder_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_object_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        upload_status_enum, server_default=text("'init'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Users(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("user_key", name="uk_user_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    display_name: Mapped[Optional[str]] = mapped_column(String(128))

    spaces: Mapped[List["Spaces"]] = relationship("Spaces", back_populates="owner_user")
    user_auth: Mapped[List["UserAuth"]] = relationship(
        "UserAuth", back_populates="user"
    )
    documents: Mapped[List["Documents"]] = relationship(
        "Documents", back_populates="creator"
    )

    # Data Rights relationships
    data_assets: Mapped[List["DataAssets"]] = relationship(
        "DataAssets", back_populates="owner"
    )
    rights_granted: Mapped[List["DataRightsTransactions"]] = relationship(
        "DataRightsTransactions",
        foreign_keys="DataRightsTransactions.owner_id",
        back_populates="owner"
    )
    rights_received: Mapped[List["DataRightsTransactions"]] = relationship(
        "DataRightsTransactions",
        foreign_keys="DataRightsTransactions.buyer_id",
        back_populates="buyer"
    )
    access_logs: Mapped[List["DataAccessAuditLogs"]] = relationship(
        "DataAccessAuditLogs", back_populates="buyer"
    )

    # Agent 配置关系
    agent_configs: Mapped[List["UserAgentConfig"]] = relationship(
        "UserAgentConfig", back_populates="user"
    )

    # Memory / Conversation relationships
    conversation_sessions: Mapped[List["ConversationSessions"]] = relationship(
        "ConversationSessions", back_populates="user"
    )
    preferences: Mapped[List["UserPreferences"]] = relationship(
        "UserPreferences", back_populates="user"
    )
    memories: Mapped[List["UserMemories"]] = relationship(
        "UserMemories", back_populates="user"
    )

    # Trade relationships
    trade_listings: Mapped[List["TradeListings"]] = relationship(
        "TradeListings", foreign_keys="TradeListings.seller_user_id", back_populates="seller"
    )
    trade_orders_buyer: Mapped[List["TradeOrders"]] = relationship(
        "TradeOrders", foreign_keys="TradeOrders.buyer_user_id", back_populates="buyer"
    )
    trade_orders_seller: Mapped[List["TradeOrders"]] = relationship(
        "TradeOrders", foreign_keys="TradeOrders.seller_user_id", back_populates="seller"
    )
    trade_wallet: Mapped[Optional["TradeWallets"]] = relationship(
        "TradeWallets", back_populates="user", uselist=False
    )
    trade_holdings: Mapped[List["TradeHoldings"]] = relationship(
        "TradeHoldings", back_populates="owner"
    )
    trade_yield_runs: Mapped[List["TradeYieldRuns"]] = relationship(
        "TradeYieldRuns", back_populates="user"
    )
    trade_transactions: Mapped[List["TradeTransactionLog"]] = relationship(
        "TradeTransactionLog", back_populates="user"
    )
    token_usages: Mapped[List["TokenUsage"]] = relationship(
        "TokenUsage", back_populates="user", order_by="TokenUsage.created_at.desc()"
    )

    # Audit / Collaboration relationships
    lineage_created: Mapped[List["DataLineage"]] = relationship(
        "DataLineage", back_populates="creator"
    )
    collaboration_ops: Mapped[List["CollaborationOperations"]] = relationship(
        "CollaborationOperations", back_populates="user"
    )
    space_memberships: Mapped[List["SpaceMembers"]] = relationship(
        "SpaceMembers", foreign_keys="SpaceMembers.user_id", back_populates="user"
    )
    invited_members: Mapped[List["SpaceMembers"]] = relationship(
        "SpaceMembers", foreign_keys="SpaceMembers.invited_by", back_populates="inviter"
    )
    audit_logs: Mapped[List["AuditLogs"]] = relationship(
        "AuditLogs", foreign_keys="AuditLogs.user_id", back_populates="user"
    )


class Spaces(Base):
    __tablename__ = "spaces"
    __table_args__ = (
        ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_spaces_owner"),
        UniqueConstraint("public_id", name="uk_space_public_id"),
        Index("idx_space_owner", "owner_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    owner_user: Mapped["Users"] = relationship("Users", back_populates="spaces")
    documents: Mapped[List["Documents"]] = relationship(
        "Documents", back_populates="space"
    )


class UserAuth(Base):
    __tablename__ = "user_auth"
    __table_args__ = (
        ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_user"),
        UniqueConstraint("identity_type", "identifier", name="uk_identity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    identity_type: Mapped[str] = mapped_column(identity_type_enum, nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    credential: Mapped[str] = mapped_column(String(255), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    user: Mapped["Users"] = relationship("Users", back_populates="user_auth")


class Documents(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("graph_id", name="uk_documents_graph_id"),
        Index("idx_documents_space", "space_id"),
        Index("idx_documents_file_version", "file_version_id"),
    )

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="SET NULL")
    )
    file_version_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("file_versions.id", ondelete="SET NULL"),
    )
    graph_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    object_key: Mapped[Optional[str]] = mapped_column(String(512))
    source_mime: Mapped[Optional[str]] = mapped_column(String(128))
    markdown_object_key: Mapped[Optional[str]] = mapped_column(String(512))
    markdown_text: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        document_status_enum, server_default=text("'pending'")
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    space: Mapped["Spaces"] = relationship("Spaces", back_populates="documents")
    file: Mapped[Optional["Files"]] = relationship("Files", foreign_keys=[file_id])
    file_version: Mapped[Optional["FileVersions"]] = relationship(
        "FileVersions", foreign_keys=[file_version_id]
    )
    creator: Mapped["Users"] = relationship("Users", back_populates="documents")
    ingest_jobs: Mapped[List["IngestJobs"]] = relationship(
        "IngestJobs", back_populates="document"
    )
    chunks: Mapped[List["DocChunks"]] = relationship(
        "DocChunks", back_populates="document"
    )


class IngestJobs(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (Index("idx_ingest_jobs_doc", "doc_id"),)

    ingest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        ingest_status_enum, server_default=text("'queued'")
    )
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    document: Mapped["Documents"] = relationship(
        "Documents", back_populates="ingest_jobs"
    )


class DocChunks(Base):
    __tablename__ = "doc_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uk_doc_chunks_doc_index"),
        Index("idx_doc_chunks_doc", "doc_id"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    start_offset: Mapped[Optional[int]] = mapped_column(Integer)
    end_offset: Mapped[Optional[int]] = mapped_column(Integer)
    section_path: Mapped[Optional[str]] = mapped_column(Text)
    chunk_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    document: Mapped["Documents"] = relationship("Documents", back_populates="chunks")
    embeddings: Mapped[List["DocChunkEmbeddings"]] = relationship(
        "DocChunkEmbeddings", back_populates="chunk"
    )


class DocChunkEmbeddings(Base):
    __tablename__ = "doc_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model", name="uk_chunk_model"),
        Index("idx_chunk_embeddings_chunk", "chunk_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doc_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[object] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    chunk: Mapped["DocChunks"] = relationship("DocChunks", back_populates="embeddings")


# ============================================================================
# Agent-related models
# ============================================================================

agent_task_status_enum = Enum(
    "pending", "running", "completed", "failed", "cancelled", name="agent_task_status"
)
review_status_enum = Enum(
    "pending", "approved", "rejected", "manual_review", name="review_status"
)


class AgentTasks(Base):
    """Tracks multi-agent task executions."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("idx_agent_tasks_status", "status"),
        Index("idx_agent_tasks_space", "space_id"),
        Index("idx_agent_tasks_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    agent_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # file_query, qa, review, etc.
    status: Mapped[str] = mapped_column(
        agent_task_status_enum, server_default=text("'pending'")
    )
    intent: Mapped[Optional[str]] = mapped_column(String(32))  # detected intent

    # Input/Output data (JSON)
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    subagent_result: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Error tracking
    error: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    # User and space context
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Timestamps
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.datetime.utcnow,
    )

    # =========================================================================
    # Agent-First: Trade Goal Support
    # =========================================================================


    # 交易目标类型
    trade_goal_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # sell_asset, buy_asset, price_inquiry

    # 执行计划ID
    execution_plan_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

    # 进度跟踪（0-100）
    progress_percentage: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), nullable=False
    )

    # 当前步骤
    current_step: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )


class AssetClusters(Base):
    """Asset clustering results for organization."""

    __tablename__ = "asset_clusters"
    __table_args__ = (
        Index("idx_asset_clusters_space", "space_id"),
        Index("idx_asset_clusters_graph_id", "graph_cluster_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Cluster metadata
    summary_report: Mapped[Optional[str]] = mapped_column(Text)  # Markdown report
    graph_cluster_id: Mapped[Optional[str]] = mapped_column(
        String(128)
    )  # Neo4j cluster ID
    cluster_method: Mapped[Optional[str]] = mapped_column(
        String(32)
    )  # community_detection, etc.

    asset_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    # Publication status
    publication_ready: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.datetime.utcnow,
    )


class AssetClusterMembership(Base):
    """Links assets to clusters for organization."""

    __tablename__ = "asset_cluster_memberships"
    __table_args__ = (
        UniqueConstraint("cluster_id", "asset_id", name="uk_cluster_asset"),
        Index("idx_cluster_membership_asset", "asset_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # Similarity/strength metrics
    similarity_score: Mapped[Optional[float]] = mapped_column(Float)
    cluster_role: Mapped[Optional[str]] = mapped_column(
        String(32)
    )  # core, peripheral, outlier

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    cluster: Mapped["AssetClusters"] = relationship(
        "AssetClusters", back_populates="memberships"
    )


# Add back-populates to AssetClusters
AssetClusters.memberships: Mapped[List["AssetClusterMembership"]] = relationship(
    "AssetClusterMembership", back_populates="cluster"
)


class ReviewLogs(Base):
    """Document review audit trail."""

    __tablename__ = "review_logs"
    __table_args__ = (
        Index("idx_review_logs_doc", "doc_id"),
        Index("idx_review_logs_status", "final_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )

    review_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # quality, compliance, completeness
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Detailed issues found
    issues: Mapped[Optional[dict]] = mapped_column(JSONB)  # List of issue objects
    recommendations: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Rework tracking
    rework_needed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    rework_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_rework: Mapped[int] = mapped_column(Integer, server_default=text("3"))

    # Final status
    final_status: Mapped[str] = mapped_column(
        review_status_enum, server_default=text("'pending'")
    )
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    document: Mapped["Documents"] = relationship(
        "Documents", back_populates="review_logs"
    )


# Add back-populates to Documents
Documents.review_logs: Mapped[List["ReviewLogs"]] = relationship(
    "ReviewLogs", back_populates="document", order_by="ReviewLogs.created_at.desc()"
)


# ============================================================================
# Trade System Models - Production Ready
# ============================================================================

listing_status_enum = Enum(
    "draft",
    "active",
    "paused",
    "sold_out",
    "delisted",
    "suspended",
    name="listing_status",
)
order_status_enum = Enum(
    "pending", "completed", "cancelled", "refunded", "disputed", name="order_status"
)
yield_strategy_enum = Enum(
    "conservative", "balanced", "aggressive", name="yield_strategy"
)


class TradeListings(Base):
    """Digital asset marketplace listings."""

    __tablename__ = "trade_listings"
    __table_args__ = (
        Index("idx_listings_status", "status"),
        Index("idx_listings_seller", "seller_user_id"),
        Index("idx_listings_category", "category"),
        Index("idx_listings_price", "price_credits"),
        Index("idx_listings_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    asset_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    space_public_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Seller info
    seller_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seller_alias: Mapped[str] = mapped_column(String(64), nullable=False)

    # Asset content
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'knowledge_report'")
    )
    tags: Mapped[List[str]] = mapped_column(
        ARRAY(String(32)), server_default=text("'{}'")
    )

    # Price in cents (integer to avoid floating point issues)
    price_credits: Mapped[int] = mapped_column(Integer, nullable=False)

    # Public info (visible before purchase)
    public_summary: Mapped[Optional[str]] = mapped_column(Text)
    preview_excerpt: Mapped[Optional[str]] = mapped_column(Text)

    # Delivery payload (encrypted)
    delivery_payload_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary)

    # Status
    status: Mapped[str] = mapped_column(
        listing_status_enum, server_default=text("'draft'")
    )

    # Statistics
    purchase_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    market_view_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    revenue_total: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))

    # Rights template snapshot
    rights_template: Mapped[Dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))

    # Auto repricing
    auto_reprice_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true")
    )
    last_reprice_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    demand_score: Mapped[float] = mapped_column(Float, server_default=text("0"))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.datetime.utcnow,
    )

    # Relationships
    seller: Mapped["Users"] = relationship(
        "Users", foreign_keys=[seller_user_id], back_populates="trade_listings"
    )
    orders: Mapped[List["TradeOrders"]] = relationship(
        "TradeOrders", back_populates="listing", foreign_keys="TradeOrders.listing_id"
    )


class TradeOrders(Base):
    """Purchase orders for digital assets."""

    __tablename__ = "trade_orders"
    __table_args__ = (
        Index("idx_orders_buyer", "buyer_user_id"),
        Index("idx_orders_seller", "seller_user_id"),
        Index("idx_orders_listing", "listing_id"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    listing_id: Mapped[str] = mapped_column(String(32), ForeignKey("trade_listings.public_id"), nullable=False)
    buyer_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seller_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Snapshot at purchase time
    asset_title_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_alias_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)

    # Amounts in cents
    price_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_income: Mapped[int] = mapped_column(Integer, nullable=False)

    # Delivery content (encrypted snapshot)
    delivery_payload_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary)

    # Status
    status: Mapped[str] = mapped_column(
        order_status_enum, server_default=text("'pending'")
    )

    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # Relationships
    buyer: Mapped["Users"] = relationship(
        "Users", foreign_keys=[buyer_user_id], back_populates="trade_orders_buyer"
    )
    seller: Mapped["Users"] = relationship(
        "Users", foreign_keys=[seller_user_id], back_populates="trade_orders_seller"
    )
    listing: Mapped["TradeListings"] = relationship(
        "TradeListings",
        foreign_keys=[listing_id],
        primaryjoin="TradeOrders.listing_id == TradeListings.public_id",
        back_populates="orders",
    )


class TradeWallets(Base):
    """User wallet for credits - with optimistic locking."""

    __tablename__ = "trade_wallets"
    __table_args__ = (Index("idx_wallets_user", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Balances in cents (avoid floating point)
    # SECURITY: Default is 0 to prevent abuse. Users must complete KYC to deposit.
    liquid_credits: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )  # Default 0.00 - requires deposit/KYC
    cumulative_sales_earnings: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    cumulative_yield_earnings: Mapped[int] = mapped_column(
        BigInteger, server_default=text("0")
    )
    total_spent: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))

    # Yield settings
    auto_yield_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true")
    )
    yield_strategy: Mapped[str] = mapped_column(
        yield_strategy_enum, server_default=text("'balanced'")
    )
    last_yield_run_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Optimistic locking version
    version: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.datetime.utcnow,
    )

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="trade_wallet")


class TradeHoldings(Base):
    """Assets owned by users after purchase."""

    __tablename__ = "trade_holdings"
    __table_args__ = (
        Index("idx_holdings_user", "user_id"),
        Index("idx_holdings_listing", "listing_id"),
        UniqueConstraint("user_id", "listing_id", name="uk_holdings_user_listing"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    listing_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # Snapshot info
    asset_title: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_alias: Mapped[str] = mapped_column(String(64), nullable=False)

    # Access control
    access_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    download_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_accessed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    purchased_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # Relationships
    owner: Mapped["Users"] = relationship("Users", back_populates="trade_holdings")


class TradeYieldRuns(Base):
    """Yield accrual execution logs."""

    __tablename__ = "trade_yield_runs"
    __table_args__ = (
        Index("idx_yield_runs_user", "user_id"),
        Index("idx_yield_runs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    strategy: Mapped[str] = mapped_column(yield_strategy_enum, nullable=False)
    annual_rate: Mapped[float] = mapped_column(Float, nullable=False)
    elapsed_days: Mapped[float] = mapped_column(Float, nullable=False)

    # Amount in cents
    yield_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Wallet snapshots
    liquid_credits_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    liquid_credits_after: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Related repricing records
    listing_adjustments: Mapped[List[dict]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="trade_yield_runs")


class TradeTransactionLog(Base):
    """Audit trail for all credit transactions."""

    __tablename__ = "trade_transaction_log"
    __table_args__ = (
        Index("idx_tx_log_user", "user_id"),
        Index("idx_tx_log_type", "tx_type"),
        Index("idx_tx_log_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    tx_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # deposit, purchase, sale_income, yield_accrual, refund

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    listing_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Amount changes in cents
    amount_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Metadata
    record_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # Relationships
    user: Mapped["Users"] = relationship("Users", back_populates="trade_transactions")





# =============================================================================
# Memory Management Models - 分层记忆管理
# =============================================================================


class ConversationSessions(Base):
    """
    对话会话记录 - L2 中期记忆

    存储用户对话的完整历史，支持会话摘要和检索。
    """

    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index("idx_conv_session_user", "user_id"),
        Index("idx_conv_session_status", "status"),
        Index("idx_conv_session_space", "space_id"),
        Index("idx_conv_session_last_msg", "user_id", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 会话元数据
    title: Mapped[Optional[str]] = mapped_column(String(255))  # LLM 生成的标题
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'active'")
    )  # active/archived/deleted
    space_id: Mapped[Optional[str]] = mapped_column(String(32))  # 关联的空间

    # 统计
    message_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    # 摘要（定期生成）
    summary: Mapped[Optional[str]] = mapped_column(Text)
    summary_tokens: Mapped[Optional[int]] = mapped_column(Integer)

    # 时间
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_message_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # 关系
    messages: Mapped[List["ConversationMessages"]] = relationship(
        "ConversationMessages",
        back_populates="session",
        order_by="ConversationMessages.created_at",
    )


class ConversationMessages(Base):
    """
    对话消息记录 - L2 中期记忆

    存储单条对话消息，支持向量嵌入用于语义检索。
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("idx_msg_session_time", "session_id", "created_at"),
        Index("idx_msg_user", "user_id"),
        Index("idx_msg_agent_type", "agent_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("conversation_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 消息内容
    role: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # user/assistant/system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 关联 Agent 类型
    agent_type: Mapped[Optional[str]] = mapped_column(
        String(32)
    )  # QA/DataProcess/Trade/...

    # 向量嵌入（用于语义检索）- 可选，用于高级检索
    embedding: Mapped[Optional[object]] = mapped_column(Vector(1536), nullable=True)

    # 元数据
    record_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 时间
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # 关系
    session: Mapped["ConversationSessions"] = relationship(
        "ConversationSessions", back_populates="messages"
    )


class UserPreferences(Base):
    """
    用户偏好 - L3 长期记忆

    存储用户的显式和隐式偏好，用于个性化服务。
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "pref_type", "key", name="uk_user_pref"),
        Index("idx_pref_user", "user_id"),
        Index("idx_pref_type", "pref_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 偏好类型
    pref_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # search/response/style/price/...

    # 偏好内容
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 编码

    # 置信度和来源
    confidence: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    source: Mapped[str] = mapped_column(
        String(16), server_default=text("'implicit'")
    )  # explicit/implicit/inferred

    # 上下文（如何得出这个偏好）
    context: Mapped[Optional[str]] = mapped_column(Text)

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UserMemories(Base):
    """
    用户长期记忆 - L3 长期记忆

    从对话中提取的关键信息，用于跨会话的知识保持。
    """

    __tablename__ = "user_memories"
    __table_args__ = (
        Index("idx_memory_user", "user_id"),
        Index("idx_memory_user_type", "user_id", "memory_type"),
        Index("idx_memory_source", "source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    memory_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 记忆内容
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 类型
    memory_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # fact/preference/goal/relationship/...

    # 向量嵌入（用于语义检索）
    embedding: Mapped[Optional[object]] = mapped_column(Vector(1536), nullable=True)

    # 来源
    source: Mapped[str] = mapped_column(
        String(32), server_default=text("'conversation'")
    )  # conversation/document/manual
    source_session_id: Mapped[Optional[str]] = mapped_column(String(32))  # 来源会话

    # 重要性（1-10）
    importance: Mapped[int] = mapped_column(Integer, server_default=text("5"))

    # 访问统计
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_accessed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # 有效期（可选）
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AgentDecisionLogs(Base):
    """
    Agent 决策日志

    记录 Agent 的决策过程，用于调试和策略优化。
    """

    __tablename__ = "agent_decision_logs"
    __table_args__ = (
        Index("idx_decision_task", "task_id"),
        Index("idx_decision_agent", "agent_type"),
        Index("idx_decision_time", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # QA/DataProcess/Trade/...

    # 决策信息
    decision: Mapped[str] = mapped_column(String(64), nullable=False)  # action taken
    context: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )  # 决策时的上下文
    reasoning: Mapped[Optional[str]] = mapped_column(Text)  # 决策理由

    # 输入输出
    input_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    output_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 结果（异步更新）
    result_status: Mapped[Optional[str]] = mapped_column(String(16))  # success/failure
    result_feedback: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AgentIntermediateResults(Base):
    """
    Agent 中间结果缓存

    存储 Agent 工作流的中间结果，支持断点续传和结果复用。
    """

    __tablename__ = "agent_intermediate_results"
    __table_args__ = (
        Index("idx_intermediate_task", "task_id"),
        Index("idx_intermediate_step", "task_id", "step_name"),
        Index("idx_intermediate_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    result_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # 结果数据
    result_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # text/json/file/...
    result_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 元数据
    record_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 过期时间
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )



# Memory management relationships
ConversationSessions.user = relationship(
    "Users", back_populates="conversation_sessions"
)
ConversationMessages.user = relationship("Users")
UserPreferences.user = relationship("Users", back_populates="preferences")
UserMemories.user = relationship("Users", back_populates="memories")


# =============================================================================
# ACL & Security Models - 权限控制与审计
# =============================================================================


class SpaceMembers(Base):
    """
    Space 成员管理 - 协作权限控制
    """

    __tablename__ = "space_members"
    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uk_space_member"),
        Index("idx_space_member_user", "user_id"),
        Index("idx_space_member_role", "space_id", "role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    space_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("spaces.public_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 角色: owner, admin, editor, viewer
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'viewer'")
    )

    # 细粒度权限 (覆盖角色默认权限)
    permissions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 邀请信息
    invited_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    invite_status: Mapped[str] = mapped_column(
        String(16), server_default=text("'active'")
    )  # pending/active/removed

    # 统计
    joined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_accessed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # 通知偏好
    notification_preferences: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )


class ResourceACL(Base):
    """
    资源级访问控制列表 (ACL)

    支持细粒度的资源权限控制。
    """

    __tablename__ = "resource_acl"
    __table_args__ = (
        Index("idx_acl_resource", "resource_type", "resource_id"),
        Index("idx_acl_user", "user_id"),
        Index("idx_acl_inherit", "inherit_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acl_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    # 资源信息
    resource_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # space/file/asset/knowledge
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # 被授权主体
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    role_id: Mapped[Optional[str]] = mapped_column(String(32))  # 预留：角色ID
    is_public: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # 权限位
    can_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_write: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_delete: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_share: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_execute: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )  # 用于 Agent 执行

    # 权限条件 (ABAC)
    conditions: Mapped[Optional[dict]] = mapped_column(
        JSONB
    )  # {"time_range": "9-18", "ip_whitelist": [...]}

    # 继承
    inherit_from: Mapped[Optional[str]] = mapped_column(String(32))  # 父资源ID
    priority: Mapped[int] = mapped_column(
        Integer, server_default=text("0")
    )  # 权限优先级 (高覆盖低)

    # 有效期
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=datetime.datetime.utcnow,
    )

    # 授权者
    granted_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))


class AuditLogs(Base):
    """
    审计日志 - 安全与合规

    记录所有敏感操作，不可修改。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_time", "created_at"),
        Index("idx_audit_risk", "risk_score"),
        PrimaryKeyConstraint("id", "created_at"),  # 分区表主键必须包含分区键
        {"postgresql_partition_by": "RANGE (created_at)"},  # 按时间分区
    )

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    log_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # 用户信息
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"))
    user_email: Mapped[Optional[str]] = mapped_column(
        String(255)
    )  # 快照，即使用户删除也能追溯

    # 客户端信息
    client_ip: Mapped[Optional[str]] = mapped_column(String(45))  # IPv6 兼容
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    session_id: Mapped[Optional[str]] = mapped_column(String(64))

    # 操作信息
    action: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # user.login, file.download, etc.
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # 操作详情
    previous_state: Mapped[Optional[dict]] = mapped_column(JSONB)  # 变更前状态
    new_state: Mapped[Optional[dict]] = mapped_column(JSONB)  # 变更后状态
    request_payload: Mapped[Optional[dict]] = mapped_column(JSONB)  # 请求参数 (脱敏)

    # 结果
    result: Mapped[str] = mapped_column(
        String(16), server_default=text("'success'")
    )  # success/failure/denied/error
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # 风险评分 (0-1)
    risk_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    risk_reasons: Mapped[Optional[list]] = mapped_column(
        JSONB
    )  # ["unusual_ip", "off_hours_access"]

    # 处理状态
    alert_sent: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AssetProvenance(Base):
    """
    资产来源记录

    记录资产的来源和出处信息。
    """

    __tablename__ = "asset_provenance"
    __table_args__ = (
        Index("idx_prov_asset", "asset_id"),
        Index("idx_prov_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provenance_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    # 资产信息
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)  # file/document/knowledge

    # 来源信息
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # upload/import/generation
    source_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    source_description: Mapped[Optional[str]] = mapped_column(Text)

    # 来源详情
    origin_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    creator_name: Mapped[Optional[str]] = mapped_column(String(255))
    license_type: Mapped[Optional[str]] = mapped_column(String(64))

    # 验证信息
    verification_hash: Mapped[Optional[str]] = mapped_column(String(64))
    verification_method: Mapped[Optional[str]] = mapped_column(String(32))

    # 记录元数据
    record_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DataLineage(Base):
    """
    数据血缘追踪

    追踪数据从来源到当前状态的完整链路。
    """

    __tablename__ = "data_lineage"
    __table_args__ = (
        Index("idx_lineage_current", "current_entity_type", "current_entity_id"),
        Index("idx_lineage_source", "source_type", "source_id"),
        Index("idx_lineage_parent", "parent_lineage_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lineage_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    # 源信息
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # upload/api/agent_generation/import
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_metadata: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    # 转换链
    transformations: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'")
    )  # [{"step": "chunking", "timestamp": "...", "config": {...}}]

    # 当前状态
    current_entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # file/chunk/knowledge/asset
    current_entity_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # 血缘关系 (树形结构)
    parent_lineage_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("data_lineage.lineage_id")
    )

    # 审计
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # 关系
    parent: Mapped[Optional["DataLineage"]] = relationship(
        "DataLineage", remote_side=[lineage_id], back_populates="children"
    )
    children: Mapped[List["DataLineage"]] = relationship(
        "DataLineage", back_populates="parent"
    )


class CollaborationOperations(Base):
    """
    协作操作记录

    用于实时同步和冲突检测。
    """

    __tablename__ = "collaboration_operations"
    __table_args__ = (
        Index("idx_collab_space", "space_id"),
        Index("idx_collab_user", "user_id"),
        Index("idx_collab_entity", "entity_type", "entity_id"),
        Index("idx_collab_time", "operation_timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    space_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("spaces.public_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )

    # 操作类型
    operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # edit/delete/create/move
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # file/markdown/graph_node
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)

    # 操作详情
    previous_state: Mapped[Optional[dict]] = mapped_column(JSONB)
    new_state: Mapped[dict] = mapped_column(JSONB)
    operation_summary: Mapped[Optional[str]] = mapped_column(
        String(255)
    )  # 人类可读摘要

    # 向量时钟 (用于冲突解决)
    vector_clock: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # {"user_123": 5, "user_456": 3}

    # 时间戳
    operation_timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # 同步状态
    synced_to_clients: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'")
    )  # ["client_id_1", "client_id_2"]



SpaceMembers.user = relationship(
    "Users", foreign_keys=[SpaceMembers.user_id], back_populates="space_memberships"
)
SpaceMembers.inviter = relationship(
    "Users", foreign_keys=[SpaceMembers.invited_by], back_populates="invited_members"
)
SpaceMembers.space = relationship("Spaces", back_populates="members")

Spaces.members = relationship("SpaceMembers", back_populates="space")

AuditLogs.user = relationship(
    "Users", foreign_keys=[AuditLogs.user_id], back_populates="audit_logs"
)

DataLineage.creator = relationship("Users", back_populates="lineage_created")

CollaborationOperations.user = relationship("Users", back_populates="collaboration_ops")
CollaborationOperations.space = relationship(
    "Spaces", back_populates="collaboration_ops"
)

Spaces.collaboration_ops = relationship(
    "CollaborationOperations", back_populates="space"
)


# ============================================================================
# Event Sourcing Blackboard - 事件溯源黑板模式
# ============================================================================

blackboard_event_type_enum = Enum(
    "BID",  # 竞拍出价
    "OFFER",  # 协商报价
    "COUNTER",  # 反报价
    "ACCEPT",  # 接受
    "REJECT",  # 拒绝
    "WITHDRAW",  # 退出
    "CEILING_SET",  # 设置天花板价
    "FLOOR_SET",  # 设置地板价
    "AGREEMENT",  # 达成协议
    "TIMEOUT",  # 超时
    name="blackboard_event_type",
)


class BlackboardEvents(Base):
    """
    事件溯源黑板 - 不可变事件流

    设计原则：
    1. 只追加（Append-only），不修改
    2. 每个事件有全局唯一的 sequence_number
    3. 通过 State Projector 计算当前状态
    4. 支持时序图谱分析

    安全优势：
    - 不可否认性：所有操作都有永久记录
    - 可审计：完整的操作历史
    - 防篡改：事件一旦写入不可修改
    """

    __tablename__ = "blackboard_events"
    __table_args__ = (
        Index("idx_blackboard_session_seq", "session_id", "sequence_number"),
        Index("idx_blackboard_session_time", "session_id", "event_timestamp"),
        Index("idx_blackboard_agent", "agent_id", "event_timestamp"),
        Index("idx_blackboard_type", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 事件唯一标识
    event_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    # 关联的会话（协商或拍卖）
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "negotiation" | "auction"

    # 序列号 - 用于保证事件顺序和乐观锁
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 事件类型
    event_type: Mapped[str] = mapped_column(blackboard_event_type_enum, nullable=False)

    # 发起者
    agent_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # user_id
    agent_role: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "buyer" | "seller" | "bidder"

    # 事件载荷（使用 Pydantic 模型序列化）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 事件时间戳（业务时间，非数据库时间）
    event_timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # 逻辑时钟（用于分布式系统的因果排序）
    vector_clock: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # {"node_id": counter}

    # 时间戳
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    # 图谱集成 - 关联到知识图谱（可选，用于时序分析）
    graph_node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class BlackboardSnapshots(Base):
    """
    黑板状态快照 - 加速状态恢复

    当事件数量过多时，定期生成快照以减少重放事件的开销。
    """

    __tablename__ = "blackboard_snapshots"
    __table_args__ = (Index("idx_snapshot_session", "session_id", "sequence_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # 快照对应的序列号
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 快照状态（JSON）
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 事件数量（用于决定何时生成新快照）
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class AgentRateLimit(Base):
    """
    Agent 频率限流 - 防止恶意 Agent 抢占资源

    基于滑动窗口的限流机制。
    """

    __tablename__ = "agent_rate_limits"
    __table_args__ = (Index("idx_rate_limit_agent", "agent_id", "window_start"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    agent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # 限流类型
    limit_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "bid" | "offer" | "message"

    # 时间窗口开始
    window_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # 窗口内的请求计数
    request_count: Mapped[int] = mapped_column(Integer, default=1)

    # 被拒绝的请求数（用于检测攻击）
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)

    # 限流状态
    is_throttled: Mapped[bool] = mapped_column(Boolean, default=False)
    throttle_until: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


class OutboxEvents(Base):
    """
    Outbox 事件表 - 保证事务一致性

    设计原则：
    1. 业务操作和事件写入在同一个事务中完成
    2. 后台 worker 定期读取未处理事件并执行
    3. 处理成功后标记为已处理
    4. 支持幂等和重试
    """

    __tablename__ = "outbox_events"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 事件类型
    aggregate_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 聚合根类型
    aggregate_id: Mapped[str] = mapped_column(String(32), nullable=False)  # 聚合根ID

    # 事件载荷
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # 处理状态
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, processing, completed, failed

    # 重试机制
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    # 时间戳
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    processed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 处理信息
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processor_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # 处理者ID

    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
        Index("idx_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )


# =============================================================================
# Data Rights Models (Phase 1)
# =============================================================================

class DataSensitivityLevel(str, PyEnum):
    """数据敏感度级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComputationMethod(str, PyEnum):
    """隐私计算方法"""
    FEDERATED_LEARNING = "federated_learning"
    MULTI_PARTY_COMPUTATION = "mpc"
    TEE = "trusted_execution_environment"
    DIFFERENTIAL_PRIVACY = "differential_privacy"
    RAW_DATA = "raw_data"


class DataRightsStatus(str, PyEnum):
    """数据权益交易状态"""
    PENDING = "pending"
    ACTIVE = "active"
    GRANTED = "granted"
    EXPIRED = "expired"
    REVOKED = "revoked"
    VIOLATED = "violated"


class AssetOrigin(str, PyEnum):
    """数字资产来源"""
    SPACE_GENERATED = "space_generated"
    CHAT_GENERATED = "chat_generated"
    ASSET_DERIVED = "asset_derived"


class AssetStatus(str, PyEnum):
    """数字资产状态"""
    DRAFT = "draft"
    AWAITING_LISTING_CONFIRMATION = "awaiting_listing_confirmation"
    LISTED = "listed"
    ARCHIVED = "archived"


class DataAssets(Base):
    """数据资产表"""
    __tablename__ = "data_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset_id = Column(String(64), unique=True, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset_name = Column(String(200), nullable=False)
    asset_description = Column(Text, nullable=True)
    data_type = Column(String(50), nullable=False)
    sensitivity_level = Column(Enum(DataSensitivityLevel), nullable=False)
    default_anonymization_level = Column(Integer, default=2)
    quality_completeness = Column(Float, default=0.0)
    quality_accuracy = Column(Float, default=0.0)
    quality_timeliness = Column(Float, default=0.0)
    quality_consistency = Column(Float, default=0.0)
    quality_uniqueness = Column(Float, default=0.0)
    quality_overall_score = Column(Float, default=0.0)
    raw_data_source = Column(String(500), nullable=False)
    lineage_root = Column(String(64), nullable=True)
    processing_chain_hash = Column(String(64), nullable=True)
    storage_location = Column(String(500), nullable=False)
    data_size_bytes = Column(Integer, default=0)
    record_count = Column(Integer, nullable=True)
    related_entities = Column(JSONB, default=list)
    is_active = Column(Boolean, default=True)
    is_available_for_trade = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    # 知识资产扩展字段
    space_public_id = Column(String(32), nullable=True)
    asset_type = Column(String(32), default="knowledge")
    asset_origin = Column(String(32), default="space_generated")
    asset_status = Column(String(32), default="draft")
    content_markdown = Column(Text, nullable=True)
    content_summary = Column(String(500), nullable=True)
    graph_snapshot = Column(JSONB, default=dict)
    generation_prompt = Column(Text, nullable=True)
    source_document_ids = Column(JSONB, default=list)
    source_asset_ids = Column(JSONB, default=list)

    owner = relationship("Users", back_populates="data_assets")
    rights_transactions = relationship("DataRightsTransactions", back_populates="data_asset")

    __table_args__ = (
        Index("ix_data_assets_owner", "owner_id"),
        Index("ix_data_assets_sensitivity", "sensitivity_level"),
        Index("ix_data_assets_type", "data_type"),
        Index("ix_data_assets_quality", "quality_overall_score"),
        Index("ix_data_assets_space", "space_public_id"),
    )


class DataRightsTransactions(Base):
    """数据权益交易表"""
    __tablename__ = "data_rights_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(64), unique=True, nullable=False, index=True)
    negotiation_id = Column(String(64), nullable=True)  # 遗留字段，协商表已移除
    listing_id = Column(String(64), nullable=True, index=True)
    order_id = Column(String(64), nullable=True, index=True)
    data_asset_id = Column(String(64), ForeignKey("data_assets.asset_id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rights_types = Column(JSONB, nullable=False)
    usage_scope = Column(JSONB, nullable=False)
    restrictions = Column(JSONB, default=list)
    computation_method = Column(Enum(ComputationMethod), nullable=False)
    anonymization_level = Column(Integer, nullable=False)
    computation_constraints = Column(JSONB, default=dict)
    valid_from = Column(DateTime, nullable=False)
    valid_until = Column(DateTime, nullable=False)
    agreed_price = Column(Float, nullable=True)
    currency = Column(String(10), default="CNY")
    status = Column(Enum(DataRightsStatus), default=DataRightsStatus.PENDING)
    settlement_tx_hash = Column(String(128), nullable=True)
    settlement_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    data_asset = relationship("DataAssets", back_populates="rights_transactions")
    owner = relationship("Users", foreign_keys=[owner_id], back_populates="rights_granted")
    buyer = relationship("Users", foreign_keys=[buyer_id], back_populates="rights_received")
    audit_logs = relationship("DataAccessAuditLogs", back_populates="transaction")

    __table_args__ = (
        Index("ix_rights_tx_asset", "data_asset_id"),
        Index("ix_rights_tx_owner", "owner_id"),
        Index("ix_rights_tx_buyer", "buyer_id"),
        Index("ix_rights_tx_status", "status"),
        Index("ix_rights_tx_validity", "valid_from", "valid_until"),
    )


class DataAccessAuditLogs(Base):
    """数据访问审计日志表"""
    __tablename__ = "data_access_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(String(64), unique=True, nullable=False, index=True)
    transaction_id = Column(String(64), ForeignKey("data_rights_transactions.transaction_id"), nullable=False)
    negotiation_id = Column(String(64), nullable=True)
    data_asset_id = Column(String(64), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    access_timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    access_purpose = Column(String(200), nullable=False)
    computation_method_used = Column(Enum(ComputationMethod), nullable=False)
    query_fingerprint = Column(String(64), nullable=False)
    query_complexity_score = Column(Float, nullable=True)
    result_size_bytes = Column(Integer, default=0)
    result_row_count = Column(Integer, nullable=True)
    result_aggregation_level = Column(String(50), nullable=False)
    policy_compliance_check = Column(JSONB, default=dict)
    risk_score = Column(Float, nullable=True)
    anomaly_flags = Column(JSONB, default=list)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    transaction = relationship("DataRightsTransactions", back_populates="audit_logs")
    buyer = relationship("Users", back_populates="access_logs")

    __table_args__ = (
        Index("ix_audit_tx", "transaction_id"),
        Index("ix_audit_buyer", "buyer_id"),
        Index("ix_audit_timestamp", "access_timestamp"),
        Index("ix_audit_risk", "risk_score"),
    )


class PolicyViolations(Base):
    """策略违规记录表"""
    __tablename__ = "policy_violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    violation_id = Column(String(64), unique=True, nullable=False, index=True)
    transaction_id = Column(String(64), ForeignKey("data_rights_transactions.transaction_id"), nullable=False)
    negotiation_id = Column(String(64), nullable=True)
    data_asset_id = Column(String(64), nullable=False)
    violation_type = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    violation_details = Column(JSONB, nullable=False)
    evidence = Column(JSONB, nullable=False)
    potential_data_exposure = Column(Float, nullable=True)
    affected_records_estimate = Column(Integer, nullable=True)
    automatic_action_taken = Column(String(200), nullable=True)
    manual_review_status = Column(String(50), default="pending")
    resolution_notes = Column(Text, nullable=True)
    detected_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    resolved_at = Column(DateTime, nullable=True)

    transaction = relationship("DataRightsTransactions")

    __table_args__ = (
        Index("ix_violation_tx", "transaction_id"),
        Index("ix_violation_type", "violation_type"),
        Index("ix_violation_severity", "severity"),
        Index("ix_violation_status", "manual_review_status"),
    )


class DataLineageNodes(Base):
    """数据血缘节点表"""
    __tablename__ = "data_lineage_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String(64), unique=True, nullable=False, index=True)
    asset_id = Column(String(64), ForeignKey("data_assets.asset_id"), nullable=False)
    node_type = Column(String(50), nullable=False)
    parent_nodes = Column(JSONB, default=list)
    processing_logic_hash = Column(String(64), nullable=False)
    quality_metrics = Column(JSONB, default=dict)
    provenance_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    __table_args__ = (
        Index("ix_lineage_asset", "asset_id"),
        Index("ix_lineage_type", "node_type"),
    )




# ============================================================================
# User-Level Agent Configuration
# ============================================================================

class LLMProvider(str, PyEnum):
    """LLM 提供商枚举"""
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    QWEN = "qwen"
    CUSTOM = "custom"


class UserAgentConfig(Base):
    """
    用户级 Agent 配置表

    每个用户可以配置自己的 LLM API，实现个性化的 Agent 行为
    """
    __tablename__ = "user_agent_configs"
    __table_args__ = (
        UniqueConstraint("user_id", name="uk_user_agent_config"),
        Index("idx_agent_config_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # LLM 配置
    provider = Column(Enum(LLMProvider), default=LLMProvider.DEEPSEEK, nullable=False)
    model = Column(String(100), default="deepseek-chat")
    api_key_encrypted = Column(Text, nullable=True)  # 加密的 API Key
    base_url = Column(String(500), nullable=True)  # 自定义 base URL

    # Agent 行为配置
    temperature = Column(Float, default=0.2)
    max_tokens = Column(Integer, default=2048)
    system_prompt = Column(Text, nullable=True)  # 自定义系统提示词

    # 交易场景专用配置
    trade_auto_negotiate = Column(Boolean, default=False)  # 是否自动协商
    trade_max_rounds = Column(Integer, default=10)
    trade_min_profit_margin = Column(Float, default=0.1)  # 最小利润率（卖方）
    trade_max_budget_ratio = Column(Float, default=0.9)  # 最大预算比例（买方）

    # 状态
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # 是否为默认配置（用于回退）

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    # 关系
    user = relationship("Users", back_populates="agent_configs")


class FeatureType(PyEnum):
    """功能类型枚举 - 用于标识Token使用的功能边界"""

    CHAT = "chat"                          # RAG对话
    CHAT_STREAM = "chat_stream"            # 流式对话
    ASSET_GENERATION = "asset_generation"  # 资产生成
    ASSET_ORGANIZE = "asset_organize"      # 资产整理
    TRADE_PRICING = "trade_pricing"        # 交易定价
    INGEST_PIPELINE = "ingest_pipeline"    # 文档摄入
    GRAPH_CONSTRUCTION = "graph_construction"  # 知识图谱构建
    REVIEW = "review"                      # 文档审核
    FILE_QUERY = "file_query"              # 文件查询
    EMBEDDING = "embedding"                # 文本嵌入
    OTHER = "other"                        # 其他


class TokenUsage(Base):
    """
    Token用量统计表

    记录每个用户、每个功能、每个模型的Token消耗情况
    支持实时查询用量统计和成本分析
    """
    __tablename__ = "token_usages"
    __table_args__ = (
        Index("idx_token_usage_user", "user_id"),
        Index("idx_token_usage_feature", "feature_type"),
        Index("idx_token_usage_model", "model"),
        Index("idx_token_usage_created", "created_at"),
        Index("idx_token_usage_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # 模型信息
    provider = Column(Enum(LLMProvider), nullable=False)  # 复用LLMProvider枚举
    model = Column(String(100), nullable=False)  # 具体模型名称
    is_custom_api = Column(Boolean, default=False)  # 是否使用用户自己的API

    # 功能边界标识
    feature_type = Column(Enum(FeatureType), nullable=False)
    feature_detail = Column(String(200), nullable=True)  # 详细功能描述

    # Token用量 (来自LLM API响应)
    prompt_tokens = Column(Integer, default=0)      # 输入token数
    completion_tokens = Column(Integer, default=0)  # 输出token数
    total_tokens = Column(Integer, default=0)       # 总token数

    # 成本计算 (单位: 美元)
    prompt_cost = Column(Float, default=0.0)        # 输入成本
    completion_cost = Column(Float, default=0.0)    # 输出成本
    total_cost = Column(Float, default=0.0)         # 总成本

    # 请求元数据
    request_id = Column(String(100), nullable=True, index=True)  # 关联的请求ID
    session_id = Column(String(100), nullable=True, index=True)  # 会话ID
    latency_ms = Column(Integer, nullable=True)     # 请求延迟(毫秒)
    status = Column(String(20), default="success")  # success/error
    error_message = Column(Text, nullable=True)     # 错误信息

    # 扩展信息 (JSON格式，存储额外上下文)
    extra_metadata = Column(JSONB, server_default=text("'{}'"))

    # 时间戳
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # 关系
    user = relationship("Users", back_populates="token_usages")

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider.value if self.provider else None,
            "model": self.model,
            "is_custom_api": self.is_custom_api,
            "feature_type": self.feature_type.value if self.feature_type else None,
            "feature_detail": self.feature_detail,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_cost": round(self.prompt_cost, 6),
            "completion_cost": round(self.completion_cost, 6),
            "total_cost": round(self.total_cost, 6),
            "request_id": self.request_id,
            "session_id": self.session_id,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_message": self.error_message,
            "extra_metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ModelPrice(Base):
    """
    模型定价表

    存储各模型的Token单价，用于成本计算
    """
    __tablename__ = "model_prices"
    __table_args__ = (
        UniqueConstraint("provider", "model", name="uk_model_price"),
        Index("idx_model_price_provider", "provider"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 模型信息
    provider = Column(Enum(LLMProvider), nullable=False)
    model = Column(String(100), nullable=False)

    # 定价 (每1K tokens的美元价格)
    prompt_price_per_1k = Column(Float, nullable=False)    # 输入价格
    completion_price_per_1k = Column(Float, nullable=False)  # 输出价格

    # 货币和有效期
    currency = Column(String(10), default="USD")
    effective_from = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    effective_to = Column(DateTime, nullable=True)  # null表示当前有效

    # 状态
    is_active = Column(Boolean, default=True)

    # 元数据
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> tuple[float, float, float]:
        """
        计算Token成本

        Returns:
            (prompt_cost, completion_cost, total_cost)
        """
        prompt_cost = (prompt_tokens / 1000) * self.prompt_price_per_1k
        completion_cost = (completion_tokens / 1000) * self.completion_price_per_1k
        return prompt_cost, completion_cost, prompt_cost + completion_cost


# ============================================================================

# ============================================================================
# Sidechain Logs - Agent Internal Execution Logs
# ============================================================================

class SidechainLog(Base):
    """Agent 执行过程的 Sidechain 日志。

    独立记录每个 Agent 实例的内部执行过程（思考、工具调用、观察、决策），
    与 parent session 的 conversation_messages 隔离，防止上下文污染。
    """

    __tablename__ = "sidechain_logs"
    __table_args__ = (
        Index("idx_sidechain_session", "session_id", "created_at"),
        Index("idx_sidechain_parent", "parent_session_id", "agent_id"),
        Index("idx_sidechain_event", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)

    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # thought | tool_call | observation | decision | error | task_start | task_complete | task_timeout | task_error

    content: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
