"""Review Tools - Document quality, compliance, and completeness checks.

Extracted from the legacy ReviewAgent LangGraph implementation.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)

REVIEW_CRITERIA = {
    "quality": {
        "min_content_length": 100,
        "max_empty_ratio": 0.3,
    },
    "compliance": {
        "blocked_patterns": [],
    },
    "completeness": {
        "required_metadata": ["title", "source", "created_at"],
    },
}


class ReviewDocumentInput(BaseModel):
    doc_id: str = Field(description="文档ID")
    review_type: str = Field(default="standard", description="审查类型（standard / strict）")


class CheckDocumentQualityInput(BaseModel):
    doc_id: str = Field(description="文档ID")


class CheckDocumentComplianceInput(BaseModel):
    doc_id: str = Field(description="文档ID")


class CheckDocumentCompletenessInput(BaseModel):
    doc_id: str = Field(description="文档ID")


class JudgeReviewInput(BaseModel):
    doc_id: str = Field(description="文档ID")
    quality_score: float = Field(description="质量检查得分 (0.0-1.0)")
    compliance_passed: bool = Field(description="合规检查是否通过")
    completeness_passed: bool = Field(description="完整性检查是否通过")
    review_type: str = Field(default="standard", description="审查类型（standard / strict）")


# ---------------------------------------------------------------------------
# Internal helpers (extracted for reuse by both atomic tools and review_document)
# ---------------------------------------------------------------------------

async def _load_document(db, doc_id: str) -> Optional[Dict[str, Any]]:
    from app.db.models import Documents
    stmt = select(Documents).where(Documents.doc_id == doc_id)
    result = await db.execute(stmt)
    doc = result.scalars().first()
    if not doc:
        return None
    return {
        "doc_id": str(doc.doc_id),
        "title": doc.title or "",
        "content": doc.markdown_text or "",
        "content_length": len(doc.markdown_text or ""),
    }


def _check_quality(content: str) -> Dict[str, Any]:
    quality_issues = []
    criteria = REVIEW_CRITERIA.get("quality", {})
    min_content_length = criteria.get("min_content_length", 100)
    max_empty_ratio = criteria.get("max_empty_ratio", 0.3)
    content_length = len(content)

    if content_length < min_content_length:
        quality_issues.append(f"Content too short: {content_length} chars (min: {min_content_length})")

    empty_chars = sum(1 for c in content if c in ' \n\t\r')
    empty_ratio = empty_chars / content_length if content_length > 0 else 1
    if empty_ratio > max_empty_ratio:
        quality_issues.append(f"Too many empty characters: {empty_ratio:.1%} (max: {max_empty_ratio:.1%})")

    quality_score = 1.0 if not quality_issues else max(0, 1.0 - len(quality_issues) * 0.25)

    return {
        "score": quality_score,
        "issues": quality_issues,
        "content_length": content_length,
    }


def _check_compliance(content: str) -> Dict[str, Any]:
    compliance_issues = []

    ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
    if ssn_pattern.search(content):
        compliance_issues.append("SSN pattern detected")

    api_key_pattern = re.compile(r'(?i)\b(?:sk|api|token|secret)[-_a-z0-9]{12,}\b')
    if api_key_pattern.search(content):
        compliance_issues.append("Potential API key detected")

    email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    if email_pattern.search(content):
        compliance_issues.append("Email address detected (may need redaction)")

    phone_pattern = re.compile(r'\b(?:\+?\d[\d\-\s]{8,}\d)\b')
    if phone_pattern.search(content):
        compliance_issues.append("Phone number detected (may need redaction)")

    return {
        "passed": len(compliance_issues) == 0,
        "issues": compliance_issues,
    }


def _check_completeness(content: str, title: str) -> Dict[str, Any]:
    completeness_issues = []

    if not title:
        completeness_issues.append("Missing title")

    has_headers = bool(re.search(r'^#+\s+', content, re.MULTILINE))
    if not has_headers:
        completeness_issues.append("No markdown headers found (document structure recommended)")

    return {
        "passed": len(completeness_issues) <= 2,
        "issues": completeness_issues,
    }


def _judge_review(
    quality_score: float,
    compliance_passed: bool,
    completeness_passed: bool,
    review_type: str,
) -> Dict[str, Any]:
    passed = quality_score >= 0.5 and compliance_passed
    rework_needed = quality_score < 0.5 or not compliance_passed or not completeness_passed

    if rework_needed:
        final_status = "manual_review"
    else:
        final_status = "approved"

    return {
        "overall_passed": passed,
        "rework_needed": rework_needed,
        "final_status": final_status,
        "message": (
            "Document approved for publication" if final_status == "approved"
            else "Document requires manual review"
        ),
        "review_type": review_type,
    }


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def review_document(doc_id: str, review_type: str = "standard") -> Dict[str, Any]:
        """对指定文档执行质量、合规、完整性三维审查（向后兼容）。"""
        try:
            doc = await _load_document(db, doc_id)
            if not doc:
                return {
                    "success": False,
                    "doc_id": doc_id,
                    "error": "Document not found",
                    "final_status": "rejected",
                }

            content = doc["content"]
            title = doc["title"]

            quality = _check_quality(content)
            compliance = _check_compliance(content)
            completeness = _check_completeness(content, title)
            judgement = _judge_review(
                quality_score=quality["score"],
                compliance_passed=compliance["passed"],
                completeness_passed=completeness["passed"],
                review_type=review_type,
            )

            review_result = {
                "doc_id": doc_id,
                "title": title,
                "content_length": len(content),
                "loaded": True,
                "quality_score": quality["score"],
                "quality_issues": quality["issues"],
                "compliance_issues": compliance["issues"],
                "passed_compliance": compliance["passed"],
                "completeness_issues": completeness["issues"],
                "passed_completeness": completeness["passed"],
                "overall_passed": judgement["overall_passed"],
                "status": judgement["final_status"],
                "message": judgement["message"],
            }

            return {
                "success": judgement["final_status"] in ("approved", "manual_review"),
                "doc_id": doc_id,
                "review_type": review_type,
                "review_result": review_result,
                "rework_needed": judgement["rework_needed"],
                "rework_count": 0,
                "final_status": judgement["final_status"],
            }

        except Exception as e:
            logger.exception(f"Review failed: {e}")
            return {
                "success": False,
                "doc_id": doc_id,
                "error": str(e),
                "final_status": "rejected",
            }

    async def check_document_quality(doc_id: str) -> Dict[str, Any]:
        """对指定文档执行质量检查（内容长度、空字符比例）。"""
        try:
            doc = await _load_document(db, doc_id)
            if not doc:
                return {"success": False, "doc_id": doc_id, "error": "Document not found"}

            quality = _check_quality(doc["content"])
            return {
                "success": True,
                "doc_id": doc_id,
                "check_type": "quality",
                "score": quality["score"],
                "issues": quality["issues"],
                "content_length": quality["content_length"],
                "passed": quality["score"] >= 0.5,
            }
        except Exception as e:
            logger.exception(f"Quality check failed: {e}")
            return {"success": False, "doc_id": doc_id, "error": str(e)}

    async def check_document_compliance(doc_id: str) -> Dict[str, Any]:
        """对指定文档执行合规检查（SSN、API key、邮箱、手机号等敏感信息）。"""
        try:
            doc = await _load_document(db, doc_id)
            if not doc:
                return {"success": False, "doc_id": doc_id, "error": "Document not found"}

            compliance = _check_compliance(doc["content"])
            return {
                "success": True,
                "doc_id": doc_id,
                "check_type": "compliance",
                "passed": compliance["passed"],
                "issues": compliance["issues"],
            }
        except Exception as e:
            logger.exception(f"Compliance check failed: {e}")
            return {"success": False, "doc_id": doc_id, "error": str(e)}

    async def check_document_completeness(doc_id: str) -> Dict[str, Any]:
        """对指定文档执行完整性检查（标题、Markdown 结构）。"""
        try:
            doc = await _load_document(db, doc_id)
            if not doc:
                return {"success": False, "doc_id": doc_id, "error": "Document not found"}

            completeness = _check_completeness(doc["content"], doc["title"])
            return {
                "success": True,
                "doc_id": doc_id,
                "check_type": "completeness",
                "passed": completeness["passed"],
                "issues": completeness["issues"],
            }
        except Exception as e:
            logger.exception(f"Completeness check failed: {e}")
            return {"success": False, "doc_id": doc_id, "error": str(e)}

    async def judge_review(
        doc_id: str,
        quality_score: float,
        compliance_passed: bool,
        completeness_passed: bool,
        review_type: str = "standard",
    ) -> Dict[str, Any]:
        """基于各维度检查结果进行综合判定。"""
        try:
            judgement = _judge_review(quality_score, compliance_passed, completeness_passed, review_type)
            return {
                "success": True,
                "doc_id": doc_id,
                "check_type": "judgement",
                "overall_passed": judgement["overall_passed"],
                "rework_needed": judgement["rework_needed"],
                "final_status": judgement["final_status"],
                "message": judgement["message"],
            }
        except Exception as e:
            logger.exception(f"Judge review failed: {e}")
            return {"success": False, "doc_id": doc_id, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="review_document",
            func=review_document,
            description="对指定文档执行质量、合规、完整性三维审查。返回审查得分、通过状态、问题列表。（向后兼容）",
            args_schema=ReviewDocumentInput,
            coroutine=review_document,
        ),
        StructuredTool.from_function(
            name="check_document_quality",
            func=check_document_quality,
            description="对指定文档执行质量检查：内容长度、空字符比例。返回得分和问题列表。",
            args_schema=CheckDocumentQualityInput,
            coroutine=check_document_quality,
        ),
        StructuredTool.from_function(
            name="check_document_compliance",
            func=check_document_compliance,
            description="对指定文档执行合规检查：检测 SSN、API key、邮箱、手机号等敏感信息。",
            args_schema=CheckDocumentComplianceInput,
            coroutine=check_document_compliance,
        ),
        StructuredTool.from_function(
            name="check_document_completeness",
            func=check_document_completeness,
            description="对指定文档执行完整性检查：标题、Markdown 结构。",
            args_schema=CheckDocumentCompletenessInput,
            coroutine=check_document_completeness,
        ),
        StructuredTool.from_function(
            name="judge_review",
            func=judge_review,
            description="基于质量、合规、完整性检查结果进行综合判定，输出 final_status 和 rework 建议。",
            args_schema=JudgeReviewInput,
            coroutine=judge_review,
        ),
    ]
