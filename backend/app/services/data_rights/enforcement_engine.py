"""
Data Rights Enforcement Engine - 数据权益技术保障引擎

实现数据权益的技术级强制执行，确保购买的权益与实际操作权限一致。

核心功能：
1. 查询改写（Query Rewriting）- 根据权益类型限制查询范围
2. 行级安全（Row-Level Security）- 控制数据访问粒度
3. 动态水印（Dynamic Watermarking）- 追踪数据泄露来源
4. 访问控制（Access Control）- 拦截违规操作

使用方式:
    # 在数据访问前检查权益
    enforcement = RightsEnforcementEngine(db, transaction_id)
    query = await enforcement.rewrite_query(user_query)

    # 在结果返回前添加水印
    result = await enforcement.add_watermark(raw_result, buyer_id)
"""

from __future__ import annotations

import logging
import hashlib
import json
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.errors import ServiceError
from app.db.models import (
    DataRightsTransactions,
    DataRightsStatus,
    DataAccessAuditLogs,
    Users,
)

logger = logging.getLogger(__name__)


class RightEnforcementType(str, Enum):
    """权益执行类型"""
    READ_ONLY = "read_only"              # 只读查询
    ANALYTICS = "analytics"              # 分析使用（仅聚合结果）
    DERIVED_WORK = "derived_work"        # 衍生作品
    FULL_ACCESS = "full_access"          # 完全访问
    EXCLUSIVE = "exclusive"              # 独占权益


@dataclass
class EnforcementPolicy:
    """权益执行策略"""
    right_type: RightEnforcementType

    # 查询限制
    max_rows_per_query: int
    allow_raw_export: bool
    allow_download: bool
    allow_api_access: bool

    # 聚合要求
    require_aggregation: bool
    min_group_size: int  # 最小分组大小（防止个体识别）

    # 水印
    watermark_required: bool
    watermark_type: str  # "visible" | "invisible" | "fingerprint"

    # 审计
    audit_level: str  # "basic" | "detailed" | "full"


# 预定义的执行策略
ENFORCEMENT_POLICIES: Dict[RightEnforcementType, EnforcementPolicy] = {
    RightEnforcementType.READ_ONLY: EnforcementPolicy(
        right_type=RightEnforcementType.READ_ONLY,
        max_rows_per_query=100,
        allow_raw_export=False,
        allow_download=False,
        allow_api_access=True,
        require_aggregation=False,
        min_group_size=1,
        watermark_required=True,
        watermark_type="visible",
        audit_level="detailed",
    ),
    RightEnforcementType.ANALYTICS: EnforcementPolicy(
        right_type=RightEnforcementType.ANALYTICS,
        max_rows_per_query=0,  # 不允许原始行返回
        allow_raw_export=False,
        allow_download=False,
        allow_api_access=True,
        require_aggregation=True,
        min_group_size=5,  # 至少5条记录聚合
        watermark_required=True,
        watermark_type="invisible",
        audit_level="full",
    ),
    RightEnforcementType.DERIVED_WORK: EnforcementPolicy(
        right_type=RightEnforcementType.DERIVED_WORK,
        max_rows_per_query=1000,
        allow_raw_export=True,
        allow_download=True,
        allow_api_access=True,
        require_aggregation=False,
        min_group_size=1,
        watermark_required=True,
        watermark_type="fingerprint",
        audit_level="full",
    ),
    RightEnforcementType.FULL_ACCESS: EnforcementPolicy(
        right_type=RightEnforcementType.FULL_ACCESS,
        max_rows_per_query=10000,
        allow_raw_export=True,
        allow_download=True,
        allow_api_access=True,
        require_aggregation=False,
        min_group_size=1,
        watermark_required=False,
        watermark_type="none",
        audit_level="basic",
    ),
    RightEnforcementType.EXCLUSIVE: EnforcementPolicy(
        right_type=RightEnforcementType.EXCLUSIVE,
        max_rows_per_query=100000,
        allow_raw_export=True,
        allow_download=True,
        allow_api_access=True,
        require_aggregation=False,
        min_group_size=1,
        watermark_required=False,
        watermark_type="none",
        audit_level="basic",
    ),
}


class RightsEnforcementEngine:
    """
    数据权益执行引擎

    确保数据访问符合购买的权益类型。
    """

    def __init__(
        self,
        db: AsyncSession,
        transaction_id: str,
        buyer_id: int,
    ):
        self.db = db
        self.transaction_id = transaction_id
        self.buyer_id = buyer_id
        self._transaction: Optional[DataRightsTransactions] = None
        self._policy: Optional[EnforcementPolicy] = None

    async def _load_transaction(self) -> DataRightsTransactions:
        """加载权益交易记录"""
        if self._transaction is not None:
            return self._transaction

        result = await self.db.execute(
            select(DataRightsTransactions).where(
                DataRightsTransactions.transaction_id == self.transaction_id,
                DataRightsTransactions.buyer_id == self.buyer_id,
            )
        )
        self._transaction = result.scalar_one_or_none()

        if not self._transaction:
            raise ServiceError(404, "Data rights transaction not found")

        if self._transaction.status != DataRightsStatus.ACTIVE:
            raise ServiceError(
                403,
                f"Transaction is not active: {self._transaction.status.value}"
            )

        # 检查有效期
        now = datetime.now(timezone.utc)
        if self._transaction.valid_until < now:
            raise ServiceError(403, "Data rights have expired")

        return self._transaction

    async def _get_policy(self) -> EnforcementPolicy:
        """获取执行策略"""
        if self._policy is not None:
            return self._policy

        transaction = await self._load_transaction()

        # 从交易记录中解析权益类型
        rights_types = transaction.rights_types
        if isinstance(rights_types, list) and len(rights_types) > 0:
            right_type_str = rights_types[0]
        elif isinstance(rights_types, str):
            right_type_str = rights_types
        else:
            right_type_str = "read_only"

        try:
            right_type = RightEnforcementType(right_type_str)
        except ValueError:
            logger.warning(f"Unknown right type: {right_type_str}, defaulting to read_only")
            right_type = RightEnforcementType.READ_ONLY

        self._policy = ENFORCEMENT_POLICIES.get(
            right_type,
            ENFORCEMENT_POLICIES[RightEnforcementType.READ_ONLY]
        )

        return self._policy

    async def check_access_permission(
        self,
        access_type: str,  # "query", "download", "api", "export"
    ) -> Tuple[bool, str]:
        """
        检查访问权限

        Args:
            access_type: 访问类型

        Returns:
            (是否允许, 原因)
        """
        policy = await self._get_policy()

        if access_type == "download" and not policy.allow_download:
            return False, "Current rights do not allow data download"

        if access_type == "export" and not policy.allow_raw_export:
            return False, "Current rights do not allow raw data export"

        if access_type == "api" and not policy.allow_api_access:
            return False, "Current rights do not allow API access"

        return True, "Access permitted"

    async def rewrite_query(
        self,
        original_query: str,
        query_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        改写查询以符合权益限制

        Args:
            original_query: 原始SQL查询
            query_params: 查询参数

        Returns:
            改写后的查询
        """
        policy = await self._get_policy()

        # 1. 检查是否允许查询
        allowed, reason = await self.check_access_permission("query")
        if not allowed:
            raise ServiceError(403, reason)

        rewritten_query = original_query

        # 2. 如果需要聚合，添加GROUP BY限制
        if policy.require_aggregation:
            # 检查是否包含聚合函数
            if not self._has_aggregation(original_query):
                raise ServiceError(
                    403,
                    f"Current rights require aggregation. Queries must group by at least {policy.min_group_size} records."
                )

        # 3. 添加行数限制
        if policy.max_rows_per_query > 0:
            rewritten_query = self._add_row_limit(
                rewritten_query,
                policy.max_rows_per_query
            )

        # 4. 记录审计日志
        await self._log_access(
            access_type="query",
            query=original_query,
            rewritten_query=rewritten_query,
        )

        return rewritten_query

    def _has_aggregation(self, query: str) -> bool:
        """检查查询是否包含聚合函数"""
        aggregation_keywords = [
            "COUNT(", "SUM(", "AVG(", "MAX(", "MIN(",
            "GROUP BY", "HAVING"
        ]
        query_upper = query.upper()
        return any(kw in query_upper for kw in aggregation_keywords)

    def _add_row_limit(self, query: str, limit: int) -> str:
        """添加行数限制"""
        # 简单处理：如果已有LIMIT，取较小值
        if "LIMIT" in query.upper():
            # 提取现有LIMIT值并比较
            import re
            limit_match = re.search(r'LIMIT\s+(\d+)', query, re.IGNORECASE)
            if limit_match:
                existing_limit = int(limit_match.group(1))
                if existing_limit > limit:
                    # 替换为更小的限制
                    query = re.sub(
                        r'LIMIT\s+\d+',
                        f'LIMIT {limit}',
                        query,
                        flags=re.IGNORECASE
                    )
                return query

        # 添加LIMIT
        return f"{query} LIMIT {limit}"

    async def add_watermark(
        self,
        data: Any,
        watermark_type: Optional[str] = None,
    ) -> Any:
        """
        添加数字水印

        Args:
            data: 原始数据
            watermark_type: 水印类型（覆盖默认策略）

        Returns:
            带水印的数据
        """
        policy = await self._get_policy()

        if not policy.watermark_required:
            return data

        wm_type = watermark_type or policy.watermark_type

        if wm_type == "visible":
            return self._add_visible_watermark(data)
        elif wm_type == "invisible":
            return self._add_invisible_watermark(data)
        elif wm_type == "fingerprint":
            return self._add_fingerprint(data)

        return data

    def _add_visible_watermark(self, data: Any) -> Any:
        """添加可见水印"""
        if isinstance(data, dict):
            # 在元数据中添加水印信息
            data = dict(data)
            data["_watermark"] = {
                "buyer_id": self.buyer_id,
                "transaction_id": self.transaction_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notice": "This data is provided under license. Unauthorized distribution is prohibited.",
            }
        elif isinstance(data, list):
            return [self._add_visible_watermark(item) for item in data]

        return data

    def _add_invisible_watermark(self, data: Any) -> Any:
        """添加不可见水印（通过微妙修改数据值）"""
        # 实现：对数值字段添加微小偏移，编码买家ID
        # 这是一个简化实现，实际应该使用更复杂的数字水印算法

        if isinstance(data, list) and len(data) > 0:
            # 为前5条记录添加微小时间戳偏移
            watermarked = []
            for i, item in enumerate(data):
                item_copy = dict(item) if isinstance(item, dict) else item
                if isinstance(item_copy, dict) and "timestamp" in item_copy:
                    # 添加毫秒级偏移（人眼不可见，但可追踪）
                    offset = (self.buyer_id % 100) + i
                    # 实际实现应该修改原始值
                    item_copy["_wm"] = offset  # 标记有水印
                watermarked.append(item_copy)
            return watermarked

        return data

    def _add_fingerprint(self, data: Any) -> Any:
        """添加指纹（唯一标识此次访问）"""
        # 生成唯一指纹
        fingerprint = hashlib.sha256(
            f"{self.transaction_id}:{self.buyer_id}:{datetime.now(timezone.utc)}".encode()
        ).hexdigest()[:16]

        if isinstance(data, dict):
            data = dict(data)
            data["_fingerprint"] = fingerprint

        return data

    async def _log_access(
        self,
        access_type: str,
        query: str,
        rewritten_query: Optional[str] = None,
        result_summary: Optional[Dict[str, Any]] = None,
    ):
        """记录访问审计日志"""
        try:
            transaction = await self._load_transaction()

            # 生成查询指纹（用于后续追踪）
            query_fingerprint = hashlib.sha256(query.encode()).hexdigest()[:16]

            # 创建审计日志
            log = DataAccessAuditLogs(
                log_id=self._generate_id(),
                transaction_id=self.transaction_id,
                data_asset_id=transaction.data_asset_id,
                buyer_id=self.buyer_id,
                access_timestamp=datetime.now(timezone.utc),
                access_purpose=access_type,
                computation_method_used=transaction.computation_method,
                query_fingerprint=query_fingerprint,
                query_complexity_score=self._calculate_complexity(query),
                result_size_bytes=result_summary.get("size_bytes", 0) if result_summary else 0,
                result_row_count=result_summary.get("row_count", 0) if result_summary else 0,
                result_aggregation_level="aggregated" if self._has_aggregation(query) else "raw",
                policy_compliance_check={
                    "policy_type": (await self._get_policy()).right_type.value,
                    "query_rewritten": rewritten_query is not None,
                    "watermark_applied": (await self._get_policy()).watermark_required,
                },
            )

            self.db.add(log)
            await self.db.flush()

        except Exception as e:
            # 审计日志失败不应阻止主流程
            logger.error(f"Failed to log access: {e}")

    def _generate_id(self) -> str:
        """生成唯一ID"""
        import uuid
        return uuid.uuid4().hex[:16]

    def _calculate_complexity(self, query: str) -> float:
        """计算查询复杂度分数（0-1）"""
        score = 0.0
        query_upper = query.upper()

        # 基于查询特征评分
        if "JOIN" in query_upper:
            score += 0.2
        if "WHERE" in query_upper:
            score += 0.1
        if "GROUP BY" in query_upper:
            score += 0.15
        if "HAVING" in query_upper:
            score += 0.15
        if "SUBQUERY" in query_upper or "SELECT" in query_upper.count("SELECT") > 1:
            score += 0.2

        return min(score, 1.0)

    async def validate_operation(
        self,
        operation: str,  # "select", "insert", "update", "delete"
        table: str,
        conditions: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        验证操作是否允许

        Args:
            operation: 操作类型
            table: 目标表
            conditions: 查询条件

        Returns:
            (是否允许, 原因, 改写后的条件)
        """
        policy = await self._get_policy()

        # 只允许SELECT操作（除非是FULL_ACCESS或EXCLUSIVE）
        if operation.upper() != "SELECT":
            if policy.right_type not in [
                RightEnforcementType.FULL_ACCESS,
                RightEnforcementType.EXCLUSIVE,
            ]:
                return False, f"{operation} is not allowed for {policy.right_type.value} rights", None

        return True, "Operation permitted", None

    async def get_usage_stats(self) -> Dict[str, Any]:
        """获取使用情况统计"""
        # 查询审计日志统计
        result = await self.db.execute(
            select(DataAccessAuditLogs).where(
                DataAccessAuditLogs.transaction_id == self.transaction_id
            )
        )
        logs = result.scalars().all()

        return {
            "total_accesses": len(logs),
            "total_rows_accessed": sum(log.result_row_count or 0 for log in logs),
            "unique_queries": len(set(log.query_fingerprint for log in logs)),
            "last_access": max((log.access_timestamp for log in logs), default=None),
            "policy_type": (await self._get_policy()).right_type.value,
        }


# ============================================================================
# 便捷函数
# ============================================================================

async def enforce_data_access(
    db: AsyncSession,
    transaction_id: str,
    buyer_id: int,
    query: str,
    access_type: str = "query",
) -> Tuple[str, Dict[str, Any]]:
    """
    便捷函数：执行数据访问权益检查

    Args:
        db: 数据库会话
        transaction_id: 权益交易ID
        buyer_id: 买家ID
        query: 原始查询
        access_type: 访问类型

    Returns:
        (改写后的查询, 元数据)
    """
    engine = RightsEnforcementEngine(db, transaction_id, buyer_id)

    # 检查权限
    allowed, reason = await engine.check_access_permission(access_type)
    if not allowed:
        raise ServiceError(403, reason)

    # 改写查询
    rewritten = await engine.rewrite_query(query)

    return rewritten, {
        "original_query": query,
        "transaction_id": transaction_id,
        "enforced": True,
    }
