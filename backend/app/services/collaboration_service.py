"""
Space实时协作系统

提供多用户在Space内的实时协作能力：
- 在线状态管理（Presence）
- 实时操作同步（Operational Transformation）
- 冲突解决（Conflict Resolution）
- 协作会话管理（Session Management）
- 细粒度权限控制（Permission Control）

使用场景：
1. 多人同时编辑Markdown文档
2. 实时查看其他用户的光标位置
3. 协作编辑知识图谱
4. 并发文件操作协调

技术方案：
- WebSocket用于实时通信
- 向量时钟（Vector Clock）用于事件排序
- 操作转换（OT）用于冲突解决
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.acl import Permission, ResourceType
from app.core.security.audit import AuditAction, audit_logger
from app.db.models import (
    CollaborationOperations,
    OperationType,
    SpaceMembers,
    SpaceRole,
    Users,
)
from app.utils.snowflake import snowflake_id

from .base import SpaceAwareService

logger = logging.getLogger(__name__)


# ============================================================================
# 协作类型定义
# ============================================================================

class PresenceStatus(str, Enum):
    """用户在线状态"""
    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    OFFLINE = "offline"


class CollaborationResourceType(str, Enum):
    """协作资源类型"""
    MARKDOWN = "markdown"
    GRAPH = "graph"
    FILE = "file"
    ASSET = "asset"
    SPACE = "space"


@dataclass
class UserPresence:
    """用户在线状态"""
    user_id: int
    user_email: str
    user_name: str
    status: PresenceStatus
    current_resource: Optional[str] = None  # 当前正在查看/编辑的资源
    cursor_position: Optional[Dict[str, Any]] = None  # 光标位置
    last_seen: datetime = field(default_factory=datetime.utcnow)
    client_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Operation:
    """协作操作"""
    id: str
    resource_type: CollaborationResourceType
    resource_id: str
    operation_type: OperationType
    user_id: int
    vector_clock: Dict[str, int]  # 向量时钟
    payload: Dict[str, Any]
    parent_operations: List[str]  # 父操作ID（用于构建DAG）
    timestamp: datetime = field(default_factory=datetime.utcnow)
    applied: bool = False


@dataclass
class CollaborationSession:
    """协作会话"""
    session_id: str
    space_id: str
    resource_type: CollaborationResourceType
    resource_id: str
    participants: Dict[int, UserPresence] = field(default_factory=dict)
    operations: List[Operation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ConflictResolution:
    """冲突解决结果"""
    resolved: bool
    winning_operation: Optional[Operation] = None
    merged_payload: Optional[Dict[str, Any]] = None
    conflict_details: Optional[Dict[str, Any]] = None


# ============================================================================
# Redis 发布/订阅管理
# ============================================================================

class CollaborationPubSub:
    """协作消息发布订阅管理"""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._subscribers: Dict[str, Set[WebSocket]] = {}
        self._running = False

    async def connect(self):
        """连接Redis"""
        self._redis = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()
        self._running = True

    async def disconnect(self):
        """断开连接"""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    def _get_channel(self, space_id: str, resource_type: str, resource_id: str) -> str:
        """生成频道名称"""
        return f"collab:{space_id}:{resource_type}:{resource_id}"

    async def subscribe(
        self,
        websocket: WebSocket,
        space_id: str,
        resource_type: str,
        resource_id: str,
    ):
        """订阅频道"""
        channel = self._get_channel(space_id, resource_type, resource_id)

        if channel not in self._subscribers:
            self._subscribers[channel] = set()
            if self._pubsub:
                await self._pubsub.subscribe(channel)

        self._subscribers[channel].add(websocket)

    async def unsubscribe(
        self,
        websocket: WebSocket,
        space_id: str,
        resource_type: str,
        resource_id: str,
    ):
        """取消订阅"""
        channel = self._get_channel(space_id, resource_type, resource_id)

        if channel in self._subscribers:
            self._subscribers[channel].discard(websocket)

            if not self._subscribers[channel]:
                del self._subscribers[channel]
                if self._pubsub:
                    await self._pubsub.unsubscribe(channel)

    async def publish(
        self,
        space_id: str,
        resource_type: str,
        resource_id: str,
        message: Dict[str, Any],
    ):
        """发布消息"""
        if self._redis:
            channel = self._get_channel(space_id, resource_type, resource_id)
            await self._redis.publish(channel, json.dumps(message))

    async def broadcast_to_session(
        self,
        session: CollaborationSession,
        message: Dict[str, Any],
        exclude_user_id: Optional[int] = None,
    ):
        """广播到会话中的所有参与者"""
        channel = self._get_channel(
            session.space_id,
            session.resource_type.value,
            session.resource_id,
        )

        if channel in self._subscribers:
            dead_sockets = set()

            for websocket in self._subscribers[channel]:
                try:
                    # 检查是否需要排除
                    if exclude_user_id:
                        # 这里需要通过websocket关联user_id
                        # 简化处理：在实际实现中需要维护映射关系
                        pass

                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to websocket: {e}")
                    dead_sockets.add(websocket)

            # 清理失效的连接
            for dead in dead_sockets:
                self._subscribers[channel].discard(dead)


# ============================================================================
# 向量时钟管理
# ============================================================================

class VectorClockManager:
    """向量时钟管理器"""

    @staticmethod
    def create_clock(user_id: int, sequence: int = 1) -> Dict[str, int]:
        """创建新的向量时钟"""
        return {str(user_id): sequence}

    @staticmethod
    def increment_clock(clock: Dict[str, int], user_id: int) -> Dict[str, int]:
        """增加向量时钟"""
        new_clock = clock.copy()
        user_key = str(user_id)
        new_clock[user_key] = new_clock.get(user_key, 0) + 1
        return new_clock

    @staticmethod
    def merge_clocks(clock1: Dict[str, int], clock2: Dict[str, int]) -> Dict[str, int]:
        """合并两个向量时钟"""
        merged = clock1.copy()
        for user_id, sequence in clock2.items():
            merged[user_id] = max(merged.get(user_id, 0), sequence)
        return merged

    @staticmethod
    def compare_clocks(
        clock1: Dict[str, int],
        clock2: Dict[str, int],
    ) -> int:
        """
        比较两个向量时钟

        Returns:
            -1: clock1 < clock2 (clock1发生在clock2之前)
             0: clock1 == clock2 (并发)
             1: clock1 > clock2 (clock1发生在clock2之后)
        """
        # 检查clock1是否小于clock2
        less_than = all(
            clock1.get(k, 0) <= clock2.get(k, 0)
            for k in set(clock1) | set(clock2)
        )

        # 检查clock1是否大于clock2
        greater_than = all(
            clock1.get(k, 0) >= clock2.get(k, 0)
            for k in set(clock1) | set(clock2)
        )

        if less_than and not greater_than:
            return -1
        elif greater_than and not less_than:
            return 1
        elif clock1 == clock2:
            return 0
        else:
            # 并发冲突
            return 0


# ============================================================================
# 冲突解决策略
# ============================================================================

class ConflictResolver:
    """冲突解决器"""

    @staticmethod
    def resolve(
        op1: Operation,
        op2: Operation,
        strategy: str = "last_write_wins",
    ) -> ConflictResolution:
        """
        解决操作冲突

        Args:
            op1: 操作1
            op2: 操作2
            strategy: 解决策略
                - last_write_wins: 最后写入优先
                - first_write_wins: 先写入优先
                - merge: 尝试合并
                - manual: 标记为需要手动解决

        Returns:
            冲突解决结果
        """
        if strategy == "last_write_wins":
            winner = op1 if op1.timestamp > op2.timestamp else op2
            return ConflictResolution(
                resolved=True,
                winning_operation=winner,
            )

        elif strategy == "first_write_wins":
            winner = op1 if op1.timestamp < op2.timestamp else op2
            return ConflictResolution(
                resolved=True,
                winning_operation=winner,
            )

        elif strategy == "merge":
            merged = ConflictResolver._try_merge(op1, op2)
            if merged:
                return ConflictResolution(
                    resolved=True,
                    merged_payload=merged,
                )
            else:
                return ConflictResolution(
                    resolved=False,
                    conflict_details={
                        "op1": op1,
                        "op2": op2,
                        "reason": "Cannot auto-merge",
                    },
                )

        elif strategy == "manual":
            return ConflictResolution(
                resolved=False,
                conflict_details={
                    "op1": op1,
                    "op2": op2,
                    "reason": "Manual resolution required",
                },
            )

        return ConflictResolution(resolved=False)

    @staticmethod
    def _try_merge(op1: Operation, op2: Operation) -> Optional[Dict[str, Any]]:
        """尝试合并两个操作的payload"""
        # 简单的键级别合并
        if op1.operation_type == op2.operation_type == OperationType.UPDATE:
            merged = op1.payload.copy()
            for key, value in op2.payload.items():
                if key not in merged:
                    merged[key] = value
                elif merged[key] == value:
                    continue
                else:
                    # 冲突的键，无法自动合并
                    return None
            return merged

        return None


# ============================================================================
# 核心服务
# ============================================================================

class CollaborationService(SpaceAwareService):
    """
    Space协作服务

    管理多用户实时协作的所有方面
    """

    _sessions: Dict[str, CollaborationSession] = {}
    _pubsub: Optional[CollaborationPubSub] = None
    _vector_clock = VectorClockManager()
    _conflict_resolver = ConflictResolver()

    def __init__(self, db: AsyncSession, redis_url: str = "redis://localhost:6379/0"):
        super().__init__(db)
        self.redis_url = redis_url
        if CollaborationService._pubsub is None:
            CollaborationService._pubsub = CollaborationPubSub(redis_url)

    # ========================================================================
    # 会话管理
    # ========================================================================

    async def join_session(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        user_id: int,
        websocket: WebSocket,
        client_info: Optional[Dict[str, Any]] = None,
    ) -> CollaborationSession:
        """
        用户加入协作会话

        Returns:
            协作会话
        """
        session_key = f"{space_id}:{resource_type.value}:{resource_id}"

        # 获取或创建会话
        if session_key not in self._sessions:
            self._sessions[session_key] = CollaborationSession(
                session_id=str(uuid4()),
                space_id=space_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        session = self._sessions[session_key]

        # 获取用户信息
        user_result = await self.db.execute(
            select(Users).where(Users.id == user_id)
        )
        user = user_result.scalar_one()

        # 添加参与者
        presence = UserPresence(
            user_id=user_id,
            user_email=user.email,
            user_name=user.username or user.email,
            status=PresenceStatus.ONLINE,
            current_resource=f"{resource_type.value}:{resource_id}",
            client_info=client_info or {},
        )
        session.participants[user_id] = presence
        session.last_activity = datetime.utcnow()

        # 订阅消息频道
        await self._pubsub.subscribe(websocket, space_id, resource_type.value, resource_id)

        # 广播用户加入
        await self._pubsub.broadcast_to_session(
            session,
            {
                "type": "user_joined",
                "data": {
                    "user_id": user_id,
                    "user_name": presence.user_name,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            },
        )

        # 记录审计日志
        await audit_logger.log(
            db=self.db,
            action=AuditAction.SPACE_MEMBER_ADD,
            user_id=user_id,
            resource_type="collaboration_session",
            resource_id=session.session_id,
            new_state={
                "space_id": space_id,
                "resource_type": resource_type.value,
                "resource_id": resource_id,
            },
        )

        logger.info(f"User {user_id} joined collaboration session {session_key}")
        return session

    async def leave_session(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        user_id: int,
        websocket: WebSocket,
    ):
        """用户离开协作会话"""
        session_key = f"{space_id}:{resource_type.value}:{resource_id}"

        if session_key in self._sessions:
            session = self._sessions[session_key]

            # 移除参与者
            if user_id in session.participants:
                del session.participants[user_id]

            # 取消订阅
            await self._pubsub.unsubscribe(websocket, space_id, resource_type.value, resource_id)

            # 广播用户离开
            await self._pubsub.broadcast_to_session(
                session,
                {
                    "type": "user_left",
                    "data": {
                        "user_id": user_id,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                },
            )

            # 如果没有参与者，清理会话
            if not session.participants:
                del self._sessions[session_key]

            logger.info(f"User {user_id} left collaboration session {session_key}")

    async def get_session(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
    ) -> Optional[CollaborationSession]:
        """获取协作会话"""
        session_key = f"{space_id}:{resource_type.value}:{resource_id}"
        return self._sessions.get(session_key)

    async def get_active_sessions(self, space_id: str) -> List[Dict[str, Any]]:
        """获取Space中的所有活跃会话"""
        sessions = []

        for key, session in self._sessions.items():
            if session.space_id == space_id:
                sessions.append({
                    "session_id": session.session_id,
                    "resource_type": session.resource_type.value,
                    "resource_id": session.resource_id,
                    "participant_count": len(session.participants),
                    "participants": [
                        {
                            "user_id": p.user_id,
                            "user_name": p.user_name,
                            "status": p.status.value,
                        }
                        for p in session.participants.values()
                    ],
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                })

        return sessions

    # ========================================================================
    # 在线状态管理
    # ========================================================================

    async def update_presence(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        user_id: int,
        status: PresenceStatus,
        cursor_position: Optional[Dict[str, Any]] = None,
    ):
        """更新用户在线状态"""
        session = await self.get_session(space_id, resource_type, resource_id)

        if session and user_id in session.participants:
            presence = session.participants[user_id]
            presence.status = status
            presence.last_seen = datetime.utcnow()

            if cursor_position:
                presence.cursor_position = cursor_position

            # 广播状态更新
            await self._pubsub.broadcast_to_session(
                session,
                {
                    "type": "presence_updated",
                    "data": {
                        "user_id": user_id,
                        "status": status.value,
                        "cursor_position": cursor_position,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                },
                exclude_user_id=user_id,
            )

    async def get_presence_list(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
    ) -> List[Dict[str, Any]]:
        """获取在线用户列表"""
        session = await self.get_session(space_id, resource_type, resource_id)

        if not session:
            return []

        return [
            {
                "user_id": p.user_id,
                "user_name": p.user_name,
                "status": p.status.value,
                "cursor_position": p.cursor_position,
                "last_seen": p.last_seen.isoformat(),
            }
            for p in session.participants.values()
        ]

    # ========================================================================
    # 操作处理
    # ========================================================================

    async def apply_operation(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        user_id: int,
        operation_type: OperationType,
        payload: Dict[str, Any],
        parent_ops: Optional[List[str]] = None,
    ) -> Operation:
        """
        应用协作操作

        Returns:
            创建的操作记录
        """
        session = await self.get_session(space_id, resource_type, resource_id)

        if not session:
            raise ValueError("Session not found")

        # 生成向量时钟
        current_clock = self._vector_clock.create_clock(user_id)

        # 合并父操作的时钟
        for op in session.operations:
            if op.id in (parent_ops or []):
                current_clock = self._vector_clock.merge_clocks(
                    current_clock, op.vector_clock
                )

        # 递增时钟
        current_clock = self._vector_clock.increment_clock(current_clock, user_id)

        # 创建操作
        operation = Operation(
            id=f"op_{snowflake_id()}",
            resource_type=resource_type,
            resource_id=resource_id,
            operation_type=operation_type,
            user_id=user_id,
            vector_clock=current_clock,
            payload=payload,
            parent_operations=parent_ops or [],
        )

        # 检查冲突
        conflicts = self._detect_conflicts(session, operation)

        if conflicts:
            # 解决冲突
            for conflict_op in conflicts:
                resolution = self._conflict_resolver.resolve(
                    operation, conflict_op, strategy="last_write_wins"
                )

                if not resolution.resolved:
                    # 记录冲突，需要手动解决
                    logger.warning(f"Unresolved conflict detected: {operation.id} vs {conflict_op.id}")

        # 添加到会话
        session.operations.append(operation)

        # 持久化到数据库
        db_operation = CollaborationOperations(
            id=snowflake_id(),
            operation_id=operation.id,
            resource_type=resource_type.value,
            resource_id=resource_id,
            space_id=space_id,
            operation_type=operation_type,
            user_id=user_id,
            vector_clock=current_clock,
            payload=payload,
            applied=True,
        )
        self.db.add(db_operation)
        await self.db.commit()

        # 广播操作
        await self._pubsub.broadcast_to_session(
            session,
            {
                "type": "operation_applied",
                "data": {
                    "operation_id": operation.id,
                    "operation_type": operation_type.value,
                    "user_id": user_id,
                    "vector_clock": current_clock,
                    "payload": payload,
                    "timestamp": operation.timestamp.isoformat(),
                },
            },
            exclude_user_id=user_id,
        )

        return operation

    def _detect_conflicts(
        self,
        session: CollaborationSession,
        new_op: Operation,
    ) -> List[Operation]:
        """检测与新操作冲突的历史操作"""
        conflicts = []

        for op in session.operations:
            # 检查是否操作相同资源
            if op.resource_id != new_op.resource_id:
                continue

            # 检查向量时钟关系
            relation = self._vector_clock.compare_clocks(
                new_op.vector_clock, op.vector_clock
            )

            # relation == 0 表示并发（可能冲突）
            if relation == 0:
                conflicts.append(op)

        return conflicts

    async def get_operation_history(
        self,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取操作历史"""
        result = await self.db.execute(
            select(CollaborationOperations).where(
                and_(
                    CollaborationOperations.space_id == space_id,
                    CollaborationOperations.resource_type == resource_type.value,
                    CollaborationOperations.resource_id == resource_id,
                )
            ).order_by(CollaborationOperations.created_at.desc()).limit(limit)
        )

        operations = result.scalars().all()

        return [
            {
                "operation_id": op.operation_id,
                "operation_type": op.operation_type.value,
                "user_id": op.user_id,
                "vector_clock": op.vector_clock,
                "payload": op.payload,
                "applied": op.applied,
                "created_at": op.created_at.isoformat(),
            }
            for op in operations
        ]

    # ========================================================================
    # 权限检查
    # ========================================================================

    async def check_collaboration_permission(
        self,
        space_id: str,
        user_id: int,
        required_permission: Permission,
    ) -> bool:
        """检查用户是否有协作权限"""
        # 查询用户在Space中的角色
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
            return False

        # 检查权限
        role_permissions = {
            SpaceRole.OWNER: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE, Permission.ADMIN],
            SpaceRole.ADMIN: [Permission.READ, Permission.WRITE, Permission.DELETE, Permission.SHARE],
            SpaceRole.EDITOR: [Permission.READ, Permission.WRITE],
            SpaceRole.VIEWER: [Permission.READ],
        }

        allowed = role_permissions.get(SpaceRole(membership.role), [])
        return required_permission in allowed or Permission.ADMIN in allowed

    # ========================================================================
    # 清理和维护
    # ========================================================================

    async def cleanup_inactive_sessions(self, max_idle_minutes: int = 30):
        """清理不活跃的会话"""
        cutoff = datetime.utcnow() - timedelta(minutes=max_idle_minutes)
        to_remove = []

        for key, session in self._sessions.items():
            if session.last_activity < cutoff:
                to_remove.append(key)

        for key in to_remove:
            session = self._sessions.pop(key)
            logger.info(f"Cleaned up inactive session: {session.session_id}")

        return len(to_remove)

    async def get_collaboration_stats(self, space_id: str) -> Dict[str, Any]:
        """获取协作统计信息"""
        # 操作统计
        result = await self.db.execute(
            select(
                CollaborationOperations.operation_type,
                func.count(CollaborationOperations.id),
            ).where(
                CollaborationOperations.space_id == space_id
            ).group_by(CollaborationOperations.operation_type)
        )
        op_stats = {row[0].value: row[1] for row in result.all()}

        # 活跃用户统计
        from_time = datetime.utcnow() - timedelta(days=7)
        result = await self.db.execute(
            select(
                func.count(func.distinct(CollaborationOperations.user_id))
            ).where(
                and_(
                    CollaborationOperations.space_id == space_id,
                    CollaborationOperations.created_at >= from_time,
                )
            )
        )
        active_users = result.scalar()

        # 活跃会话数
        active_sessions = sum(
            1 for s in self._sessions.values() if s.space_id == space_id
        )

        return {
            "operation_stats": op_stats,
            "active_users_7d": active_users,
            "active_sessions": active_sessions,
            "total_sessions_today": len([
                s for s in self._sessions.values()
                if s.space_id == space_id and s.created_at.date() == datetime.utcnow().date()
            ]),
        }


# ============================================================================
# WebSocket处理器
# ============================================================================

class CollaborationWebSocketHandler:
    """WebSocket处理器"""

    def __init__(self, service: CollaborationService):
        self.service = service
        self.user_id: Optional[int] = None
        self.space_id: Optional[str] = None
        self.resource_type: Optional[CollaborationResourceType] = None
        self.resource_id: Optional[str] = None
        self.websocket: Optional[WebSocket] = None

    async def handle(
        self,
        websocket: WebSocket,
        space_id: str,
        resource_type: CollaborationResourceType,
        resource_id: str,
        user_id: int,
    ):
        """处理WebSocket连接"""
        self.websocket = websocket
        self.user_id = user_id
        self.space_id = space_id
        self.resource_type = resource_type
        self.resource_id = resource_id

        # 接受连接
        await websocket.accept()

        try:
            # 加入会话
            session = await self.service.join_session(
                space_id, resource_type, resource_id, user_id, websocket
            )

            # 发送初始状态
            await websocket.send_json({
                "type": "session_joined",
                "data": {
                    "session_id": session.session_id,
                    "participants": [
                        {
                            "user_id": p.user_id,
                            "user_name": p.user_name,
                            "status": p.status.value,
                        }
                        for p in session.participants.values()
                    ],
                },
            })

            # 处理消息
            while True:
                message = await websocket.receive_json()
                await self._handle_message(message)

        except WebSocketDisconnect:
            await self._cleanup()
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await self._cleanup()

    async def _handle_message(self, message: Dict[str, Any]):
        """处理客户端消息"""
        msg_type = message.get("type")
        data = message.get("data", {})

        if msg_type == "presence_update":
            await self.service.update_presence(
                self.space_id,
                self.resource_type,
                self.resource_id,
                self.user_id,
                PresenceStatus(data.get("status", "online")),
                data.get("cursor_position"),
            )

        elif msg_type == "operation":
            await self.service.apply_operation(
                self.space_id,
                self.resource_type,
                self.resource_id,
                self.user_id,
                OperationType(data.get("operation_type")),
                data.get("payload", {}),
                data.get("parent_operations"),
            )

        elif msg_type == "get_history":
            history = await self.service.get_operation_history(
                self.space_id,
                self.resource_type,
                self.resource_id,
                limit=data.get("limit", 100),
            )
            await self.websocket.send_json({
                "type": "operation_history",
                "data": {"operations": history},
            })

    async def _cleanup(self):
        """清理连接"""
        if self.websocket and self.space_id:
            await self.service.leave_session(
                self.space_id,
                self.resource_type,
                self.resource_id,
                self.user_id,
                self.websocket,
            )


# ============================================================================
# 便捷函数
# ============================================================================

async def get_collaboration_service(db: AsyncSession) -> CollaborationService:
    """获取协作服务实例"""
    return CollaborationService(db)
