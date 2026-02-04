from typing import Optional, List
import datetime

from sqlalchemy import CHAR, Enum, ForeignKeyConstraint, Index, String, TIMESTAMP, text, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, INTEGER, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FileVersions(Base):
    __tablename__ = 'file_versions'
    __table_args__ = (
        ForeignKeyConstraint(['file_id'], ['files.id'], name='fk_file_versions_file'),
        Index('fk_file_versions_file', 'file_id'),
        UniqueConstraint('public_id', name='uk_version_public_id')
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    version_no: Mapped[int] = mapped_column(INTEGER, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(CHAR(64))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))

    # 建立与文件的双向关联
    file: Mapped['Files'] = relationship(
        'Files',
        foreign_keys=[file_id],
        back_populates='file_versions'
    )

    # 针对循环引用的反向映射
    referenced_as_current: Mapped[List['Files']] = relationship(
        'Files',
        foreign_keys='[Files.current_version_id]',
        back_populates='current_version'
    )


class Files(Base):
    __tablename__ = 'files'
    __table_args__ = (
        # 核心修复：添加 use_alter=True 解决循环依赖导致的排序告警
        ForeignKeyConstraint(
            ['current_version_id'], ['file_versions.id'],
            name='fk_files_current_version',
            use_alter=True
        ),
        UniqueConstraint('public_id', name='uk_file_public_id'),
        Index('fk_files_current_version', 'current_version_id')
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    folder_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mime: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[Optional[int]] = mapped_column(BIGINT)
    sha256: Mapped[Optional[str]] = mapped_column(CHAR(64))
    status: Mapped[str] = mapped_column(Enum('active', 'archived', 'deleted'), server_default=text("'active'"))
    current_version_id: Mapped[Optional[int]] = mapped_column(BIGINT)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))

    # 关系映射
    file_versions: Mapped[List['FileVersions']] = relationship(
        'FileVersions',
        foreign_keys='[FileVersions.file_id]',
        back_populates='file',
        cascade="all, delete-orphan"
    )
    # 核心修复：post_update=True 确保在异步/同步环境能正确处理循环插入
    current_version: Mapped[Optional['FileVersions']] = relationship(
        'FileVersions',
        foreign_keys=[current_version_id],
        back_populates='referenced_as_current',
        post_update=True
    )


class Folders(Base):
    __tablename__ = 'folders'
    __table_args__ = (
        UniqueConstraint('public_id', name='uk_folder_public_id'),
        # 确保同级目录下唯一性验证在模型层生效
        UniqueConstraint('space_id', 'parent_id', 'name', name='uk_folder_sibling_name'),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BIGINT, nullable=True)
    path_cache: Mapped[Optional[str]] = mapped_column(String(2048))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text(
        'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(TIMESTAMP, nullable=True)


class Uploads(Base):
    __tablename__ = 'uploads'
    __table_args__ = (UniqueConstraint('public_id', name='uk_upload_public_id'),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    space_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    folder_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BIGINT, nullable=False)
    created_by: Mapped[int] = mapped_column(BIGINT, nullable=False)
    status: Mapped[str] = mapped_column(Enum('init', 'uploading', 'completed', 'failed'), server_default=text("'init'"))
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))


class Users(Base):
    __tablename__ = 'users'
    __table_args__ = (UniqueConstraint('user_key', name='uk_user_key'),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    display_name: Mapped[Optional[str]] = mapped_column(String(128))

    spaces: Mapped[List['Spaces']] = relationship('Spaces', back_populates='owner_user')
    user_auth: Mapped[List['UserAuth']] = relationship('UserAuth', back_populates='user')


class Spaces(Base):
    __tablename__ = 'spaces'
    __table_args__ = (
        ForeignKeyConstraint(['owner_user_id'], ['users.id'], name='fk_spaces_owner'),
        UniqueConstraint('public_id', name='uk_space_public_id'),
        Index('idx_space_owner', 'owner_user_id')
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, server_default=text(
        'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))

    owner_user: Mapped['Users'] = relationship('Users', back_populates='spaces')


class UserAuth(Base):
    __tablename__ = 'user_auth'
    __table_args__ = (
        ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_auth_user'),
        UniqueConstraint('identity_type', 'identifier', name='uk_identity')
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    identity_type: Mapped[str] = mapped_column(Enum('password', 'phone', 'wechat', 'github'), nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    credential: Mapped[str] = mapped_column(String(255), nullable=False)
    verified: Mapped[int] = mapped_column(TINYINT(1), server_default=text("'0'"))

    user: Mapped['Users'] = relationship('Users', back_populates='user_auth')