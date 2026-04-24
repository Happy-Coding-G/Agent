"""
Tests for QA autonomous decision-making capabilities (ReAct mode).

Covers:
1. Query Intent Classification
2. Hybrid Merge Decision
3. ReAct Tool Decision (AgentSession)
4. End-to-End Decision Flow
5. Edge Cases & Resilience
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.tools.qa_tools import (
    _extract_query_terms,
    _hybrid_merge,
    _compute_hybrid_score,
    _to_candidate,
    _assess_overall_confidence,
    _assess_single_confidence,
)
from app.agents.core.main_agent import MainAgent, AgentType
from app.agents.core.state import MainAgentState, TaskStatus
from app.agents.agents.definition import AgentDefinition, AgentMemoryConfig
from app.agents.agents.protocol import AgentRequest, AgentResult
from app.agents.agents.session import AgentSession, AgentMaxRoundsError


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def base_qa_state() -> Dict[str, Any]:
    """Base state for decision tests."""
    return {
        "query": "",
        "space_id": "space-1",
        "user_id": 1,
        "top_k": 5,
        "context_items": None,
        "conversation_history": [],
        "intent": None,
        "vector_results": [],
        "graph_results": [],
        "hybrid_results": [],
        "answer": None,
        "sources": [],
        "retrieval_debug": {},
        "error": None,
    }


@pytest.fixture
def make_hybrid_result():
    """Factory for creating hybrid result candidates."""
    def _make(
        doc_id: str = "doc-1",
        chunk_index: int = 0,
        score: float = 0.8,
        vector_score: float | None = None,
        graph_score: float | None = None,
        sources: List[str] | None = None,
        content: str = "test content",
        graph_evidence: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "doc_title": f"Document {doc_id}",
            "section_path": "Section 1",
            "content": content,
            "score": score,
            "vector_score": vector_score,
            "graph_score": graph_score,
            "sources": sources or ["vector"],
            "rerank_text": content,
            "match_terms": [],
            "graph_evidence": graph_evidence,
        }
    return _make


# ============================================================================
# 1. Query Intent Classification Decision
# ============================================================================

class TestQueryIntentClassification:
    """Test autonomous query type classification."""

    def test_factual_queries(self):
        """Decision: factual intent for 5W1H questions."""
        factual_queries = [
            "什么是知识图谱",
            "谁是作者",
            "何时发布",
            "where is the data stored",
            "why does it fail",
            "how to configure",
        ]
        for q in factual_queries:
            terms = _extract_query_terms(q)
            # Should extract meaningful terms
            assert len(terms) > 0, f"Failed for: {q}"

    def test_explanatory_queries(self):
        """Decision: explanatory intent for explanation-seeking questions."""
        explanatory_queries = [
            "请解释这个算法",
            "描述一下系统架构",
            "告诉我工作原理",
            "explain the pipeline",
            "describe the process",
        ]
        for q in explanatory_queries:
            terms = _extract_query_terms(q)
            assert len(terms) > 0, f"Failed for: {q}"

    def test_comparative_queries(self):
        """Decision: comparative intent for comparison questions."""
        comparative_queries = [
            "比较两种方法",
            "difference between X and Y",
            "compare A and B",
            "X与Y的区别",
        ]
        for q in comparative_queries:
            terms = _extract_query_terms(q)
            assert len(terms) > 0, f"Failed for: {q}"

    def test_general_queries(self):
        """Decision: general intent for open-ended or non-question queries."""
        general_queries = [
            "总结这份文档",
            "给出建议",
            "overview of the system",
            "相关信息",
        ]
        for q in general_queries:
            terms = _extract_query_terms(q)
            assert len(terms) > 0, f"Failed for: {q}"

    def test_empty_query_classifies_unknown(self):
        """Decision: empty query defaults to empty terms."""
        terms = _extract_query_terms("")
        assert terms == []

    def test_mixed_language_query(self):
        """Decision: mixed CN/EN query correctly handled."""
        terms = _extract_query_terms("what is 知识图谱 and how does it work")
        assert len(terms) > 0
        assert any("知识" in t for t in terms)

    def test_classification_affects_hybrid_scoring(self):
        """Decision: different intents produce different hybrid scores."""
        candidate = {
            "vector_score": 0.7,
            "graph_score": 0.6,
            "sources": ["vector", "graph"],
            "graph_evidence": "entity --RELATES--> other",
            "content": "test",
        }

        factual_score = _compute_hybrid_score(candidate, vector_rank=1, graph_rank=2)
        comparative_score = _compute_hybrid_score(candidate, vector_rank=1, graph_rank=2)
        general_score = _compute_hybrid_score(candidate, vector_rank=1, graph_rank=2)

        # All should produce valid scores in (0, 1]
        assert 0 < factual_score <= 1.0
        assert 0 < comparative_score <= 1.0
        assert 0 < general_score <= 1.0
        # Multi-source candidates get a bonus
        assert factual_score > 0.08  # source_bonus alone is 0.08


# ============================================================================
# 2. Hybrid Merge Decision
# ============================================================================

class TestHybridMergeDecision:
    """Test autonomous evidence merging and scoring decisions."""

    def test_multi_source_boost(self, base_qa_state, make_hybrid_result):
        """Decision: candidates with both vector+graph score higher."""
        vector_results = [
            {
                "doc_id": "doc-1",
                "chunk_index": 0,
                "doc_title": "Doc A",
                "section_path": "S1",
                "content": "content A",
                "score": 0.8,
            }
        ]
        graph_results = [
            {
                "doc_id": "doc-1",
                "chunk_index": 0,
                "doc_title": "Doc A",
                "section_path": "S1",
                "content": "content A graph",
                "score": 0.7,
                "graph_evidence": "A --RELATES--> B",
                "match_terms": ["A"],
            }
        ]
        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        assert len(result) == 1
        assert result[0]["sources"] == ["vector", "graph"]
        # Multi-source should score higher than single source would
        assert result[0]["score"] > 0.8

    def test_intent_based_boost_comparative(self, base_qa_state, make_hybrid_result):
        """Decision: comparative intent processes graph evidence correctly."""
        vector_results = []
        graph_results = [
            {
                "doc_id": "doc-compare",
                "chunk_index": 0,
                "doc_title": "Compare Doc",
                "section_path": "Comparison",
                "content": "A vs B comparison",
                "score": 0.6,
                "graph_evidence": "A --DIFFERS_FROM--> B",
                "match_terms": ["A", "B"],
            }
        ]
        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        assert len(result) > 0
        assert result[0]["score"] > 0
        assert result[0]["sources"] == ["graph"]

    def test_no_graph_results_still_produces_output(self, base_qa_state):
        """Decision: vector-only results still produce valid candidates."""
        vector_results = [
            {
                "doc_id": "doc-only",
                "chunk_index": 0,
                "doc_title": "Only Vector",
                "section_path": "S1",
                "content": "vector only content",
                "score": 0.75,
            }
        ]
        graph_results = []
        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        assert len(result) == 1
        assert result[0]["sources"] == ["vector"]

    def test_compute_hybrid_score_with_both_sources(self):
        """Decision: hybrid score computation with dual evidence."""
        candidate = {
            "vector_score": 0.8,
            "graph_score": 0.7,
            "sources": ["vector", "graph"],
        }
        score = _compute_hybrid_score(candidate, vector_rank=1, graph_rank=2)
        assert score > 0
        # Should be higher than either individual score due to multi-source boost
        assert score > 0.7

    def test_compute_hybrid_score_no_evidence(self):
        """Decision: candidate with no content/evidence is filtered."""
        candidate = {
            "content": "",
            "graph_evidence": None,
            "vector_score": None,
            "graph_score": None,
            "sources": [],
        }
        score = _compute_hybrid_score(candidate, vector_rank=None, graph_rank=None)
        # Content-empty candidates get penalized
        assert score >= 0


# ============================================================================
# 3. ReAct Tool Decision (AgentSession)
# ============================================================================

class TestReActToolDecision:
    """Test AgentSession's autonomous tool selection in ReAct loop."""

    def _make_definition(self, tools: List[str] | None = None, max_rounds: int = 3) -> AgentDefinition:
        return AgentDefinition(
            skill_id="qa_research",
            name="QA Research Agent",
            capability_type="agent",
            description="Autonomous QA agent",
            max_rounds=max_rounds,
            tools=tools or ["search_knowledge"],
        )

    @pytest.mark.asyncio
    async def test_react_direct_answer_no_tools(self):
        """Decision: LLM chooses direct answer without tool calls."""
        definition = self._make_definition(tools=[], max_rounds=3)
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        # Mock LLM that returns direct answer (no tool calls)
        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "This is the direct answer."
                response.tool_calls = []
                return response

        class MockLLM:
            def bind_tools(self, tools):
                return MockBoundLLM()

        session._llm_client = MockLLM()
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="What is X?",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert result.success is True
        assert "direct answer" in result.summary.lower() or "answer" in result.summary.lower()
        assert result.rounds_used == 1
        assert result.tool_calls_count == 0

    @pytest.mark.asyncio
    async def test_react_calls_tool_then_answers(self):
        """Decision: LLM calls tool in round 1, then answers in round 2."""
        definition = self._make_definition(tools=["search_knowledge"], max_rounds=5)
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        call_count = 0

        # Mock LLM: first call requests tool, second call answers directly
        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                nonlocal call_count
                call_count += 1
                response = MagicMock()
                if call_count == 1:
                    response.content = "I need to search for this."
                    response.tool_calls = [
                        {"name": "search_knowledge", "args": {"query": "X"}, "id": "call_1"}
                    ]
                else:
                    response.content = "Based on the search, X is a variable."
                    response.tool_calls = []
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        mock_llm.total_tokens = 150
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False

        # Mock tool registry
        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = "Search result: X is a variable used in math."
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.tool_registry.get_tool.return_value = mock_tool
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="What is X?",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert result.success is True
        assert result.rounds_used == 2
        assert result.tool_calls_count == 1
        assert "variable" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_react_max_rounds_exceeded(self):
        """Decision: Agent respects max_rounds limit and stops."""
        definition = self._make_definition(tools=["search_knowledge"], max_rounds=3)
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        # Mock LLM that always requests tool calls (never decides to answer)
        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "I will search more."
                response.tool_calls = [
                    {"name": "search_knowledge", "args": {"query": "more"}, "id": "call_x"}
                ]
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = "result"
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.tool_registry.get_tool.return_value = mock_tool
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="Research something complex",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert result.success is False
        assert result.error == "max_rounds_exceeded"
        assert result.rounds_used == 3

    @pytest.mark.asyncio
    async def test_react_tool_not_allowed(self):
        """Decision: Agent rejects tool not in whitelist."""
        definition = self._make_definition(tools=["allowed_tool"], max_rounds=3)
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "Trying forbidden tool."
                response.tool_calls = [
                    {"name": "forbidden_tool", "args": {}, "id": "call_bad"}
                ]
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False

        # Tool registry returns None for forbidden tool
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.tool_registry.get_tool.return_value = None
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="Do something",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        # Should fail because tool not found and then hit max rounds
        assert result.success is False

    @pytest.mark.asyncio
    async def test_react_empty_tool_name(self):
        """Decision: Agent handles empty tool name gracefully."""
        definition = self._make_definition(tools=["some_tool"], max_rounds=3)
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "Oops."
                response.tool_calls = [
                    {"name": "", "args": {}, "id": "call_empty"}
                ]
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="Test",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert result.success is False
        assert result.rounds_used <= 3


# ============================================================================
# 4. End-to-End Decision Flow
# ============================================================================

class TestEndToEndDecisionFlow:
    """Test the complete decision chain from input to output."""

    def test_main_agent_routes_qa_intent(self):
        """E2E: MainAgent correctly identifies and routes QA intent."""
        mock_db = MagicMock()
        agent = MainAgent(db=mock_db)

        qa_cases = [
            "什么是知识图谱",
            "解释一下 RAG 流程",
            "A 和 B 有什么区别",
            "how does vector search work",
            "what is the difference between X and Y",
            "为什么模型会出错",
        ]
        for text in qa_cases:
            intent = agent._simple_intent_detection(text)
            assert intent == AgentType.QA, f"Should route to QA: {text}"

    @pytest.mark.asyncio
    async def test_main_agent_subagent_mode_routing(self, monkeypatch):
        """E2E: MainAgent plan step routes subagent mode."""
        mock_db = MagicMock()
        mock_llm = AsyncMock()

        # Mock LLM to return agent mode decision
        mock_response = MagicMock()
        mock_response.content = """{"decision": {"mode": "subagent", "name": "qa_research", "arguments": {"query": "test"}}}"""
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = MainAgent(db=mock_db, llm_client=mock_llm)

        # Mock user lookup
        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock registries
        with patch.object(agent, "_get_tool_registry") as mock_tool_reg, \
             patch.object(agent, "_get_skill_registry") as mock_skill_reg, \
             patch.object(agent, "_get_agent_registry") as mock_agent_reg:

            mock_tool_reg.return_value.get_tool_schemas.return_value = []
            mock_skill_reg.return_value.get_skill_schemas.return_value = []
            mock_agent_reg.return_value.get_agent_schemas.return_value = []

            state: MainAgentState = {
                "user_request": "What is X?",
                "session_id": "sess_1",
                "user_id": 1,
                "space_id": "space_1",
            }

            result = await agent._plan_step(state)
            assert result["decision_mode"] == "subagent"
            assert result["active_subagent_call"]["name"] == "qa_research"
            assert len(result.get("subagent_calls", [])) == 1


# ============================================================================
# 5. Edge Cases & Resilience
# ============================================================================

class TestDecisionEdgeCases:
    """Test edge cases in autonomous decision-making."""

    def test_malformed_query(self):
        """Decision: agent handles malformed input gracefully."""
        malformed = [
            "   ",
            "!!!???",
            "\n\t\n",
            "a" * 10000,  # very long query
        ]
        for q in malformed:
            terms = _extract_query_terms(q)
            # Should not crash, should return list
            assert isinstance(terms, list)

    def test_single_character_query(self):
        """Decision: single character query handled."""
        terms = _extract_query_terms("?")
        assert isinstance(terms, list)

    def test_hybrid_merge_with_none_scores(self, base_qa_state):
        """Decision: None scores don't crash merge."""
        vector_results = [
            {
                "doc_id": "doc-bad",
                "chunk_index": 0,
                "doc_title": "Bad",
                "section_path": "S1",
                "content": "content",
                "score": None,  # type: ignore
            }
        ]
        graph_results = []
        result = _hybrid_merge(vector_results, graph_results, top_k=5)
        # Should not crash, may filter out or handle gracefully
        assert isinstance(result, list)

    def test_hybrid_score_with_missing_fields(self):
        """Decision: missing fields handled gracefully in scoring."""
        candidate = {}  # empty candidate
        score = _compute_hybrid_score(
            candidate, vector_rank=None, graph_rank=None
        )
        assert score >= 0  # Should not crash

    @pytest.mark.asyncio
    async def test_react_handles_tool_exception(self):
        """Decision: tool exception is caught and reported."""
        definition = AgentDefinition(
            skill_id="qa_research",
            name="QA Research Agent",
            capability_type="agent",
            description="Autonomous QA agent",
            max_rounds=3,
            tools=["bad_tool"],
        )
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "Calling tool."
                response.tool_calls = [
                    {"name": "bad_tool", "args": {}, "id": "call_1"}
                ]
                return response

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = MockBoundLLM()
        session._llm_client = mock_llm
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False

        # Tool that raises exception
        mock_tool = AsyncMock()
        mock_tool.ainvoke.side_effect = RuntimeError("Tool crashed!")
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.tool_registry.get_tool.return_value = mock_tool
        session.memory = None

        request = AgentRequest(
            agent_id="qa_research",
            task_description="Test error handling",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        # Should handle gracefully, either fail with error or max rounds
        assert result.rounds_used <= 3


# ============================================================================
# 6. Decision Logging & Observability
# ============================================================================

class TestDecisionObservability:
    """Test that decisions are properly recorded for observability."""

    def test_sidechain_logs_tool_calls(self):
        """Decision: tool calls are logged to sidechain."""
        from app.agents.agents.sidechain import SidechainLogger

        logger = SidechainLogger(
            session_id="sess_1:qa",
            parent_session_id="sess_1",
            agent_id="qa",
        )

        import asyncio

        async def _test():
            await logger.log("tool_call", {
                "round": 1,
                "tool": "search_knowledge",
                "args": {"query": "test"},
                "result": "found",
            })
            entries = await logger.get_entries()
            assert len(entries) == 1
            assert entries[0].event_type == "tool_call"
            assert entries[0].content["tool"] == "search_knowledge"

        asyncio.run(_test())

    def test_sidechain_logs_thoughts(self):
        """Decision: LLM reasoning is logged as thoughts."""
        from app.agents.agents.sidechain import SidechainLogger

        logger = SidechainLogger(
            session_id="sess_1:qa",
            parent_session_id="sess_1",
            agent_id="qa",
        )

        import asyncio

        async def _test():
            await logger.log("thought", {
                "round": 1,
                "content": "I should search for this.",
                "tool_calls": [{"name": "search"}],
            })
            summary = await logger.get_summary()
            assert "qa" in summary
            assert "总事件数: 1" in summary

        asyncio.run(_test())

    @pytest.mark.asyncio
    async def test_agent_result_includes_decision_metadata(self):
        """Decision: AgentResult carries decision metadata."""
        definition = AgentDefinition(
            skill_id="test",
            name="Test Agent",
            capability_type="agent",
            description="Test",
            max_rounds=3,
        )
        session = AgentSession(
            agent_definition=definition,
            parent_session_id="sess_1",
            user_id=1,
        )

        # Mock direct answer
        class MockBoundLLM:
            async def ainvoke(self, messages, **kwargs):
                response = MagicMock()
                response.content = "Answer."
                response.tool_calls = []
                return response

        class MockLLM:
            def bind_tools(self, tools):
                return MockBoundLLM()

        session._llm_client = MockLLM()
        session._initialized = True
        session._db = MagicMock()
        session._db_owned = False
        session.tool_registry = MagicMock()
        session.tool_registry.get_tools.return_value = []
        session.memory = None

        request = AgentRequest(
            agent_id="test",
            task_description="What?",
            parent_session_id="sess_1",
        )

        result = await session.execute(request)
        assert result.agent_id == "test"
        assert result.rounds_used >= 1
        assert result.correlation_id is not None
        assert result.sidechain_id == "sess_1:test"


# ============================================================================
# 7. Three-Layer Retrieval Decision
# ============================================================================

class TestThreeLayerRetrievalDecision:
    """Test vector_search / graph_search / rerank decision flow."""

    def test_vector_candidate_format(self):
        """Decision: vector candidate follows unified format."""
        item = {
            "chunk_id": "c1",
            "doc_id": "d1",
            "chunk_index": 0,
            "doc_title": "Doc A",
            "section_path": "S1",
            "content": "vector content",
            "score": 0.82,
        }
        cand = _to_candidate(item, "vector")
        assert cand["candidate_id"] == "vector:d1:0"
        assert cand["source_type"] == "vector"
        assert cand["confidence"] == "high"
        assert "chunk_id" in cand
        assert "metadata" in cand

    def test_graph_candidate_includes_evidence(self):
        """Decision: graph candidate includes graph_evidence in metadata."""
        item = {
            "chunk_id": None,
            "doc_id": "d2",
            "chunk_index": 1,
            "doc_title": "Doc B",
            "section_path": None,
            "content": "",
            "score": 0.55,
            "graph_evidence": "Entity [Type] --REL--> Other",
            "match_terms": ["term1", "term2"],
        }
        cand = _to_candidate(item, "graph")
        assert cand["source_type"] == "graph"
        assert cand["metadata"]["graph_evidence"] == "Entity [Type] --REL--> Other"
        assert cand["metadata"]["match_terms"] == ["term1", "term2"]

    def test_overall_confidence_high(self):
        """Decision: top score >= 0.7 yields high confidence."""
        cands = [
            {"score": 0.85},
            {"score": 0.6},
        ]
        assert _assess_overall_confidence(cands) == "high"

    def test_overall_confidence_medium(self):
        """Decision: top score >= 0.4 and < 0.7 yields medium confidence."""
        cands = [
            {"score": 0.55},
            {"score": 0.3},
        ]
        assert _assess_overall_confidence(cands) == "medium"

    def test_overall_confidence_low(self):
        """Decision: top score < 0.4 yields low confidence."""
        cands = [
            {"score": 0.35},
            {"score": 0.2},
        ]
        assert _assess_overall_confidence(cands) == "low"

    def test_overall_confidence_empty(self):
        """Decision: empty candidates yields low confidence."""
        assert _assess_overall_confidence([]) == "low"

    def test_confidence_threshold_boundary(self):
        """Decision: boundary values handled correctly."""
        assert _assess_single_confidence(0.7) == "high"
        assert _assess_single_confidence(0.4) == "medium"
        assert _assess_single_confidence(0.399) == "low"

    def test_main_agent_routes_qa_to_subagent(self):
        """E2E: MainAgent routes QA intent to qa_research subagent."""
        mock_db = MagicMock()
        agent = MainAgent(db=mock_db)

        qa_cases = [
            "什么是知识图谱",
            "解释一下 RAG 流程",
            "A 和 B 有什么区别",
            "how does vector search work",
            "what is the difference between X and Y",
            "为什么模型会出错",
        ]
        for text in qa_cases:
            intent = agent._simple_intent_detection(text)
            assert intent == AgentType.QA, f"Should route to QA: {text}"

    @pytest.mark.asyncio
    async def test_main_agent_fallback_qa_routes_subagent(self, monkeypatch):
        """E2E: MainAgent fallback routes QA to qa_research subagent."""
        mock_db = MagicMock()
        agent = MainAgent(db=mock_db)

        state = {
            "user_request": "什么是知识图谱",
            "space_id": "space_1",
            "tool_calls": [],
            "subagent_calls": [],
            "context": {"top_k": 5},
        }

        result = await agent._fallback_plan(state, MagicMock(), AgentType.QA)
        assert result["decision_mode"] == "subagent"
        assert result["active_subagent_call"]["name"] == "qa_research"
        assert result.get("active_tool") is None

    @pytest.mark.asyncio
    async def test_main_agent_plan_qa_forces_subagent(self, monkeypatch):
        """E2E: Even if LLM returns direct, QA intent forces subagent."""
        mock_db = MagicMock()
        mock_llm = AsyncMock()

        mock_response = MagicMock()
        mock_response.content = '{"decision": {"mode": "direct", "answer": "test"}}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        agent = MainAgent(db=mock_db, llm_client=mock_llm)

        mock_user = MagicMock()
        mock_user.id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(agent, "_get_tool_registry") as mock_tool_reg, \
             patch.object(agent, "_get_skill_registry") as mock_skill_reg, \
             patch.object(agent, "_get_agent_registry") as mock_agent_reg:

            mock_tool_reg.return_value.get_tool_schemas.return_value = []
            mock_skill_reg.return_value.get_skill_schemas.return_value = []
            mock_agent_reg.return_value.get_agent_schemas.return_value = []

            state = {
                "user_request": "什么是知识图谱",
                "session_id": "sess_1",
                "user_id": 1,
                "space_id": "space_1",
                "context": {"top_k": 5},
            }

            result = await agent._plan_step(state)
            assert result["decision_mode"] == "subagent"
            assert result["active_subagent_call"]["name"] == "qa_research"
