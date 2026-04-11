from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import hashlib
import logging
from enum import Enum
from dataclasses import dataclass, field

from app.services.trade.data_rights_events import (
    DataAccessAuditPayload,
    PolicyViolationPayload,
    ComputationMethod,
)
from app.services.trade.negotiation_event_store import NegotiationEventStore
from app.db.models import (
    DataAccessAuditLogs,
    PolicyViolations,
    DataRightsTransactions,
)

logger = logging.getLogger(__name__)


class ViolationType(str, Enum):
    """违规类型"""
    EXCESSIVE_ACCESS = "excessive_access"           # 访问频率过高
    RECONSTRUCTION_ATTEMPT = "reconstruction_attempt"  # 试图重构原始数据
    EXCESSIVE_OUTPUT = "excessive_output"           # 输出数据量过大
    UNAUTHORIZED_PURPOSE = "unauthorized_purpose"   # 未授权用途
    TIME_VIOLATION = "time_violation"               # 超出时间范围
    ALGORITHM_VIOLATION = "algorithm_violation"     # 使用未授权算法
    SUSPICIOUS_PATTERN = "suspicious_pattern"       # 可疑访问模式
    COLLUSION_SUSPECTED = "collusion_suspected"     # 疑似串通


class ViolationSeverity(str, Enum):
    """违规严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AccessPattern:
    """访问模式分析结果"""
    frequency_score: float  # 0-1
    query_patterns: List[str]
    result_sizes: List[int]
    access_times: List[datetime]
    anomaly_indicators: List[str] = field(default_factory=list)


class ContinuousAuditService:
    """
    持续审计服务

    职责：
    1. 记录数据访问日志
    2. 实时异常检测
    3. 策略违规识别
    4. 自动响应执行
    """

    # 异常检测阈值
    THRESHOLDS = {
        "max_hourly_access": 100,      # 每小时最大访问次数
        "max_daily_access": 500,       # 每天最大访问次数
        "max_output_size_mb": 100,     # 最大输出大小(MB)
        "max_result_rows": 10000,      # 最大结果行数
        "suspicious_query_patterns": [
            "SELECT *",                  # 全表查询
            "LIMIT 1000000",             # 超大限制
        ],
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_store = NegotiationEventStore(db)

    async def record_data_access(
        self,
        transaction_id: str,
        negotiation_id: str,
        data_asset_id: str,
        buyer_id: int,
        access_purpose: str,
        computation_method_used: ComputationMethod,
        query: str,
        result_size_bytes: int,
        result_row_count: int,
        result_aggregation_level: str,
    ) -> Dict[str, Any]:
        """
        记录数据访问并实时审计

        Returns:
            审计结果，包含风险评分和异常标记
        """
        # 生成查询指纹
        query_fingerprint = self._generate_query_fingerprint(query)

        # 计算查询复杂度
        complexity_score = self._assess_query_complexity(query)

        # 检查策略合规
        compliance_check = await self._check_policy_compliance(
            transaction_id=transaction_id,
            access_purpose=access_purpose,
            computation_method=computation_method_used,
            query=query,
        )

        # 获取历史访问模式
        access_pattern = await self._analyze_access_pattern(
            transaction_id=transaction_id,
            buyer_id=buyer_id,
        )

        # 计算风险评分
        risk_score = self._calculate_risk_score(
            access_pattern=access_pattern,
            result_size_bytes=result_size_bytes,
            result_row_count=result_row_count,
            compliance_check=compliance_check,
        )

        # 检测异常
        anomaly_flags = self._detect_anomalies(
            access_pattern=access_pattern,
            query=query,
            result_size_bytes=result_size_bytes,
            compliance_check=compliance_check,
        )

        # 创建审计日志
        audit_payload = DataAccessAuditPayload(
            negotiation_id=negotiation_id,
            data_asset_id=data_asset_id,
            data_buyer=buyer_id,
            access_timestamp=datetime.now(timezone.utc),
            access_purpose=access_purpose,
            computation_method_used=computation_method_used,
            query_fingerprint=query_fingerprint,
            query_complexity_score=complexity_score,
            result_size_bytes=result_size_bytes,
            result_row_count=result_row_count,
            result_aggregation_level=result_aggregation_level,
            policy_compliance_check=compliance_check,
            risk_score=risk_score,
            anomaly_flags=anomaly_flags,
        )

        # 保存到数据库
        await self._save_audit_log(audit_payload, transaction_id)

        # 记录到事件溯源
        await self.event_store.append_event(
            session_id=negotiation_id,
            session_type="data_rights_negotiation",
            event_type="DATA_ACCESS_AUDIT",
            agent_id=buyer_id,
            agent_role="data_buyer",
            payload=audit_payload.model_dump(),
        )

        # 如果检测到异常，触发告警
        if anomaly_flags or risk_score > 0.7:
            await self._trigger_alert(
                transaction_id=transaction_id,
                risk_score=risk_score,
                anomaly_flags=anomaly_flags,
            )

        return {
            "audit_id": query_fingerprint,
            "risk_score": risk_score,
            "anomaly_flags": anomaly_flags,
            "compliance_status": compliance_check.get("status", "unknown"),
        }

    def _generate_query_fingerprint(self, query: str) -> str:
        """生成查询指纹（哈希）"""
        normalized = query.lower().replace(" ", "").replace("\n", "")
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    def _assess_query_complexity(self, query: str) -> float:
        """评估查询复杂度 (0-1)"""
        complexity = 0.0
        query_lower = query.lower()

        # JOIN 复杂度
        join_count = query_lower.count("join")
        complexity += min(0.3, join_count * 0.1)

        # 子查询复杂度
        subquery_count = query_lower.count("select") - 1  # 减去主查询
        complexity += min(0.3, subquery_count * 0.15)

        # 聚合复杂度
        agg_functions = ["sum", "count", "avg", "max", "min", "group by"]
        for func in agg_functions:
            if func in query_lower:
                complexity += 0.05

        # 查询长度
        if len(query) > 1000:
            complexity += 0.1

        return min(1.0, complexity)

    async def _check_policy_compliance(
        self,
        transaction_id: str,
        access_purpose: str,
        computation_method: ComputationMethod,
        query: str,
    ) -> Dict[str, Any]:
        """检查策略合规性"""
        # 获取交易信息
        tx = await self._get_transaction(transaction_id)
        if not tx:
            return {"status": "unknown", "violations": ["transaction_not_found"]}

        violations = []

        # 检查用途合规
        allowed_purposes = tx.usage_scope.get("purposes", [])
        if access_purpose not in allowed_purposes:
            violations.append("unauthorized_purpose")

        # 检查计算方法合规
        if computation_method.value != tx.computation_method:
            violations.append("unauthorized_computation_method")

        # 检查时间合规
        now = datetime.now(timezone.utc)
        valid_until = tx.valid_until
        if valid_until and now > valid_until:
            violations.append("expired_access")

        # 检查是否仅聚合查询（如果要求）
        aggregation_required = tx.usage_scope.get("output_constraints", {}).get(
            "aggregation_required", True
        )
        if aggregation_required:
            if "group by" not in query.lower() and "count" not in query.lower():
                violations.append("aggregation_required")

        return {
            "status": "compliant" if not violations else "violated",
            "violations": violations,
            "checked_at": now.isoformat(),
        }

    async def _analyze_access_pattern(
        self,
        transaction_id: str,
        buyer_id: int,
    ) -> AccessPattern:
        """分析访问模式"""
        # 获取最近24小时的访问记录
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        stmt = select(DataAccessAuditLogs).where(
            and_(
                DataAccessAuditLogs.transaction_id == transaction_id,
                DataAccessAuditLogs.access_timestamp >= since,
            )
        ).order_by(DataAccessAuditLogs.access_timestamp)

        result = await self.db.execute(stmt)
        recent_access = result.scalars().all()

        if not recent_access:
            return AccessPattern(
                frequency_score=0.0,
                query_patterns=[],
                result_sizes=[],
                access_times=[],
                anomaly_indicators=[],
            )

        # 计算频率评分
        hourly_count = len(recent_access)
        frequency_score = min(1.0, hourly_count / self.THRESHOLDS["max_hourly_access"])

        # 收集查询模式
        query_patterns = list(set([log.query_fingerprint for log in recent_access]))

        # 收集结果大小
        result_sizes = [log.result_size_bytes for log in recent_access]

        # 收集访问时间
        access_times = [log.access_timestamp for log in recent_access]

        # 检测异常指标
        anomaly_indicators = []

        # 检查访问时间分布
        if len(access_times) >= 3:
            intervals = [
                (access_times[i] - access_times[i-1]).total_seconds()
                for i in range(1, len(access_times))
            ]
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                if avg_interval < 5:  # 平均间隔小于5秒
                    anomaly_indicators.append("rapid_access")

        # 检查输出大小趋势
        if len(result_sizes) >= 3:
            if result_sizes[-1] > result_sizes[0] * 10:  # 输出大小激增
                anomaly_indicators.append("output_size_surge")

        return AccessPattern(
            frequency_score=frequency_score,
            query_patterns=query_patterns,
            result_sizes=result_sizes,
            access_times=access_times,
            anomaly_indicators=anomaly_indicators,
        )

    def _calculate_risk_score(
        self,
        access_pattern: AccessPattern,
        result_size_bytes: int,
        result_row_count: int,
        compliance_check: Dict[str, Any],
    ) -> float:
        """计算风险评分 (0-1)"""
        risk = 0.0

        # 频率风险
        risk += access_pattern.frequency_score * 0.3

        # 输出大小风险
        max_size = self.THRESHOLDS["max_output_size_mb"] * 1024 * 1024
        size_risk = min(1.0, result_size_bytes / max_size)
        risk += size_risk * 0.2

        # 结果行数风险
        row_risk = min(1.0, result_row_count / self.THRESHOLDS["max_result_rows"])
        risk += row_risk * 0.1

        # 合规风险
        if compliance_check.get("status") == "violated":
            violation_count = len(compliance_check.get("violations", []))
            risk += min(0.4, violation_count * 0.2)

        # 异常指标风险
        risk += len(access_pattern.anomaly_indicators) * 0.1

        return min(1.0, risk)

    def _detect_anomalies(
        self,
        access_pattern: AccessPattern,
        query: str,
        result_size_bytes: int,
        compliance_check: Dict[str, Any],
    ) -> List[str]:
        """检测异常"""
        flags = []

        # 频率异常
        if access_pattern.frequency_score > 0.8:
            flags.append("EXCESSIVE_ACCESS")

        # 查询模式异常
        query_lower = query.lower()
        for pattern in self.THRESHOLDS["suspicious_query_patterns"]:
            if pattern.lower() in query_lower:
                flags.append("SUSPICIOUS_QUERY_PATTERN")
                break

        # 输出大小异常
        if result_size_bytes > self.THRESHOLDS["max_output_size_mb"] * 1024 * 1024:
            flags.append("EXCESSIVE_OUTPUT")

        # 合规违规
        violations = compliance_check.get("violations", [])
        for violation in violations:
            if violation == "unauthorized_purpose":
                flags.append("UNAUTHORIZED_PURPOSE")
            elif violation == "expired_access":
                flags.append("TIME_VIOLATION")

        # 访问模式异常
        flags.extend(access_pattern.anomaly_indicators)

        return list(set(flags))  # 去重

    async def _save_audit_log(
        self,
        payload: DataAccessAuditPayload,
        transaction_id: str,
    ) -> None:
        """保存审计日志到数据库"""
        log = DataAccessAuditLogs(
            log_id=f"log_{hashlib.sha256(f'{transaction_id}_{datetime.now().isoformat()}'.encode()).hexdigest()[:24]}",
            transaction_id=transaction_id,
            negotiation_id=payload.negotiation_id,
            data_asset_id=payload.data_asset_id,
            buyer_id=payload.data_buyer,
            access_timestamp=payload.access_timestamp,
            access_purpose=payload.access_purpose,
            computation_method_used=payload.computation_method_used,
            query_fingerprint=payload.query_fingerprint,
            query_complexity_score=payload.query_complexity_score,
            result_size_bytes=payload.result_size_bytes,
            result_row_count=payload.result_row_count,
            result_aggregation_level=payload.result_aggregation_level,
            policy_compliance_check=payload.policy_compliance_check,
            risk_score=payload.risk_score,
            anomaly_flags=payload.anomaly_flags,
        )
        self.db.add(log)
        await self.db.flush()

    async def _trigger_alert(
        self,
        transaction_id: str,
        risk_score: float,
        anomaly_flags: List[str],
    ) -> None:
        """触发告警"""
        logger.warning(
            f"ALERT: Transaction {transaction_id} - "
            f"Risk Score: {risk_score:.2f}, "
            f"Anomalies: {anomaly_flags}"
        )

        # 高风险自动采取行动
        if risk_score > 0.8:
            await self._take_automatic_action(
                transaction_id=transaction_id,
                action="throttle",
                reason=f"High risk score: {risk_score:.2f}",
            )

    async def report_violation(
        self,
        transaction_id: str,
        violation_type: ViolationType,
        severity: ViolationSeverity,
        details: Dict[str, Any],
        evidence: Dict[str, Any],
        automatic_action: Optional[str] = None,
    ) -> str:
        """
        报告策略违规

        Returns:
            violation_id: 违规记录ID
        """
        violation_id = f"viol_{hashlib.sha256(f'{transaction_id}_{datetime.now().isoformat()}'.encode()).hexdigest()[:20]}"

        # 创建违规记录
        violation = PolicyViolations(
            violation_id=violation_id,
            transaction_id=transaction_id,
            negotiation_id=details.get("negotiation_id"),
            data_asset_id=details.get("data_asset_id", "unknown"),
            violation_type=violation_type.value,
            severity=severity.value,
            violation_details=details,
            evidence=evidence,
            potential_data_exposure=details.get("potential_exposure"),
            affected_records_estimate=details.get("affected_records"),
            automatic_action_taken=automatic_action,
        )
        self.db.add(violation)
        await self.db.flush()

        # 记录到事件溯源
        payload = PolicyViolationPayload(
            negotiation_id=details.get("negotiation_id", ""),
            violation_type=violation_type.value,
            severity=severity.value,
            violation_details=details,
            evidence=evidence,
            automatic_action_taken=automatic_action,
        )

        await self.event_store.append_event(
            session_id=details.get("negotiation_id", ""),
            session_type="data_rights_negotiation",
            event_type="POLICY_VIOLATION",
            agent_id=0,  # 系统报告
            agent_role="system",
            payload=payload.model_dump(),
        )

        logger.error(
            f"Violation reported: {violation_id} - "
            f"Type: {violation_type.value}, "
            f"Severity: {severity.value}"
        )

        # 严重违规自动采取行动
        if severity in [ViolationSeverity.HIGH, ViolationSeverity.CRITICAL]:
            await self._take_automatic_action(
                transaction_id=transaction_id,
                action="suspend",
                reason=f"{severity.value} violation: {violation_type.value}",
            )

        return violation_id

    async def _take_automatic_action(
        self,
        transaction_id: str,
        action: str,
        reason: str,
    ) -> None:
        """执行自动响应措施"""
        logger.info(f"Taking automatic action '{action}' on {transaction_id}: {reason}")

        # 获取交易
        tx = await self._get_transaction(transaction_id)
        if not tx:
            return

        if action == "throttle":
            # 限流：暂时降低访问频率
            # 实际实现应与限流服务集成
            pass

        elif action == "suspend":
            # 暂停：暂时中止数据访问权限
            tx.status = "violated"
            await self.db.flush()

        elif action == "revoke":
            # 撤销：完全撤销数据权益
            tx.status = "revoked"
            await self.db.flush()

    async def generate_audit_report(
        self,
        transaction_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        生成审计报告

        Returns:
            审计报告
        """
        if not start_date:
            start_date = datetime.now(timezone.utc) - timedelta(days=30)
        if not end_date:
            end_date = datetime.now(timezone.utc)

        # 查询访问日志
        stmt = select(DataAccessAuditLogs).where(
            and_(
                DataAccessAuditLogs.transaction_id == transaction_id,
                DataAccessAuditLogs.access_timestamp >= start_date,
                DataAccessAuditLogs.access_timestamp <= end_date,
            )
        ).order_by(DataAccessAuditLogs.access_timestamp)

        result = await self.db.execute(stmt)
        logs = result.scalars().all()

        # 查询违规记录
        violations_stmt = select(PolicyViolations).where(
            and_(
                PolicyViolations.transaction_id == transaction_id,
                PolicyViolations.detected_at >= start_date,
                PolicyViolations.detected_at <= end_date,
            )
        )
        violations_result = await self.db.execute(violations_stmt)
        violations = violations_result.scalars().all()

        # 统计
        total_access = len(logs)
        avg_risk_score = sum(log.risk_score or 0 for log in logs) / total_access if total_access > 0 else 0
        high_risk_access = sum(1 for log in logs if (log.risk_score or 0) > 0.7)

        return {
            "transaction_id": transaction_id,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "summary": {
                "total_access_count": total_access,
                "unique_queries": len(set(log.query_fingerprint for log in logs)),
                "average_risk_score": round(avg_risk_score, 3),
                "high_risk_access_count": high_risk_access,
                "violation_count": len(violations),
            },
            "access_trend": [
                {
                    "date": log.access_timestamp.isoformat(),
                    "risk_score": log.risk_score,
                    "result_size": log.result_size_bytes,
                }
                for log in logs[-30:]  # 最近30条
            ],
            "violations": [
                {
                    "violation_id": v.violation_id,
                    "type": v.violation_type,
                    "severity": v.severity,
                    "detected_at": v.detected_at.isoformat(),
                    "status": v.manual_review_status,
                }
                for v in violations
            ],
        }

    async def _get_transaction(self, transaction_id: str) -> Optional[DataRightsTransactions]:
        """获取交易信息"""
        stmt = select(DataRightsTransactions).where(
            DataRightsTransactions.transaction_id == transaction_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()