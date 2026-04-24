"""Tests for review_document atomic dimension checks."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.tools.review_tools import (
    _check_quality,
    _check_compliance,
    _check_completeness,
    _judge_review,
)


class TestReviewHelpers:
    """Test extracted review helper functions."""

    def test_check_quality_pass(self):
        content = "a" * 200
        result = _check_quality(content)
        assert result["score"] == 1.0
        assert result["issues"] == []
        assert result["content_length"] == 200

    def test_check_quality_fail_too_short(self):
        content = "short"
        result = _check_quality(content)
        assert result["score"] < 1.0
        assert any("too short" in i.lower() for i in result["issues"])

    def test_check_quality_fail_too_many_empty(self):
        content = "   \n\t\r" * 50 + "a"
        result = _check_quality(content)
        assert result["score"] < 1.0
        assert any("empty" in i.lower() for i in result["issues"])

    def test_check_compliance_pass(self):
        content = "This is a normal document without sensitive data."
        result = _check_compliance(content)
        assert result["passed"] is True
        assert result["issues"] == []

    def test_check_compliance_detects_email(self):
        content = "Contact us at admin@example.com for details."
        result = _check_compliance(content)
        assert result["passed"] is False
        assert any("email" in i.lower() for i in result["issues"])

    def test_check_compliance_detects_api_key(self):
        content = "API key: sk-abc1234567890abcdef"
        result = _check_compliance(content)
        assert result["passed"] is False
        assert any("api key" in i.lower() for i in result["issues"])

    def test_check_completeness_pass(self):
        content = "# Title\n\nBody"
        result = _check_completeness(content, "My Title")
        assert result["passed"] is True
        assert result["issues"] == []

    def test_check_completeness_missing_title(self):
        content = "# Title\n\nBody"
        result = _check_completeness(content, "")
        assert result["passed"] is True  # 1 issue <= 2 threshold
        assert any("title" in i.lower() for i in result["issues"])

    def test_check_completeness_no_headers(self):
        content = "Just plain text without markdown headers."
        result = _check_completeness(content, "Title")
        assert any("headers" in i.lower() for i in result["issues"])

    def test_judge_review_approved(self):
        result = _judge_review(1.0, True, True, "standard")
        assert result["final_status"] == "approved"
        assert result["rework_needed"] is False

    def test_judge_review_quality_fail(self):
        result = _judge_review(0.3, True, True, "standard")
        assert result["final_status"] == "manual_review"
        assert result["rework_needed"] is True

    def test_judge_review_compliance_fail(self):
        result = _judge_review(0.8, False, True, "standard")
        assert result["final_status"] == "manual_review"
        assert result["rework_needed"] is True

    def test_judge_review_completeness_fail(self):
        result = _judge_review(0.8, True, False, "standard")
        assert result["final_status"] == "manual_review"
        assert result["rework_needed"] is True


class TestReviewAtomicTools:
    """Test atomic review tools via build_tools."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        return registry

    @pytest.mark.asyncio
    async def test_check_document_quality_tool(self, mock_registry):
        from app.agents.tools.review_tools import build_tools

        tools = build_tools(mock_registry)
        quality_tool = next(t for t in tools if t.name == "check_document_quality")

        mock_doc = MagicMock()
        mock_doc.doc_id = "doc-1"
        mock_doc.title = "Title"
        mock_doc.markdown_text = "a" * 500

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_doc
        mock_registry.db.execute = AsyncMock(return_value=mock_result)

        result = await quality_tool.ainvoke({"doc_id": "doc-1"})
        assert result["success"] is True
        assert result["check_type"] == "quality"
        assert result["score"] == 1.0
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_check_document_compliance_tool(self, mock_registry):
        from app.agents.tools.review_tools import build_tools

        tools = build_tools(mock_registry)
        compliance_tool = next(t for t in tools if t.name == "check_document_compliance")

        mock_doc = MagicMock()
        mock_doc.doc_id = "doc-1"
        mock_doc.markdown_text = "Contact us at test@example.com"

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_doc
        mock_registry.db.execute = AsyncMock(return_value=mock_result)

        result = await compliance_tool.ainvoke({"doc_id": "doc-1"})
        assert result["success"] is True
        assert result["check_type"] == "compliance"
        assert result["passed"] is False
        assert any("email" in i.lower() for i in result["issues"])

    @pytest.mark.asyncio
    async def test_check_document_completeness_tool(self, mock_registry):
        from app.agents.tools.review_tools import build_tools

        tools = build_tools(mock_registry)
        completeness_tool = next(t for t in tools if t.name == "check_document_completeness")

        mock_doc = MagicMock()
        mock_doc.doc_id = "doc-1"
        mock_doc.title = ""
        mock_doc.markdown_text = "No headers here."

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_doc
        mock_registry.db.execute = AsyncMock(return_value=mock_result)

        result = await completeness_tool.ainvoke({"doc_id": "doc-1"})
        assert result["success"] is True
        assert result["check_type"] == "completeness"
        assert len(result["issues"]) >= 1

    @pytest.mark.asyncio
    async def test_judge_review_tool(self):
        from app.agents.tools.review_tools import build_tools

        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        tools = build_tools(registry)
        judge_tool = next(t for t in tools if t.name == "judge_review")

        result = await judge_tool.ainvoke({
            "doc_id": "doc-1",
            "quality_score": 0.9,
            "compliance_passed": True,
            "completeness_passed": True,
            "review_type": "standard",
        })
        assert result["success"] is True
        assert result["check_type"] == "judgement"
        assert result["final_status"] == "approved"

    @pytest.mark.asyncio
    async def test_review_document_backward_compat(self, mock_registry):
        from app.agents.tools.review_tools import build_tools

        tools = build_tools(mock_registry)
        review_tool = next(t for t in tools if t.name == "review_document")

        mock_doc = MagicMock()
        mock_doc.doc_id = "doc-1"
        mock_doc.title = "Title"
        mock_doc.markdown_text = "# Heading\n\nContent here."

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_doc
        mock_registry.db.execute = AsyncMock(return_value=mock_result)

        result = await review_tool.ainvoke({"doc_id": "doc-1", "review_type": "standard"})
        assert result["success"] is True
        assert "review_result" in result
        assert result["final_status"] == "approved"
