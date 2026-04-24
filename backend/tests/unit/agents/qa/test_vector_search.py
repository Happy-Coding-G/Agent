"""Tests for vector_search tool."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.tools.qa_tools import (
    _to_candidate,
    _assess_overall_confidence,
    _assess_single_confidence,
)


class TestVectorSearchTool:
    """Test vector_search tool behavior."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        return registry

    @pytest.mark.asyncio
    async def test_vector_search_space_not_found(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        vector_tool = next(t for t in tools if t.name == "vector_search")

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=None)
            mock_repo_cls.return_value = mock_repo

            result = await vector_tool.ainvoke({"query": "test", "space_id": "bad_space", "top_k": 5})

        assert result["success"] is False
        assert "Space not found" in result["error"]
        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_vector_search_returns_candidates(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        vector_tool = next(t for t in tools if t.name == "vector_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.agents.tools.qa_tools._vector_search_internal") as mock_vec:
                mock_vec.return_value = [
                    {
                        "chunk_id": "chunk-1",
                        "doc_id": "doc-1",
                        "chunk_index": 0,
                        "doc_title": "Doc A",
                        "section_path": "Section 1",
                        "content": "vector search content",
                        "score": 0.85,
                    }
                ]

                result = await vector_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert len(result["candidates"]) >= 1
        assert result["confidence"] == "high"
        cand = result["candidates"][0]
        assert cand["source_type"] == "vector"
        assert "candidate_id" in cand

    @pytest.mark.asyncio
    async def test_vector_search_empty_results(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        vector_tool = next(t for t in tools if t.name == "vector_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.agents.tools.qa_tools._vector_search_internal") as mock_vec:
                mock_vec.return_value = []

                result = await vector_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert result["candidates"] == []
        assert result["confidence"] == "low"


class TestVectorSearchHelpers:
    """Test vector_search helper functions."""

    def test_to_candidate_vector_format(self):
        item = {
            "chunk_id": "c1",
            "doc_id": "d1",
            "chunk_index": 0,
            "doc_title": "Doc A",
            "section_path": "S1",
            "content": "content A",
            "score": 0.82,
        }
        cand = _to_candidate(item, "vector")
        assert cand["candidate_id"] == "vector:d1:0"
        assert cand["chunk_id"] == "c1"
        assert cand["doc_id"] == "d1"
        assert cand["doc_title"] == "Doc A"
        assert cand["score"] == 0.82
        assert cand["source_type"] == "vector"
        assert cand["confidence"] == "high"
        assert cand["metadata"] == {}

    def test_to_candidate_low_score(self):
        item = {
            "chunk_id": "c2",
            "doc_id": "d2",
            "chunk_index": 1,
            "doc_title": "Doc B",
            "section_path": None,
            "content": "content B",
            "score": 0.25,
        }
        cand = _to_candidate(item, "vector")
        assert cand["confidence"] == "low"

    def test_assess_overall_confidence_with_candidates(self):
        cands = [
            {"score": 0.85},
            {"score": 0.6},
            {"score": 0.3},
        ]
        assert _assess_overall_confidence(cands) == "high"

    def test_assess_single_confidence_boundaries(self):
        assert _assess_single_confidence(0.7) == "high"
        assert _assess_single_confidence(0.69) == "medium"
        assert _assess_single_confidence(0.4) == "medium"
        assert _assess_single_confidence(0.39) == "low"
