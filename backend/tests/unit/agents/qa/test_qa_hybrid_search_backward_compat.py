"""Backward compatibility tests for qa_hybrid_search."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


class TestQAHybridSearchBackwardCompat:
    """Ensure qa_hybrid_search output format hasn't changed."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        return registry

    @pytest.mark.asyncio
    async def test_qa_hybrid_search_output_format(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        hybrid_tool = next(t for t in tools if t.name == "qa_hybrid_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.ai.embedding_client.embed_query_with_fallback") as mock_embed:
                mock_embed.return_value = ([0.1] * 1536, "model")

                mock_chunk = MagicMock()
                mock_chunk.chunk_id = "chunk-1"
                mock_chunk.chunk_index = 0
                mock_chunk.section_path = "Intro"
                mock_chunk.content = "hybrid content"

                mock_doc = MagicMock()
                mock_doc.doc_id = "doc-1"
                mock_doc.title = "Doc Title"

                mock_result = MagicMock()
                mock_result.all.return_value = [(mock_chunk, mock_doc, 0.85)]
                mock_registry.db.execute = AsyncMock(return_value=mock_result)

                with patch("app.core.config.settings.NEO4J_URI", ""):
                    result = await hybrid_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert "query" in result
        assert "space_id" in result
        assert "results" in result
        assert "sources" in result
        assert "debug" in result

        # Verify debug fields
        assert "vector_count" in result["debug"]
        assert "graph_count" in result["debug"]
        assert "hybrid_count" in result["debug"]

        # Verify sources format
        if result["sources"]:
            src = result["sources"][0]
            assert "doc_id" in src
            assert "title" in src
            assert "section" in src
            assert "score" in src
            assert "source_type" in src
            assert "excerpt" in src

    @pytest.mark.asyncio
    async def test_qa_hybrid_search_empty_results_format(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        hybrid_tool = next(t for t in tools if t.name == "qa_hybrid_search")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            with patch("app.ai.embedding_client.embed_query_with_fallback") as mock_embed:
                mock_embed.return_value = ([0.1] * 1536, "model")

                mock_result = MagicMock()
                mock_result.all.return_value = []
                mock_registry.db.execute = AsyncMock(return_value=mock_result)

                with patch("app.core.config.settings.NEO4J_URI", ""):
                    result = await hybrid_tool.ainvoke({"query": "test", "space_id": "space_1", "top_k": 5})

        assert result["success"] is True
        assert result["results"] == []
        assert result["sources"] == []
        assert result["debug"]["vector_count"] == 0
        assert result["debug"]["graph_count"] == 0
        assert result["debug"]["hybrid_count"] == 0

    @pytest.mark.asyncio
    async def test_qa_hybrid_search_error_format(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        hybrid_tool = next(t for t in tools if t.name == "qa_hybrid_search")

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=None)
            mock_repo_cls.return_value = mock_repo

            result = await hybrid_tool.ainvoke({"query": "test", "space_id": "bad_space", "top_k": 5})

        assert result["success"] is False
        assert "error" in result
        assert result["results"] == []
        assert result["sources"] == []

    def test_qa_hybrid_search_result_item_format(self):
        """Verify _hybrid_merge output has the expected backward-compatible fields."""
        from app.agents.tools.qa_tools import _hybrid_merge

        vector_results = [
            {
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "chunk_index": 0,
                "doc_title": "Title",
                "section_path": "Section 1",
                "content": "content",
                "score": 0.9,
            }
        ]
        graph_results = []
        merged = _hybrid_merge(vector_results, graph_results, top_k=5)

        assert len(merged) > 0
        item = merged[0]
        # Backward-compatible fields
        assert "doc_id" in item
        assert "chunk_index" in item
        assert "doc_title" in item
        assert "section_path" in item
        assert "content" in item
        assert "score" in item
        assert "sources" in item
