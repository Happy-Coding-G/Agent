"""
AuditSkill - 审计Skill

提供持续审计、合规检查、风险评估、审计报告等能力。
无状态、只读的Skill，可被多个Agent复用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.trade.continuous_audit import ContinuousAuditService

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    """风险评估结果"""
    transaction_id: str
    risk_score: float
    risk_level: str  # low, medium, high, critical
    factors: List[str]
    trend: str  # improving, stable, worsening
    recommendations: List[str]


@dataclass
class AccessSummary:
    """访问摘要"""
    transaction_id: str
    total_access: int
    unique_queries: int
    avg_risk_score: float
    high_risk_count: int
    violation_count: int
    last_access: Optional[datetime]
    access_pattern: str  # normal, suspicious, anomalous


@dataclass
class ComplianceStatus:
    """合规状态"""
    transaction_id: str
    overall_status: str  # compliant, warning, violated
    compliance_rate: float
    violations_by_type: Dict[str, int]
    last_violation: Optional[datetime]
    required_actions: List[str]


class AuditSkill:
    """
    审计Skill

    职责：
    1. 查询审计日志和统计
    2. 评估交易风险
    3. 分析访问模式
    4. 生成审计报告
    5. 检查合规状态

    使用示例：
        skill = AuditSkill(db)

        # 生成审计报告
        report = await skill.generate_audit_report(transaction_id)

        # 评估风险
        risk = await skill.assess_risk(transaction_id)

        # 检查合规
        compliance = await skill.check_compliance(transaction_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_service = ContinuousAuditService(db)

    # ========================================================================
    # 审计报告API
    # ========================================================================

    async def generate_audit_report(
        self,
        transaction_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        生成审计报告

        完整的交易审计报告，包含访问记录、风险分析、违规情况。
        """
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            end_date = datetime.utcnow()

            report = await self.audit_service.generate_audit_report(
                transaction_id=transaction_id,
                start_date=start_date,
                end_date=end_date,
            )

            # 添加分析和建议
            summary = report.get("summary", {})
            total_access = summary.get("total_access_count", 0)
            avg_risk = summary.get("average_risk_score", 0)
            violations = summary.get("violation_count", 0)

            recommendations = []
            if avg_risk > 0.5:
                recommendations.append("风险评分较高，建议审查访问策略")
            if violations > 0:
                recommendations.append(f"发现{violations}起违规，需要处理")
            if total_access > 1000:
                recommendations.append("访问频率异常，可能存在滥用")

            return {
                "success": True,
                "transaction_id": transaction_id,
                "period": report.get("period"),
                "summary": {
                    **summary,
                    "risk_level": self._score_to_risk_level(avg_risk),
                },
                "access_trend": report.get("access_trend", []),
                "violations": report.get("violations", []),
                "recommendations": recommendations,
                "generated_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to generate audit report for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def get_access_summary(self, transaction_id: str) -> Dict[str, Any]:
        """
        获取访问摘要

        快速了解交易的访问概况。
        """
        try:
            # 查询最近30天的访问统计
            since = datetime.utcnow() - timedelta(days=30)

            # 这里简化实现，实际应该从服务获取
            report = await self.generate_audit_report(transaction_id, days=30)

            if not report.get("success"):
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "error": report.get("error"),
                }

            summary = report.get("summary", {})

            # 判断访问模式
            total = summary.get("total_access_count", 0)
            risk = summary.get("average_risk_score", 0)

            if risk > 0.6:
                pattern = "anomalous"
            elif risk > 0.3 or total > 500:
                pattern = "suspicious"
            else:
                pattern = "normal"

            return {
                "success": True,
                "transaction_id": transaction_id,
                "total_access": total,
                "unique_queries": summary.get("unique_queries", 0),
                "avg_risk_score": round(risk, 3),
                "high_risk_count": summary.get("high_risk_access_count", 0),
                "violation_count": summary.get("violation_count", 0),
                "access_pattern": pattern,
                "period_days": 30,
            }

        except Exception as e:
            logger.error(f"Failed to get access summary for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    # ========================================================================
    # 风险评估API
    # ========================================================================

    async def assess_risk(
        self,
        transaction_id: str,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        评估交易风险

        基于近期访问行为计算风险评分。
        """
        try:
            report = await self.generate_audit_report(transaction_id, days=days)

            if not report.get("success"):
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "error": report.get("error"),
                }

            summary = report.get("summary", {})
            risk_score = summary.get("average_risk_score", 0)

            # 识别风险因素
            factors = []

            if summary.get("high_risk_access_count", 0) > 0:
                factors.append("存在高风险访问记录")

            if summary.get("violation_count", 0) > 0:
                factors.append("发现策略违规")

            if summary.get("total_access_count", 0) > 100:
                factors.append("访问频率较高")

            risk_level = self._score_to_risk_level(risk_score)

            # 生成建议
            recommendations = []
            if risk_level == "high":
                recommendations.append("立即暂停数据访问，人工审核")
                recommendations.append("通知数据所有者和管理员")
            elif risk_level == "medium":
                recommendations.append("加强监控频率")
                recommendations.append("审查访问目的合规性")
            else:
                recommendations.append("保持现有监控策略")

            return {
                "success": True,
                "transaction_id": transaction_id,
                "risk_score": round(risk_score, 3),
                "risk_level": risk_level,
                "factors": factors,
                "recommendations": recommendations,
                "period_days": days,
            }

        except Exception as e:
            logger.error(f"Failed to assess risk for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def compare_risk_trend(
        self,
        transaction_id: str,
        period1_days: int = 7,
        period2_days: int = 7,
    ) -> Dict[str, Any]:
        """
        比较风险趋势

        对比两个时间段的风险变化。
        """
        try:
            # 获取两个周期的风险评分
            end1 = datetime.utcnow() - timedelta(days=period2_days)
            start1 = end1 - timedelta(days=period1_days)

            # 这里简化实现，实际应该查询特定时间段
            risk1 = await self.assess_risk(transaction_id, days=period1_days)
            risk2 = await self.assess_risk(transaction_id, days=period2_days)

            score1 = risk1.get("risk_score", 0)
            score2 = risk2.get("risk_score", 0)

            diff = score2 - score1
            change_pct = (diff / score1 * 100) if score1 > 0 else 0

            if diff > 0.1:
                trend = "worsening"
                interpretation = "风险上升，需要关注"
            elif diff < -0.1:
                trend = "improving"
                interpretation = "风险下降，趋势良好"
            else:
                trend = "stable"
                interpretation = "风险稳定"

            return {
                "success": True,
                "transaction_id": transaction_id,
                "period1": {
                    "days": period1_days,
                    "risk_score": score1,
                },
                "period2": {
                    "days": period2_days,
                    "risk_score": score2,
                },
                "change": round(diff, 3),
                "change_percent": round(change_pct, 1),
                "trend": trend,
                "interpretation": interpretation,
            }

        except Exception as e:
            logger.error(f"Failed to compare risk trend for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    # ========================================================================
    # 合规检查API
    # ========================================================================

    async def check_compliance(self, transaction_id: str) -> Dict[str, Any]:
        """
        检查合规状态

        评估交易的合规性。
        """
        try:
            report = await self.generate_audit_report(transaction_id, days=30)

            if not report.get("success"):
                return {
                    "success": False,
                    "transaction_id": transaction_id,
                    "error": report.get("error"),
                }

            summary = report.get("summary", {})
            total_access = summary.get("total_access_count", 0)
            violation_count = summary.get("violation_count", 0)

            # 计算合规率
            if total_access > 0:
                compliance_rate = (total_access - violation_count) / total_access
            else:
                compliance_rate = 1.0

            # 确定状态
            if violation_count == 0:
                status = "compliant"
            elif violation_count <= 2:
                status = "warning"
            else:
                status = "violated"

            # 统计违规类型
            violations = report.get("violations", [])
            violations_by_type = {}
            for v in violations:
                v_type = v.get("type", "unknown")
                violations_by_type[v_type] = violations_by_type.get(v_type, 0) + 1

            # 生成需要采取的行动
            actions = []
            if status == "violated":
                actions.append("立即暂停数据访问权限")
                actions.append("审查所有违规记录")
                actions.append("通知数据所有者和合规团队")
            elif status == "warning":
                actions.append("加强监控和审查")
                actions.append("向买方发送合规提醒")

            return {
                "success": True,
                "transaction_id": transaction_id,
                "overall_status": status,
                "compliance_rate": round(compliance_rate, 3),
                "total_access": total_access,
                "violation_count": violation_count,
                "violations_by_type": violations_by_type,
                "required_actions": actions,
            }

        except Exception as e:
            logger.error(f"Failed to check compliance for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    async def get_violation_details(
        self,
        transaction_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """
        获取违规详情

        详细列出所有违规记录。
        """
        try:
            report = await self.generate_audit_report(transaction_id, days=days)

            violations = report.get("violations", [])

            # 按严重程度分类
            by_severity = {"critical": [], "high": [], "medium": [], "low": []}
            for v in violations:
                severity = v.get("severity", "medium")
                if severity in by_severity:
                    by_severity[severity].append(v)

            return {
                "success": True,
                "transaction_id": transaction_id,
                "total_violations": len(violations),
                "by_severity": {
                    k: len(v) for k, v in by_severity.items()
                },
                "violations": violations,
                "period_days": days,
            }

        except Exception as e:
            logger.error(f"Failed to get violation details for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    # ========================================================================
    # 实时监控API（查询型）
    # ========================================================================

    async def get_real_time_metrics(self, transaction_id: str) -> Dict[str, Any]:
        """
        获取实时指标

        当前交易的实时状态快照。
        """
        try:
            # 查询最近1小时的访问情况
            summary = await self.get_access_summary(transaction_id)

            # 获取最新风险评估
            risk = await self.assess_risk(transaction_id, days=1)

            return {
                "success": True,
                "transaction_id": transaction_id,
                "timestamp": datetime.utcnow().isoformat(),
                "metrics": {
                    "total_access": summary.get("total_access", 0),
                    "avg_risk_score": risk.get("risk_score", 0),
                    "risk_level": risk.get("risk_level", "unknown"),
                    "violation_count": summary.get("violation_count", 0),
                },
                "status": self._determine_status(risk, summary),
            }

        except Exception as e:
            logger.error(f"Failed to get real-time metrics for {transaction_id}: {e}")
            return {
                "success": False,
                "transaction_id": transaction_id,
                "error": str(e),
            }

    def _determine_status(
        self,
        risk: Dict[str, Any],
        summary: Dict[str, Any],
    ) -> str:
        """确定交易状态"""
        risk_level = risk.get("risk_level", "low")
        violations = summary.get("violation_count", 0)

        if risk_level == "critical" or violations > 5:
            return "suspended"
        elif risk_level == "high" or violations > 0:
            return "monitored"
        else:
            return "active"

    # ========================================================================
    # 批量审计API
    # ========================================================================

    async def batch_audit(
        self,
        transaction_ids: List[str],
    ) -> Dict[str, Any]:
        """
        批量审计多个交易

        生成整体审计概览。
        """
        try:
            results = []
            total_violations = 0
            total_high_risk = 0

            for tx_id in transaction_ids:
                report = await self.generate_audit_report(tx_id, days=30)
                if report.get("success"):
                    summary = report.get("summary", {})
                    results.append({
                        "transaction_id": tx_id,
                        "risk_score": summary.get("average_risk_score", 0),
                        "violations": summary.get("violation_count", 0),
                    })
                    total_violations += summary.get("violation_count", 0)
                    total_high_risk += summary.get("high_risk_access_count", 0)

            # 统计风险分布
            risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for r in results:
                level = self._score_to_risk_level(r["risk_score"])
                risk_distribution[level] = risk_distribution.get(level, 0) + 1

            return {
                "success": True,
                "transaction_count": len(transaction_ids),
                "audited_count": len(results),
                "total_violations": total_violations,
                "total_high_risk_access": total_high_risk,
                "risk_distribution": risk_distribution,
                "details": results,
            }

        except Exception as e:
            logger.error(f"Failed to batch audit: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _score_to_risk_level(self, score: float) -> str:
        """风险分数转等级"""
        if score >= 0.7:
            return "critical"
        elif score >= 0.5:
            return "high"
        elif score >= 0.3:
            return "medium"
        else:
            return "low"
