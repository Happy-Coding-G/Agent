"""
审计日志系统

记录所有敏感操作，用于安全审计、合规和故障排查。
特性：
- 不可篡改的审计日志
- 实时风险检测
- 自动归档
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Dict, List

from fastapi import Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLogs
from app.utils.snowflake import snowflake_id

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """审计动作类型"""
    # 认证相关
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_REGISTER = "user.register"
    USER_PASSWORD_CHANGE = "user.password_change"
    USER_MFA_ENABLED = "user.mfa_enabled"

    # Space 相关
    SPACE_CREATE = "space.create"
    SPACE_DELETE = "space.delete"
    SPACE_UPDATE = "space.update"
    SPACE_MEMBER_ADD = "space.member_add"
    SPACE_MEMBER_REMOVE = "space.member_remove"
    SPACE_MEMBER_ROLE_CHANGE = "space.member_role_change"

    # 文件相关
    FILE_UPLOAD = "file.upload"
    FILE_DOWNLOAD = "file.download"
    FILE_DELETE = "file.delete"
    FILE_SHARE = "file.share"

    # 资产相关
    ASSET_CREATE = "asset.create"
    ASSET_UPDATE = "asset.update"
    ASSET_PURCHASE = "asset.purchase"
    ASSET_SALE = "asset.sale"
    NEGOTIATION_START = "negotiation.start"
    NEGOTIATION_COMPLETE = "negotiation.complete"

    # 权限相关
    PERMISSION_GRANT = "permission.grant"
    PERMISSION_REVOKE = "permission.revoke"
    ACL_MODIFY = "acl.modify"

    # 管理操作
    ADMIN_USER_DELETE = "admin.user_delete"
    ADMIN_USER_SUSPEND = "admin.user_suspend"
    ADMIN_CONFIG_CHANGE = "admin.config_change"


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# 高风险动作列表
HIGH_RISK_ACTIONS = {
    AuditAction.USER_PASSWORD_CHANGE,
    AuditAction.USER_MFA_ENABLED,
    AuditAction.SPACE_DELETE,
    AuditAction.FILE_DOWNLOAD,
    AuditAction.ASSET_PURCHASE,
    AuditAction.PERMISSION_GRANT,
    AuditAction.ADMIN_USER_DELETE,
    AuditAction.ADMIN_USER_SUSPEND,
}

# 需要立即告警的动作
CRITICAL_ACTIONS = {
    AuditAction.ADMIN_USER_DELETE,
    AuditAction.ADMIN_CONFIG_CHANGE,
    AuditAction.PERMISSION_GRANT,
}


class AuditLogger:
    """
    审计日志记录器

    单例模式，提供统一的审计日志接口。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.alert_handlers = []

    def register_alert_handler(self, handler: callable):
        """注册告警处理器"""
        self.alert_handlers.append(handler)

    async def log(
        self,
        db: AsyncSession,
        action: AuditAction,
        user_id: Optional[int],
        resource_type: str,
        resource_id: str,
        result: str = "success",
        request: Optional[Request] = None,
        previous_state: Optional[Dict] = None,
        new_state: Optional[Dict] = None,
        request_payload: Optional[Dict] = None,
        error_message: Optional[str] = None,
    ) -> AuditLogs:
        """
        记录审计日志

        Args:
            db: 数据库会话
            action: 动作类型
            user_id: 用户ID（可为None表示匿名）
            resource_type: 资源类型
            resource_id: 资源ID
            result: 结果 (success/failure/denied/error)
            request: FastAPI请求对象（提取IP、UA等）
            previous_state: 变更前状态
            new_state: 变更后状态
            request_payload: 请求参数（会被脱敏）
            error_message: 错误信息

        Returns:
            创建的审计日志记录
        """
        # 提取请求信息
        client_ip = None
        user_agent = None
        session_id = None

        if request:
            client_ip = self._get_client_ip(request)
            user_agent = request.headers.get("user-agent")
            # 从cookie或header中提取session_id
            session_id = request.headers.get("x-session-id") or request.cookies.get("session_id")

        # 计算风险评分
        risk_score, risk_reasons = self._calculate_risk(
            action, user_id, client_ip, result
        )

        # 脱敏处理
        sanitized_payload = self._sanitize_payload(request_payload)

        # 生成日志ID和完整性哈希
        log_id = f"log_{snowflake_id()}"
        integrity_hash = self._calculate_integrity_hash(
            log_id, action.value, user_id, resource_id, result
        )

        # 获取用户邮箱（快照）
        user_email = None
        if user_id:
            from app.db.models import Users
            user_result = await db.execute(
                select(Users.email).where(Users.id == user_id)
            )
            user_email = user_result.scalar_one_or_none()

        log_entry = AuditLogs(
            id=snowflake_id(),
            log_id=log_id,
            user_id=user_id,
            user_email=user_email,
            client_ip=client_ip,
            user_agent=user_agent,
            session_id=session_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            previous_state=previous_state,
            new_state=new_state,
            request_payload=sanitized_payload,
            result=result,
            error_message=error_message,
            risk_score=risk_score,
            risk_reasons=risk_reasons,
            alert_sent=False,
        )

        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)

        # 实时告警
        if risk_score >= 0.8 or action in CRITICAL_ACTIONS:
            await self._send_alert(log_entry)

        logger.debug(f"Audit log created: {log_id} - {action.value}")
        return log_entry

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实IP"""
        # 优先从X-Forwarded-For获取（通过代理）
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        # 其次从X-Real-IP获取
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # 直接连接
        if request.client:
            return request.client.host

        return "unknown"

    def _calculate_risk(
        self,
        action: AuditAction,
        user_id: Optional[int],
        client_ip: Optional[str],
        result: str,
    ) -> tuple[float, List[str]]:
        """
        计算风险评分

        Returns:
            (风险评分 0-1, 风险原因列表)
        """
        risk_score = 0.0
        risk_reasons = []

        # 基于动作类型的基础风险
        if action in CRITICAL_ACTIONS:
            risk_score += 0.5
            risk_reasons.append("critical_action")
        elif action in HIGH_RISK_ACTIONS:
            risk_score += 0.3
            risk_reasons.append("high_risk_action")

        # 失败操作增加风险
        if result != "success":
            risk_score += 0.2
            risk_reasons.append("operation_failed")

        # 匿名用户执行敏感操作
        if user_id is None and action not in {AuditAction.USER_LOGIN, AuditAction.USER_REGISTER}:
            risk_score += 0.3
            risk_reasons.append("anonymous_user")

        # 检查是否是非常用IP（简化版，实际应查询用户历史IP）
        # TODO: 查询用户常用IP列表进行对比

        # 检查是否是非工作时间
        current_hour = datetime.utcnow().hour
        if current_hour < 6 or current_hour > 22:
            risk_score += 0.1
            risk_reasons.append("off_hours_access")

        return min(risk_score, 1.0), risk_reasons

    def _sanitize_payload(self, payload: Optional[Dict]) -> Optional[Dict]:
        """脱敏处理请求参数"""
        if not payload:
            return None

        sensitive_keys = {
            "password", "token", "secret", "api_key", "credit_card",
            "ssn", "phone", "email", "address", "id_number",
        }

        sanitized = {}
        for key, value in payload.items():
            key_lower = key.lower()
            if any(sk in key_lower for sk in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_payload(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_payload(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

    def _calculate_integrity_hash(
        self,
        log_id: str,
        action: str,
        user_id: Optional[int],
        resource_id: str,
        result: str,
    ) -> str:
        """计算日志完整性哈希（用于防篡改验证）"""
        data = f"{log_id}:{action}:{user_id}:{resource_id}:{result}:{datetime.utcnow().isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()

    async def _send_alert(self, log_entry: AuditLogs):
        """发送安全告警"""
        alert_data = {
            "log_id": log_entry.log_id,
            "action": log_entry.action,
            "user_id": log_entry.user_id,
            "risk_score": log_entry.risk_score,
            "risk_reasons": log_entry.risk_reasons,
            "timestamp": log_entry.created_at.isoformat(),
            "client_ip": log_entry.client_ip,
        }

        for handler in self.alert_handlers:
            try:
                await handler(alert_data)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

        # 标记已发送告警
        log_entry.alert_sent = True

    async def query_logs(
        self,
        db: AsyncSession,
        user_id: Optional[int] = None,
        action: Optional[AuditAction] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        result: Optional[str] = None,
        min_risk_score: Optional[float] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLogs]:
        """
        查询审计日志

        Args:
            db: 数据库会话
            user_id: 用户ID过滤
            action: 动作类型过滤
            resource_type: 资源类型过滤
            resource_id: 资源ID过滤
            result: 结果过滤
            min_risk_score: 最小风险评分
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制
            offset: 分页偏移

        Returns:
            审计日志列表
        """
        query = select(AuditLogs)

        if user_id:
            query = query.where(AuditLogs.user_id == user_id)
        if action:
            query = query.where(AuditLogs.action == action.value)
        if resource_type:
            query = query.where(AuditLogs.resource_type == resource_type)
        if resource_id:
            query = query.where(AuditLogs.resource_id == resource_id)
        if result:
            query = query.where(AuditLogs.result == result)
        if min_risk_score is not None:
            query = query.where(AuditLogs.risk_score >= min_risk_score)
        if start_time:
            query = query.where(AuditLogs.created_at >= start_time)
        if end_time:
            query = query.where(AuditLogs.created_at <= end_time)

        query = query.order_by(desc(AuditLogs.created_at)).limit(limit).offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_user_activity_summary(
        self,
        db: AsyncSession,
        user_id: int,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        获取用户活动摘要

        Args:
            db: 数据库会话
            user_id: 用户ID
            days: 统计天数

        Returns:
            活动摘要
        """
        from_time = datetime.utcnow() - __import__('datetime').timedelta(days=days)

        # 总操作数
        total_count = await db.scalar(
            select(func.count(AuditLogs.id)).where(
                and_(
                    AuditLogs.user_id == user_id,
                    AuditLogs.created_at >= from_time,
                )
            )
        )

        # 按动作统计
        action_counts = await db.execute(
            select(
                AuditLogs.action,
                func.count(AuditLogs.id),
            ).where(
                and_(
                    AuditLogs.user_id == user_id,
                    AuditLogs.created_at >= from_time,
                )
            ).group_by(AuditLogs.action)
        )

        # 失败次数
        failure_count = await db.scalar(
            select(func.count(AuditLogs.id)).where(
                and_(
                    AuditLogs.user_id == user_id,
                    AuditLogs.created_at >= from_time,
                    AuditLogs.result != "success",
                )
            )
        )

        # 高风险操作次数
        high_risk_count = await db.scalar(
            select(func.count(AuditLogs.id)).where(
                and_(
                    AuditLogs.user_id == user_id,
                    AuditLogs.created_at >= from_time,
                    AuditLogs.risk_score >= 0.5,
                )
            )
        )

        return {
            "user_id": user_id,
            "period_days": days,
            "total_operations": total_count or 0,
            "failed_operations": failure_count or 0,
            "high_risk_operations": high_risk_count or 0,
            "action_breakdown": {row[0]: row[1] for row in action_counts.all()},
            "risk_assessment": "high" if high_risk_count > 5 else "medium" if high_risk_count > 0 else "low",
        }

    async def get_security_anomalies(
        self,
        db: AsyncSession,
        days: int = 1,
        min_risk_score: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        获取安全异常列表

        Args:
            db: 数据库会话
            days: 统计天数
            min_risk_score: 最小风险评分

        Returns:
            异常列表
        """
        from_time = datetime.utcnow() - __import__('datetime').timedelta(days=days)

        logs = await self.query_logs(
            db,
            min_risk_score=min_risk_score,
            start_time=from_time,
            limit=100,
        )

        anomalies = []
        for log in logs:
            anomalies.append({
                "log_id": log.log_id,
                "action": log.action,
                "user_id": log.user_id,
                "user_email": log.user_email,
                "client_ip": log.client_ip,
                "risk_score": log.risk_score,
                "risk_reasons": log.risk_reasons,
                "timestamp": log.created_at.isoformat(),
                "result": log.result,
            })

        return anomalies


# 全局审计日志实例
audit_logger = AuditLogger()


# 便捷的装饰器函数
def audit_log(
    action: AuditAction,
    resource_type: str,
    resource_id_param: str = "space_id",
    extract_new_state: Optional[callable] = None,
    extract_previous_state: Optional[callable] = None,
):
    """
    审计日志装饰器

    用法:
        @router.post("/spaces/{space_id}")
        @audit_log(
            action=AuditAction.SPACE_CREATE,
            resource_type="space",
            resource_id_param="space_id",
        )
        async def create_space(...):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 执行原函数
            result = await func(*args, **kwargs)

            # 提取参数
            db = kwargs.get("db")
            request = kwargs.get("request")
            current_user = kwargs.get("current_user")
            resource_id = kwargs.get(resource_id_param)

            if db and current_user:
                # 提取状态
                new_state = None
                prev_state = None
                if extract_new_state:
                    new_state = extract_new_state(result)
                if extract_previous_state:
                    prev_state = extract_previous_state(kwargs)

                # 记录审计日志
                await audit_logger.log(
                    db=db,
                    action=action,
                    user_id=current_user.id,
                    resource_type=resource_type,
                    resource_id=resource_id or "unknown",
                    result="success",
                    request=request,
                    previous_state=prev_state,
                    new_state=new_state,
                )

            return result
        return wrapper
    return decorator
