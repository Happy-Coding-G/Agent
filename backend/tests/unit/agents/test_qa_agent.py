"""QAAgent retrieval optimization tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.subagents.qa_agent import QAAgent


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def agent(mock_db_session):
    return QAAgent(mock_db_session)


class TestQAAgentHelpers:
    def test_extract_query_terms_supports_chinese_and_english(self, agent):
        terms = agent._extract_query_terms("请解释知识图谱检索流程 retrieval pipeline")

        assert "retrieval" in terms
        assert any(term in terms for term in ["知识图谱", "图谱检索", "检索流程"])

    @pytest.mark.asyncio
    async def test_hybrid_merge_prefers_multi_source_candidates(self, agent):
        state = {
            "query": "知识图谱是什么",
            "space_id": "space-1",
            "user_id": 1,
            "top_k": 5,
            "context_items": None,
            "intent": "factual",
            "vector_results": [
                {
                    "chunk_id": "chunk-1",
                    "doc_id": "doc-1",
                    "chunk_index": 0,
                    "doc_title": "文档一",
                    "section_path": "概述",
                    "content": "这是文档一的正文内容。",
                    "score": 0.82,
                },
                {
                    "chunk_id": "chunk-2",
                    "doc_id": "doc-2",
                    "chunk_index": 1,
                    "doc_title": "文档二",
                    "section_path": "背景",
                    "content": "这是文档二的正文内容。",
                    "score": 0.79,
                },
            ],
            "graph_results": [
                {
                    "chunk_id": "chunk-1",
                    "doc_id": "doc-1",
                    "chunk_index": 0,
                    "doc_title": "文档一",
                    "section_path": "概述",
                    "content": "这是文档一的正文内容。",
                    "score": 0.76,
                    "graph_evidence": "知识图谱 [Entity] --RELATES--> 检索 | 命中词: 知识图谱",
                    "match_terms": ["知识图谱"],
                }
            ],
            "hybrid_results": [],
            "answer": None,
            "sources": [],
            "retrieval_debug": {},
            "error": None,
        }

        result = await agent._hybrid_merge_node(state)
        best = result["hybrid_results"][0]

        assert best["doc_id"] == "doc-1"
        assert best["sources"] == ["vector", "graph"]
        assert best["score"] > result["hybrid_results"][1]["score"]
        assert "图谱证据" in best["rerank_text"]

    @pytest.mark.asyncio
    async def test_rerank_disabled_still_limits_final_results(self, agent, monkeypatch):
        monkeypatch.setattr("app.agents.subagents.qa_agent.settings.REMOTE_RERANK_ENABLED", False)

        state = {
            "query": "test query",
            "space_id": "space-1",
            "user_id": 1,
            "top_k": 2,
            "context_items": None,
            "intent": "general",
            "vector_results": [],
            "graph_results": [],
            "hybrid_results": [
                {"doc_id": "doc-1", "chunk_index": 0, "doc_title": "A", "content": "A", "score": 0.9, "sources": ["vector"]},
                {"doc_id": "doc-2", "chunk_index": 0, "doc_title": "B", "content": "B", "score": 0.8, "sources": ["vector"]},
                {"doc_id": "doc-3", "chunk_index": 0, "doc_title": "C", "content": "C", "score": 0.7, "sources": ["graph"]},
            ],
            "answer": None,
            "sources": [],
            "retrieval_debug": {},
            "error": None,
        }

        result = await agent._rerank_hybrid_node(state)

        assert len(result["hybrid_results"]) == 2
        assert [item["doc_id"] for item in result["hybrid_results"]] == ["doc-1", "doc-2"]