"""Tests for rerank tool."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


class TestRerankTool:
    """Test rerank tool behavior."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        return registry

    @pytest.mark.asyncio
    async def test_rerank_space_not_found(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=None)
            mock_repo_cls.return_value = mock_repo

            result = await rerank_tool.ainvoke({
                "query": "test",
                "space_id": "bad_space",
                "candidate_refs": [],
                "top_k": 5,
            })

        assert result["success"] is False
        assert "Space not found" in result["error"]

    @pytest.mark.asyncio
    async def test_rerank_empty_input(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            result = await rerank_tool.ainvoke({
                "query": "test",
                "space_id": "space_1",
                "candidate_refs": [],
                "top_k": 5,
            })

        assert result["success"] is True
        assert result["candidates"] == []
        assert result["debug"]["fallback_reason"] == "empty_input"

    @pytest.mark.asyncio
    async def test_rerank_deduplicates(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        refs = [
            {"candidate_id": "v:d1:0", "doc_id": "d1", "chunk_index": 0, "original_score": 0.8, "source_type": "vector"},
            {"candidate_id": "v:d1:0_dup", "doc_id": "d1", "chunk_index": 0, "original_score": 0.75, "source_type": "vector"},
            {"candidate_id": "g:d2:1", "doc_id": "d2", "chunk_index": 1, "original_score": 0.6, "source_type": "graph"},
        ]

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            mock_result = MagicMock()
            mock_result.all.return_value = []
            mock_registry.db.execute = AsyncMock(return_value=mock_result)

            with patch("app.core.config.settings.REMOTE_RERANK_ENABLED", False):
                result = await rerank_tool.ainvoke({
                    "query": "test",
                    "space_id": "space_1",
                    "candidate_refs": refs,
                    "top_k": 5,
                })

        assert result["success"] is True
        assert result["debug"]["input_count"] == 3
        assert result["debug"]["dedup_count"] == 2
        assert len(result["candidates"]) == 2
        # d1:0 should be first (score 0.8)
        assert result["candidates"][0]["doc_id"] == "d1"
        assert result["candidates"][0]["chunk_index"] == 0

    @pytest.mark.asyncio
    async def test_rerank_remote_service_success(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        refs = [
            {"candidate_id": "v:d1:0", "doc_id": "d1", "chunk_index": 0, "original_score": 0.6, "source_type": "vector"},
            {"candidate_id": "g:d2:1", "doc_id": "d2", "chunk_index": 1, "original_score": 0.8, "source_type": "graph"},
        ]

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            mock_chunk = MagicMock()
            mock_chunk.chunk_id = "c1"
            mock_chunk.chunk_index = 0
            mock_chunk.section_path = "S1"
            mock_chunk.content = "content1"
            mock_chunk.doc_id = "doc-1"

            mock_doc = MagicMock()
            mock_doc.doc_id = "doc-1"
            mock_doc.title = "Doc 1"

            mock_result = MagicMock()
            mock_result.all.return_value = [(mock_chunk, mock_doc)]
            mock_registry.db.execute = AsyncMock(return_value=mock_result)

            with patch("app.ai.embedding_client.rerank_documents") as mock_rerank:
                mock_rerank.return_value = {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.80},
                    ]
                }

                with patch("app.core.config.settings.REMOTE_RERANK_ENABLED", True):
                    result = await rerank_tool.ainvoke({
                        "query": "test",
                        "space_id": "space_1",
                        "candidate_refs": refs,
                        "top_k": 5,
                    })

        assert result["success"] is True
        assert result["debug"]["rerank_service"] is True
        assert result["debug"]["fallback_reason"] is None
        # index 1 (original_score 0.8) should come first with relevance_score 0.95
        assert result["candidates"][0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_rerank_fallback_on_service_error(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        refs = [
            {"candidate_id": "v:d1:0", "doc_id": "d1", "chunk_index": 0, "original_score": 0.8, "source_type": "vector"},
        ]

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            mock_result = MagicMock()
            mock_result.all.return_value = []
            mock_registry.db.execute = AsyncMock(return_value=mock_result)

            with patch("app.ai.embedding_client.rerank_documents") as mock_rerank:
                mock_rerank.side_effect = RuntimeError("Service unavailable")

                with patch("app.core.config.settings.REMOTE_RERANK_ENABLED", True):
                    result = await rerank_tool.ainvoke({
                        "query": "test",
                        "space_id": "space_1",
                        "candidate_refs": refs,
                        "top_k": 5,
                    })

        assert result["success"] is True
        assert result["debug"]["rerank_service"] is False
        assert "rerank_error" in (result["debug"]["fallback_reason"] or "")
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["score"] == 0.8

    @pytest.mark.asyncio
    async def test_rerank_hydrate_from_db(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        refs = [
            {"candidate_id": "v:d1111111-1111-1111-1111-111111111111:0", "doc_id": "d1111111-1111-1111-1111-111111111111", "chunk_index": 0, "original_score": 0.8, "source_type": "vector"},
        ]

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            mock_chunk = MagicMock()
            mock_chunk.chunk_id = "c1"
            mock_chunk.chunk_index = 0
            mock_chunk.section_path = "Section A"
            mock_chunk.content = "full content here"
            mock_chunk.doc_id = "d1111111-1111-1111-1111-111111111111"

            mock_doc = MagicMock()
            mock_doc.doc_id = "d1111111-1111-1111-1111-111111111111"
            mock_doc.title = "Doc Title"

            mock_result = MagicMock()
            mock_result.all.return_value = [(mock_chunk, mock_doc)]
            mock_registry.db.execute = AsyncMock(return_value=mock_result)

            with patch("app.core.config.settings.REMOTE_RERANK_ENABLED", False):
                result = await rerank_tool.ainvoke({
                    "query": "test",
                    "space_id": "space_1",
                    "candidate_refs": refs,
                    "top_k": 5,
                })

        assert result["success"] is True
        cand = result["candidates"][0]
        assert cand["doc_title"] == "Doc Title"
        assert cand["section_path"] == "Section A"
        assert cand["content"] == "full content here"
        assert cand["chunk_id"] == "c1"

    @pytest.mark.asyncio
    async def test_rerank_respects_top_k(self, mock_registry):
        from app.agents.tools.qa_tools import build_tools

        tools = build_tools(mock_registry)
        rerank_tool = next(t for t in tools if t.name == "rerank")

        mock_space = MagicMock()
        mock_space.id = 1

        refs = [
            {"candidate_id": f"v:d{i}:0", "doc_id": f"d{i}", "chunk_index": 0, "original_score": 0.9 - i * 0.1, "source_type": "vector"}
            for i in range(10)
        ]

        with patch("app.repositories.space_repo.SpaceRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.get_by_public_id = AsyncMock(return_value=mock_space)
            mock_repo_cls.return_value = mock_repo

            mock_result = MagicMock()
            mock_result.all.return_value = []
            mock_registry.db.execute = AsyncMock(return_value=mock_result)

            with patch("app.core.config.settings.REMOTE_RERANK_ENABLED", False):
                result = await rerank_tool.ainvoke({
                    "query": "test",
                    "space_id": "space_1",
                    "candidate_refs": refs,
                    "top_k": 3,
                })

        assert result["success"] is True
        assert len(result["candidates"]) == 3
