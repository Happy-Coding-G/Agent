"""QA Tools tests - extracted from legacy QAAgent."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.tools.qa_tools import (
    _extract_query_terms,
    _hybrid_merge,
    _compute_hybrid_score,
    _normalize_score,
    _build_context_text,
    _build_qa_prompt,
)
from app.agents.core.main_agent import MainAgent, AgentType


class TestQAHelperFunctions:
    def test_extract_query_terms_supports_chinese_and_english(self):
        terms = _extract_query_terms("请解释知识图谱检索流程 retrieval pipeline")
        assert "retrieval" in terms
        assert any(term in terms for term in ["知识图谱", "图谱检索", "检索流程"])

    def test_normalize_score_bounds(self):
        assert _normalize_score(0.5) == 0.5
        assert _normalize_score(1.5) == 1.0
        assert _normalize_score(-0.1) == 0.0
        assert _normalize_score("invalid") == 0.0
        assert _normalize_score(float("nan")) == 0.0

    def test_build_context_text_empty(self):
        assert "无可用上下文" in _build_context_text([])

    def test_build_context_text_with_items(self):
        items = [
            {"doc_title": "Doc1", "section_path": "S1", "score": 0.8, "content": "hello world"}
        ]
        text = _build_context_text(items)
        assert "Doc1" in text
        assert "hello world" in text

    def test_build_qa_prompt_basic(self):
        prompt = _build_qa_prompt("What is X?", "Context here", None)
        assert "What is X?" in prompt
        assert "Context here" in prompt

    def test_build_qa_prompt_with_history(self):
        history = [{"query": "Q1", "answer": "A1"}]
        prompt = _build_qa_prompt("Q2?", "Ctx", history)
        assert "Q1" in prompt
        assert "A1" in prompt


class TestHybridMerge:
    def test_hybrid_merge_prefers_multi_source_candidates(self):
        vector_results = [
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
        ]
        graph_results = [
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
        ]

        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        best = result[0]
        assert best["doc_id"] == "doc-1"
        assert "vector" in best["sources"] and "graph" in best["sources"]
        assert best["score"] > result[1]["score"]

    def test_hybrid_merge_vector_only(self):
        vector_results = [
            {"doc_id": "doc-1", "chunk_index": 0, "doc_title": "A", "content": "A", "score": 0.9}
        ]
        graph_results = []
        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        assert len(result) == 1
        assert result[0]["sources"] == ["vector"]

    def test_compute_hybrid_score_with_both_sources(self):
        candidate = {
            "vector_score": 0.8,
            "graph_score": 0.7,
            "sources": ["vector", "graph"],
        }
        score = _compute_hybrid_score(candidate, vector_rank=1, graph_rank=2)
        assert score > 0
        assert score > 0.7

    def test_compute_hybrid_score_no_evidence(self):
        candidate = {
            "content": "",
            "graph_evidence": None,
            "vector_score": None,
            "graph_score": None,
            "sources": [],
        }
        score = _compute_hybrid_score(candidate, vector_rank=None, graph_rank=None)
        assert score >= 0


class TestMainAgentIntentRouting:
    def test_natural_questions_route_to_qa(self):
        """回归测试：常见自然问法应被正确路由到 QA。"""
        agent = MainAgent(db=MagicMock())
        cases = [
            ("请解释 DistMult", AgentType.QA),
            ("RotatE 是什么", AgentType.QA),
            ("DistMult 和 ComplEx 的区别", AgentType.QA),
            ("how does graph search work", AgentType.QA),
            ("what is the difference between A and B", AgentType.QA),
            ("查找文件", AgentType.FILE_QUERY),
            ("审查文档", AgentType.REVIEW),
            ("你好", AgentType.CHAT),
        ]
        for text, expected in cases:
            assert agent._simple_intent_detection(text) == expected, f"Failed for: {text}"

    def test_writing_and_summarizing_routes_to_chat(self):
        """回归测试：写作/总结类请求不应被误判为 QA。"""
        agent = MainAgent(db=MagicMock())
        cases = [
            ("帮我总结今天的工作", AgentType.CHAT),
            ("写一个周报开头", AgentType.CHAT),
            ("翻译这段文字", AgentType.CHAT),
            ("生成一份报告", AgentType.CHAT),
        ]
        for text, expected in cases:
            assert agent._simple_intent_detection(text) == expected, f"Failed for: {text}"
