"""
ReviewAgent - LangGraph-based document review agent with quality, compliance, and completeness checks.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core import REVIEW_CRITERIA, ReviewState
from app.db.models import Documents

logger = logging.getLogger(__name__)


class ReviewAgent:
    """Agent for reviewing documents with quality, compliance, and completeness checks."""

    def __init__(self, db: AsyncSession):
        """
        Initialize ReviewAgent.

        Args:
            db: AsyncSession for database operations
        """
        self.db = db
        self.graph = self._build_graph()
        self.max_rework = 3

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for document review."""
        builder = StateGraph(ReviewState)

        builder.add_node("load_document", RunnableLambda(self._load_document_node))
        builder.add_node("quality_check", RunnableLambda(self._quality_check_node))
        builder.add_node("compliance_check", RunnableLambda(self._compliance_check_node))
        builder.add_node("completeness_check", RunnableLambda(self._completeness_check_node))
        builder.add_node("judge_result", RunnableLambda(self._judge_result_node))
        builder.add_node("finalize", RunnableLambda(self._finalize_node))

        builder.add_edge("load_document", "quality_check")
        builder.add_edge("quality_check", "compliance_check")
        builder.add_edge("compliance_check", "completeness_check")
        builder.add_edge("completeness_check", "judge_result")

        # 条件分支：需要 rework 且未超限时回到 quality_check 重新审查，否则进入 finalize。
        builder.add_conditional_edges(
            "judge_result",
            self._should_rework,
            {"rework": "quality_check", "done": "finalize"}
        )
        builder.add_edge("finalize", END)

        builder.set_entry_point("load_document")
        return builder.compile()

    async def _load_document_node(self, state: ReviewState) -> ReviewState:
        """Load the document to be reviewed."""
        doc_id = state.get("doc_id")
        if not doc_id:
            state["review_result"] = {"error": "No document ID provided"}
            state["final_status"] = "rejected"
            return state

        try:
            stmt = select(Documents).where(Documents.doc_id == doc_id)
            result = await self.db.execute(stmt)
            doc = result.scalars().first()

            if not doc:
                state["review_result"] = {"error": "Document not found"}
                state["final_status"] = "rejected"
                return state

            state["review_result"] = {
                "doc_id": str(doc.doc_id),
                "title": doc.title,
                "content": doc.markdown_text or "",
                "content_length": len(doc.markdown_text or ""),
                "loaded": True
            }

        except Exception as e:
            logger.error(f"Failed to load document: {e}")
            state["review_result"] = {"error": f"Failed to load document: {str(e)}"}
            state["final_status"] = "rejected"

        return state

    async def _quality_check_node(self, state: ReviewState) -> ReviewState:
        """Check document quality metrics."""
        review_result = state.get("review_result", {})
        content = review_result.get("content", "")

        if not content:
            review_result["quality_score"] = 0
            review_result["quality_issues"] = ["No content available"]
            state["review_result"] = review_result
            return state

        criteria = REVIEW_CRITERIA.get("quality", {})
        min_content_length = criteria.get("min_content_length", 100)
        max_empty_ratio = criteria.get("max_empty_ratio", 0.3)

        issues = []

        # Check content length
        content_length = len(content)
        if content_length < min_content_length:
            issues.append(f"Content too short: {content_length} chars (min: {min_content_length})")

        # Check empty ratio
        empty_chars = sum(1 for c in content if c in ' \n\t\r')
        empty_ratio = empty_chars / content_length if content_length > 0 else 1
        if empty_ratio > max_empty_ratio:
            issues.append(f"Too many empty characters: {empty_ratio:.1%} (max: {max_empty_ratio:.1%})")

        # Calculate quality score
        if not issues:
            quality_score = 1.0
        else:
            quality_score = max(0, 1.0 - len(issues) * 0.25)

        review_result["quality_score"] = quality_score
        review_result["quality_issues"] = issues
        state["review_result"] = review_result

        return state

    async def _compliance_check_node(self, state: ReviewState) -> ReviewState:
        """Check document compliance (SSN patterns, secrets, etc.)."""
        review_result = state.get("review_result", {})
        content = review_result.get("content", "")

        if not content:
            review_result["compliance_issues"] = []
            state["review_result"] = review_result
            return state

        criteria = REVIEW_CRITERIA.get("compliance", {})
        blocked_patterns = criteria.get("blocked_patterns", [])

        issues = []

        # SSN pattern (example: XXX-XX-XXXX)
        ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
        if ssn_pattern.search(content):
            issues.append("SSN pattern detected")

        # API key patterns
        api_key_pattern = re.compile(r'(?i)\b(?:sk|api|token|secret)[-_a-z0-9]{12,}\b')
        if api_key_pattern.search(content):
            issues.append("Potential API key detected")

        # Email patterns
        email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        if email_pattern.search(content):
            issues.append("Email address detected (may need redaction)")

        # Phone number patterns
        phone_pattern = re.compile(r'\b(?:\+?\d[\d\-\s]{8,}\d)\b')
        if phone_pattern.search(content):
            issues.append("Phone number detected (may need redaction)")

        review_result["compliance_issues"] = issues
        review_result["passed_compliance"] = len(issues) == 0
        state["review_result"] = review_result

        return state

    async def _completeness_check_node(self, state: ReviewState) -> ReviewState:
        """Check document completeness (required metadata)."""
        review_result = state.get("review_result", {})
        title = review_result.get("title")

        criteria = REVIEW_CRITERIA.get("completeness", {})
        required_metadata = criteria.get("required_metadata", ["title", "source", "created_at"])

        issues = []

        # Check title
        if "title" in required_metadata and not title:
            issues.append("Missing title")

        # Check content has structure (headers, etc.)
        content = review_result.get("content", "")
        has_headers = bool(re.search(r'^#+\s+', content, re.MULTILINE))
        if not has_headers:
            issues.append("No markdown headers found (document structure recommended)")

        review_result["completeness_issues"] = issues
        review_result["passed_completeness"] = len(issues) == 0
        state["review_result"] = review_result

        return state

    def _should_rework(self, state: ReviewState) -> str:
        """Decide whether to loop back for rework or proceed to finalize."""
        rework_needed = state.get("rework_needed", False)
        rework_count = state.get("rework_count", 0)
        max_rework = state.get("max_rework", self.max_rework)

        if rework_needed and rework_count < max_rework:
            return "rework"
        return "done"

    async def _judge_result_node(self, state: ReviewState) -> ReviewState:
        """Judge the overall review result and determine if rework is needed."""
        review_result = state.get("review_result", {})

        quality_score = review_result.get("quality_score", 0)
        compliance_issues = review_result.get("compliance_issues", [])
        completeness_issues = review_result.get("completeness_issues", [])

        # Determine if rework is needed
        rework_needed = False
        reasons = []

        if quality_score < 0.5:
            rework_needed = True
            reasons.append(f"Low quality score: {quality_score:.2f}")

        if len(compliance_issues) > 0:
            rework_needed = True
            reasons.append(f"Compliance issues: {', '.join(compliance_issues)}")

        if len(completeness_issues) > 2:
            rework_needed = True
            reasons.append(f"Multiple completeness issues: {', '.join(completeness_issues)}")

        # Overall pass/fail
        passed = quality_score >= 0.5 and len(compliance_issues) == 0

        review_result["overall_passed"] = passed
        review_result["rework_reasons"] = reasons
        state["rework_needed"] = rework_needed
        state["review_result"] = review_result

        # Handle rework counter and final_status decision
        rework_count = state.get("rework_count", 0)
        max_rework = state.get("max_rework", self.max_rework)

        if rework_needed and rework_count < max_rework:
            state["rework_count"] = rework_count + 1
        elif rework_needed and rework_count >= max_rework:
            state["final_status"] = "manual_review"
            state["rework_needed"] = False  # stop looping
        else:
            state["final_status"] = "approved"

        return state

    async def _finalize_node(self, state: ReviewState) -> ReviewState:
        """Finalize the review result."""
        review_result = state.get("review_result", {})
        final_status = state.get("final_status", "rejected")

        if final_status == "approved":
            review_result["status"] = "approved"
            review_result["message"] = "Document approved for publication"
        elif final_status == "manual_review":
            review_result["status"] = "manual_review"
            review_result["message"] = "Document requires manual review"
        else:
            review_result["status"] = "rejected"
            review_result["message"] = "Document rejected"

        state["review_result"] = review_result
        return state

    async def run(self, doc_id: str, review_type: str = "standard") -> dict[str, Any]:
        """
        Run the document review.

        Args:
            doc_id: Document UUID to review
            review_type: Type of review (standard, strict)

        Returns:
            Dict containing review results
        """
        initial_state: ReviewState = {
            "doc_id": doc_id,
            "review_type": review_type,
            "review_result": {},
            "rework_needed": False,
            "rework_count": 0,
            "max_rework": self.max_rework,
            "final_status": "pending"
        }

        try:
            result = await self.graph.ainvoke(initial_state)
            return {
                "success": result.get("final_status") in ["approved", "manual_review"],
                "doc_id": doc_id,
                "review_type": review_type,
                "review_result": result.get("review_result", {}),
                "rework_needed": result.get("rework_needed", False),
                "rework_count": result.get("rework_count", 0),
                "final_status": result.get("final_status", "rejected")
            }
        except Exception as e:
            logger.exception(f"ReviewAgent error: {e}")
            return {
                "success": False,
                "doc_id": doc_id,
                "error": str(e),
                "final_status": "rejected"
            }
