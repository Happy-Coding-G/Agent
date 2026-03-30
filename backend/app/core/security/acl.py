"""
细粒度访问控制 (ACL) 系统

提供资源级的权限控制能力，支持：
- RBAC (基于角色的访问控制)
- ABAC (基于属性的访问控制)
- 细粒度权限检查
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List, Dict

from fastapi import HTTPException, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResourceACL, SpaceMembers, Users
from app.db.session import get_db

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """权限枚举"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SHARE = "share"
    EXECUTE = "execute"  # Agent 执行权限
    ADMIN = "admin"  # 管理权限


class ResourceType(str, Enum):
    """资源类型枚举"""
    SPACE = "space"
    FILE = "file"
    ASSET = "asset"
    KNOWLEDGE = "knowledge"
    MARKDOWN = "markdown"
    NEGOTIATION = "negotiation"


class SpaceRole(str, Enum):
    """Space 角色枚举"""
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


# 角色默认权限映射
ROLE_PERMISSIONS = {
    SpaceRole.OWNER: {
        ResourceType.SPACE: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE, Permission.ADMIN],
        ResourceType.FILE: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.ASSET: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE, Permission.EXECUTE],
        ResourceType.KNOWLEDGE: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.MARKDOWN: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.NEGOTIATION: [Permission.READ, Permission.WRITE, Permission.EXECUTE],
    },
    SpaceRole.ADMIN: {
        ResourceType.SPACE: [Permission.READ, Permission.WRITE, Permission.SHARE],
        ResourceType.FILE: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.ASSET: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.KNOWLEDGE: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.MARKDOWN: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
        ResourceType.NEGOTIATION: [Permission.READ, Permission.WRITE],
    },
    SpaceRole.EDITOR: {
        ResourceType.SPACE: [Permission.READ],
        ResourceType.FILE: [Permission.READ, Permission.WRITE],
        ResourceType.ASSET: [Permission.READ, Permission.WRITE],
        ResourceType.KNOWLEDGE: [Permission.READ, Permission.WRITE],
        ResourceType.MARKDOWN: [Permission.READ, Permission.WRITE],
        ResourceType.NEGOTIATION: [Permission.READ],
    },
    SpaceRole.VIEWER: {
        ResourceType.SPACE: [Permission.READ],
        ResourceType.FILE: [Permission.READ],
        ResourceType.ASSET: [Permission.READ],
        ResourceType.KNOWLEDGE: [Permission.READ],
        ResourceType.MARKDOWN: [Permission.READ],
        ResourceType.NEGOTIATION: [],
    },
}


@dataclass
class PermissionCheckResult:
    """权限检查结果"""
    allowed: bool
    reason: Optional[str] = None
    required_permission: Optional[Permission] = None
    user_role: Optional[SpaceRole] = None


@dataclass
class AccessContext:
    """访问上下文（用于ABAC）"""
    user_id: int
    user_ip: Optional[str] = None
    user_agent: Optional[str] = None
    time_of_day: Optional[int] = None  # 0-23
    day_of_week: Optional[int] = None  # 0-6
    is_mobile: bool = False


class ACLService:
    """
    ACL 权限服务

    提供统一的权限检查接口。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_permission(
        self,
        user_id: int,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
        context: Optional[AccessContext] = None,
    ) -> PermissionCheckResult:
        """
        检查用户是否拥有指定资源的权限

        Args:
            user_id: 用户ID
            resource_type: 资源类型
            resource_id: 资源ID
            permission: 所需权限
            context: 可选的访问上下文（用于ABAC）

        Returns:
            权限检查结果
        """
        # 1. 检查显式ACL（最高优先级）
        explicit = await self._check_explicit_acl(
            user_id, resource_type, resource_id, permission
        )
        if explicit.allowed:
            return explicit

        # 2. 对于Space资源，检查成员角色
        if resource_type == ResourceType.SPACE:
            role_result = await self._check_space_role_permission(
                user_id, resource_id, permission
            )
            if role_result.allowed:
                return role_result

        # 3. 对于Space内的资源，检查Space成员权限
        if resource_type != ResourceType.SPACE:
            space_id = await self._get_resource_space_id(resource_type, resource_id)
            if space_id:
                space_result = await self._check_space_role_permission(
                    user_id, space_id, permission, resource_type
                )
                if space_result.allowed:
                    return space_result

        # 4. 检查公开访问
        public_result = await self._check_public_access(
            resource_type, resource_id, permission
        )
        if public_result.allowed:
            return public_result

        return PermissionCheckResult(
            allowed=False,
            reason="Permission denied",
            required_permission=permission,
        )

    async def _check_explicit_acl(
        self,
        user_id: int,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ) -> PermissionCheckResult:
        """检查显式ACL条目"""
        result = await self.db.execute(
            select(ResourceACL).where(
                and_(
                    ResourceACL.resource_type == resource_type.value,
                    ResourceACL.resource_id == resource_id,
                    ResourceACL.user_id == user_id,
                    or_(
                        ResourceACL.expires_at.is_(None),
                        ResourceACL.expires_at > datetime.utcnow(),
                    ),
                )
            )
        )

        acl_entries = result.scalars().all()

        for acl in sorted(acl_entries, key=lambda x: x.priority, reverse=True):
            has_perm = self._has_permission_bit(acl, permission)
            if has_perm:
                return PermissionCheckResult(allowed=True)

        return PermissionCheckResult(allowed=False)

    async def _check_space_role_permission(
        self,
        user_id: int,
        space_id: str,
        permission: Permission,
        resource_type: Optional[ResourceType] = None,
    ) -> PermissionCheckResult:
        """检查Space角色权限"""
        result = await self.db.execute(
            select(SpaceMembers).where(
                and_(
                    SpaceMembers.space_id == space_id,
                    SpaceMembers.user_id == user_id,
                    SpaceMembers.invite_status == "active",
                )
            )
        )

        membership = result.scalar_one_or_none()
        if not membership:
            return PermissionCheckResult(allowed=False)

        role = SpaceRole(membership.role)

        # 检查自定义权限（覆盖默认）
        custom_perms = membership.permissions.get("permissions", [])
        if custom_perms:
            if permission.value in custom_perms or "*" in custom_perms:
                return PermissionCheckResult(allowed=True, user_role=role)

        # 检查默认角色权限
        role_perms = ROLE_PERMISSIONS.get(role, {})
        check_type = resource_type or ResourceType.SPACE
        allowed_perms = role_perms.get(check_type, [])

        if permission in allowed_perms or Permission.ADMIN in allowed_perms:
            return PermissionCheckResult(allowed=True, user_role=role)

        return PermissionCheckResult(allowed=False, user_role=role)

    async def _check_public_access(
        self,
        resource_type: ResourceType,
        resource_id: str,
        permission: Permission,
    ) -> PermissionCheckResult:
        """检查公开访问权限"""
        result = await self.db.execute(
            select(ResourceACL).where(
                and_(
                    ResourceACL.resource_type == resource_type.value,
                    ResourceACL.resource_id == resource_id,
                    ResourceACL.is_public == True,
                    or_(
                        ResourceACL.expires_at.is_(None),
                        ResourceACL.expires_at > datetime.utcnow(),
                    ),
                )
            )
        )

        acl = result.scalar_one_or_none()
        if acl and self._has_permission_bit(acl, permission):
            return PermissionCheckResult(allowed=True)

        return PermissionCheckResult(allowed=False)

    def _has_permission_bit(self, acl: ResourceACL, permission: Permission) -> bool:
        """检查ACL条目是否拥有指定权限位"""
        permission_map = {
            Permission.READ: acl.can_read,
            Permission.WRITE: acl.can_write,
            Permission.DELETE: acl.can_delete,
            Permission.SHARE: acl.can_share,
            Permission.EXECUTE: acl.can_execute,
        }
        return permission_map.get(permission, False)

    async def _get_resource_space_id(
        self,
        resource_type: ResourceType,
        resource_id: str,
    ) -> Optional[str]:
        """获取资源所属的Space ID"""
        # 根据不同资源类型查询
        from app.db.models import Files, DigitalAssets, MarkdownDocs

        if resource_type == ResourceType.FILE:
            result = await self.db.execute(
                select(Files.space_id).where(Files.file_id == resource_id)
            )
            return result.scalar_one_or_none()

        elif resource_type == ResourceType.ASSET:
            result = await self.db.execute(
                select(DigitalAssets.space_id).where(DigitalAssets.asset_id == resource_id)
            )
            return result.scalar_one_or_none()

        elif resource_type == ResourceType.MARKDOWN:
            result = await self.db.execute(
                select(MarkdownDocs.space_id).where(MarkdownDocs.doc_id == resource_id)
            )
            return result.scalar_one_or_none()

        return None

    async def grant_permission(
        self,
        resource_type: ResourceType,
        resource_id: str,
        user_id: int,
        permissions: List[Permission],
        granted_by: int,
        expires_at: Optional[datetime] = None,
        conditions: Optional[Dict[str, Any]] = None,
    ) -> ResourceACL:
        """
        授予权限

        Args:
            resource_type: 资源类型
            resource_id: 资源ID
            user_id: 被授权用户ID
            permissions: 权限列表
            granted_by: 授权者用户ID
            expires_at: 过期时间
            conditions: ABAC条件

        Returns:
            创建的ACL条目
        """
        from app.utils.snowflake import snowflake_id

        # 检查授权者是否有ADMIN权限
        check = await self.check_permission(
            granted_by, resource_type, resource_id, Permission.ADMIN
        )
        if not check.allowed:
            raise HTTPException(status_code=403, detail="No permission to grant access")

        acl = ResourceACL(
            id=snowflake_id(),
            acl_id=f"acl_{snowflake_id()}",
            resource_type=resource_type.value,
            resource_id=resource_id,
            user_id=user_id,
            can_read=Permission.READ in permissions,
            can_write=Permission.WRITE in permissions,
            can_delete=Permission.DELETE in permissions,
            can_share=Permission.SHARE in permissions,
            can_execute=Permission.EXECUTE in permissions,
            conditions=conditions,
            expires_at=expires_at,
            granted_by=granted_by,
        )

        self.db.add(acl)
        await self.db.commit()
        await self.db.refresh(acl)

        logger.info(
            f"Granted {permissions} on {resource_type}:{resource_id} to user {user_id} by {granted_by}"
        )
        return acl

    async def revoke_permission(
        self,
        acl_id: str,
        revoked_by: int,
    ) -> bool:
        """撤销权限"""
        result = await self.db.execute(
            select(ResourceACL).where(ResourceACL.acl_id == acl_id)
        )
        acl = result.scalar_one_or_none()

        if not acl:
            return False

        # 检查撤销者权限
        check = await self.check_permission(
            revoked_by,
            ResourceType(acl.resource_type),
            acl.resource_id,
            Permission.ADMIN,
        )
        if not check.allowed:
            raise HTTPException(status_code=403, detail="No permission to revoke access")

        await self.db.delete(acl)
        await self.db.commit()

        logger.info(f"Revoked ACL {acl_id} by user {revoked_by}")
        return True


class PermissionChecker:
    """
    权限检查装饰器/依赖

    用于 FastAPI 依赖注入。
    """

    def __init__(
        self,
        resource_type: ResourceType,
        permission: Permission,
        resource_id_param: str = "space_id",
    ):
        self.resource_type = resource_type
        self.permission = permission
        self.resource_id_param = resource_id_param

    async def __call__(
        self,
        resource_id: str,
        current_user: Users = Depends(),
        db: AsyncSession = Depends(get_db),
    ) -> PermissionCheckResult:
        """执行权限检查"""
        acl_service = ACLService(db)

        result = await acl_service.check_permission(
            user_id=current_user.id,
            resource_type=self.resource_type,
            resource_id=resource_id,
            permission=self.permission,
        )

        if not result.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Permission denied",
                    "required": self.permission.value,
                    "resource": self.resource_type.value,
                },
            )

        return result


# 便捷依赖函数
def require_permission(
    resource_type: ResourceType,
    permission: Permission,
    resource_id_param: str = "space_id",
):
    """
    创建权限检查依赖

    用法:
        @router.get("/spaces/{space_id}/files")
        async def list_files(
            space_id: str,
            perm: PermissionCheckResult = Depends(
                require_permission(ResourceType.SPACE, Permission.READ)
            ),
        ):
            ...
    """
    return PermissionChecker(resource_type, permission, resource_id_param)


async def add_space_member(
    db: AsyncSession,
    space_id: str,
    user_id: int,
    role: SpaceRole,
    invited_by: int,
    permissions: Optional[Dict[str, Any]] = None,
) -> SpaceMembers:
    """
    添加Space成员

    Args:
        db: 数据库会话
        space_id: Space ID
        user_id: 用户ID
        role: 角色
        invited_by: 邀请者ID
        permissions: 自定义权限（可选）

    Returns:
        创建的成员记录
    """
    from app.utils.snowflake import snowflake_id

    # 检查邀请者权限
    acl = ACLService(db)
    check = await acl.check_permission(
        invited_by, ResourceType.SPACE, space_id, Permission.SHARE
    )
    if not check.allowed:
        raise HTTPException(status_code=403, detail="No permission to add members")

    # 检查是否已是成员
    result = await db.execute(
        select(SpaceMembers).where(
            and_(
                SpaceMembers.space_id == space_id,
                SpaceMembers.user_id == user_id,
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # 更新角色
        existing.role = role.value
        if permissions:
            existing.permissions = permissions
        await db.commit()
        await db.refresh(existing)
        return existing

    # 创建新成员
    member = SpaceMembers(
        id=snowflake_id(),
        space_id=space_id,
        user_id=user_id,
        role=role.value,
        invited_by=invited_by,
        permissions=permissions or {},
    )

    db.add(member)
    await db.commit()
    await db.refresh(member)

    logger.info(f"Added user {user_id} to space {space_id} with role {role.value}")
    return member


async def remove_space_member(
    db: AsyncSession,
    space_id: str,
    user_id: int,
    removed_by: int,
) -> bool:
    """移除Space成员"""
    # 检查权限
    acl = ACLService(db)
    check = await acl.check_permission(
        removed_by, ResourceType.SPACE, space_id, Permission.ADMIN
    )
    if not check.allowed and removed_by != user_id:
        raise HTTPException(status_code=403, detail="No permission to remove members")

    result = await db.execute(
        select(SpaceMembers).where(
            and_(
                SpaceMembers.space_id == space_id,
                SpaceMembers.user_id == user_id,
            )
        )
    )
    member = result.scalar_one_or_none()

    if member:
        member.invite_status = "removed"
        await db.commit()
        logger.info(f"Removed user {user_id} from space {space_id} by {removed_by}")
        return True

    return False
