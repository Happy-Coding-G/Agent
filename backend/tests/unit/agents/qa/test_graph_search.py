"""Tests for graph_search tool."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.tools.qa_tools import (
    _to_candidate,
    _assess_overall_confidence,
)


class TestGraphSearchTool:
    """Test graph_search tool behavior."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        return registry

    @pytest.mark.asyncio
    async def test_graph_search_space_not_found(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        graph_tool = next(t for t in tools if t.name == "graph_search")

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=None)
            mock_repo_cls.return_value = mock_repo

            result = await graph_tool.ainvoke({"query": "test", "space_id": "bad_space", "top_k": 5})

        assert result["success"] is False
        assert "Space not found" in result["error"]

    @pytest.mark.asyncio
    async def test_graph_search_neo4j_disabled(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        graph_tool = next(t for t in tools if t.name == "graph_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.agents.tools.qa_tools._graph_search_internal") as mock_graph:
                mock_graph.return_value = []
                result = await graph_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert result["candidates"] == []
        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_graph_search_no_documents(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        graph_tool = next(t for t in tools if t.name == "graph_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.agents.tools.qa_tools._graph_search_internal") as mock_graph:
                mock_graph.return_value = []
                result = await graph_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert result["candidates"] == []


class TestGraphSearchHelpers:
    """Test graph_search helper functions."""

    def test_to_candidate_graph_format(self):
        item = {
            "chunk_id": None,
            "doc_id": "d1",
            "chunk_index": 2,
            "doc_title": "Doc G",
            "section_path": None,
            "content": "",
            "score": 0.65,
            "graph_evidence": "Entity [Type] --RELATES--> Other | fact here",
            "match_terms": ["term1"],
        }
        cand = _to_candidate(item, "graph")
        assert cand["candidate_id"] == "graph:d1:2"
        assert cand["source_type"] == "graph"
        assert cand["confidence"] == "medium"
        assert cand["metadata"]["graph_evidence"] == "Entity [Type] --RELATES--> Other | fact here"
        assert cand["metadata"]["match_terms"] == ["term1"]

    def test_graph_candidate_no_evidence(self):
        item = {
            "doc_id": "d1",
            "chunk_index": 0,
            "doc_title": "Doc",
            "score": 0.3,
        }
        cand = _to_candidate(item, "graph")
        assert cand["metadata"]["graph_evidence"] is None
        assert cand["metadata"]["match_terms"] is None

    def test_overall_confidence_medium(self):
        cands = [{"score": 0.5}, {"score": 0.4}]
        assert _assess_overall_confidence(cands) == "medium"
