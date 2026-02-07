import datetime
import uuid
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
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


identity_type_enum = Enum("password", "phone", "wechat", "github", name="identity_type")
file_status_enum = Enum("active", "archived", "deleted", name="file_status")
upload_status_enum = Enum("init", "uploading", "completed", "failed", name="upload_status")
document_status_enum = Enum("pending", "processing", "completed", "failed", name="document_status")
ingest_status_enum = Enum("queued", "running", "succeeded", "failed", name="ingest_status")


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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

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
    status: Mapped[str] = mapped_column(file_status_enum, server_default=text("'active'"))
    current_version_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

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
        UniqueConstraint("space_id", "parent_id", "name", name="uk_folder_sibling_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    path_cache: Mapped[Optional[str]] = mapped_column(String(2048))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


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
    status: Mapped[str] = mapped_column(upload_status_enum, server_default=text("'init'"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Users(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("user_key", name="uk_user_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    display_name: Mapped[Optional[str]] = mapped_column(String(128))

    spaces: Mapped[List["Spaces"]] = relationship("Spaces", back_populates="owner_user")
    user_auth: Mapped[List["UserAuth"]] = relationship("UserAuth", back_populates="user")
    documents: Mapped[List["Documents"]] = relationship("Documents", back_populates="creator")


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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    owner_user: Mapped["Users"] = relationship("Users", back_populates="spaces")
    documents: Mapped[List["Documents"]] = relationship("Documents", back_populates="space")


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

    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("files.id", ondelete="SET NULL"))
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
    status: Mapped[str] = mapped_column(document_status_enum, server_default=text("'pending'"))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    space: Mapped["Spaces"] = relationship("Spaces", back_populates="documents")
    file: Mapped[Optional["Files"]] = relationship("Files", foreign_keys=[file_id])
    file_version: Mapped[Optional["FileVersions"]] = relationship("FileVersions", foreign_keys=[file_version_id])
    creator: Mapped["Users"] = relationship("Users", back_populates="documents")
    ingest_jobs: Mapped[List["IngestJobs"]] = relationship("IngestJobs", back_populates="document")
    chunks: Mapped[List["DocChunks"]] = relationship("DocChunks", back_populates="document")


class IngestJobs(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (Index("idx_ingest_jobs_doc", "doc_id"),)

    ingest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(ingest_status_enum, server_default=text("'queued'"))
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    document: Mapped["Documents"] = relationship("Documents", back_populates="ingest_jobs")


class DocChunks(Base):
    __tablename__ = "doc_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uk_doc_chunks_doc_index"),
        Index("idx_doc_chunks_doc", "doc_id"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    document: Mapped["Documents"] = relationship("Documents", back_populates="chunks")
    embeddings: Mapped[List["DocChunkEmbeddings"]] = relationship("DocChunkEmbeddings", back_populates="chunk")


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
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    chunk: Mapped["DocChunks"] = relationship("DocChunks", back_populates="embeddings")
