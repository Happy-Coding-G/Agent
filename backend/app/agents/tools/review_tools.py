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


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def review_document(doc_id: str, review_type: str = "standard") -> Dict[str, Any]:
        """对指定文档执行质量、合规、完整性三维审查。"""
        from app.db.models import Documents

        try:
            # Load document
            stmt = select(Documents).where(Documents.doc_id == doc_id)
            result = await db.execute(stmt)
            doc = result.scalars().first()

            if not doc:
                return {
                    "success": False,
                    "doc_id": doc_id,
                    "error": "Document not found",
                    "final_status": "rejected",
                }

            content = doc.markdown_text or ""
            title = doc.title or ""
            review_result: Dict[str, Any] = {
                "doc_id": str(doc.doc_id),
                "title": title,
                "content": content,
                "content_length": len(content),
                "loaded": True,
            }

            # Quality check
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
            review_result["quality_score"] = quality_score
            review_result["quality_issues"] = quality_issues

            # Compliance check
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
            review_result["compliance_issues"] = compliance_issues
            review_result["passed_compliance"] = len(compliance_issues) == 0

            # Completeness check
            completeness_issues = []
            if not title:
                completeness_issues.append("Missing title")
            has_headers = bool(re.search(r'^#+\s+', content, re.MULTILINE))
            if not has_headers:
                completeness_issues.append("No markdown headers found (document structure recommended)")
            review_result["completeness_issues"] = completeness_issues
            review_result["passed_completeness"] = len(completeness_issues) <= 2

            # Judge result
            passed = quality_score >= 0.5 and len(compliance_issues) == 0
            review_result["overall_passed"] = passed
            rework_needed = quality_score < 0.5 or len(compliance_issues) > 0 or len(completeness_issues) > 2

            if rework_needed:
                final_status = "manual_review" if review_type == "strict" else "manual_review"
            else:
                final_status = "approved"

            review_result["status"] = final_status
            review_result["message"] = (
                "Document approved for publication" if final_status == "approved"
                else "Document requires manual review"
            )

            return {
                "success": final_status in ("approved", "manual_review"),
                "doc_id": doc_id,
                "review_type": review_type,
                "review_result": review_result,
                "rework_needed": rework_needed,
                "rework_count": 0,
                "final_status": final_status,
            }

        except Exception as e:
            logger.exception(f"Review failed: {e}")
            return {
                "success": False,
                "doc_id": doc_id,
                "error": str(e),
                "final_status": "rejected",
            }

    return [
        StructuredTool.from_function(
            name="review_document",
            func=review_document,
            description="对指定文档执行质量、合规、完整性三维审查。返回审查得分、通过状态、问题列表。",
            args_schema=ReviewDocumentInput,
            coroutine=review_document,
        ),
    ]
