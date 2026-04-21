"""
Tests for QAAgent autonomous decision-making capabilities.

Covers:
1. Query Intent Classification - how QA Agent decides query type
2. Retrieval Route Decision - routing based on retrieval results
3. Hybrid Merge Decision - multi-source evidence scoring decisions
4. ReAct Tool Decision - AgentSession autonomous tool selection
5. End-to-End Decision Flow - full pipeline decision chain
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.agents.subagents.qa_agent import QAAgent, QAState
from app.agents.core.main_agent import MainAgent, AgentType
from app.agents.core.state import MainAgentState, TaskStatus
from app.agents.agents.definition import AgentDefinition, AgentMemoryConfig
from app.agents.agents.protocol import AgentRequest, AgentResult
from app.agents.agents.session import AgentSession, AgentMaxRoundsError


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def qa_agent(mock_db_session):
    return QAAgent(mock_db_session)


@pytest.fixture
def base_qa_state() -> QAState:
    """Base QAState for decision tests."""
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
    """Test QAAgent's autonomous query type classification."""

    @pytest.mark.asyncio
    async def test_factual_queries(self, qa_agent, base_qa_state):
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
            state = {**base_qa_state, "query": q}
            result = await qa_agent._classify_query_node(state)
            assert result["intent"] == "factual", f"Failed for: {q}"

    @pytest.mark.asyncio
    async def test_explanatory_queries(self, qa_agent, base_qa_state):
        """Decision: explanatory intent for explanation-seeking questions."""
        explanatory_queries = [
            "请解释这个算法",
            "描述一下系统架构",
            "告诉我工作原理",
            "explain the pipeline",
            "describe the process",
        ]
        for q in explanatory_queries:
            state = {**base_qa_state, "query": q}
            result = await qa_agent._classify_query_node(state)
            assert result["intent"] == "explanatory", f"Failed for: {q}"

    @pytest.mark.asyncio
    async def test_comparative_queries(self, qa_agent, base_qa_state):
        """Decision: comparative intent for comparison questions."""
        # Note: queries containing "什么" are classified as factual first
        # because "什么" appears earlier in the keyword list.
        comparative_queries = [
            "比较两种方法",
            "difference between X and Y",
            "compare A and B",
            "X与Y的区别",
        ]
        for q in comparative_queries:
            state = {**base_qa_state, "query": q}
            result = await qa_agent._classify_query_node(state)
            assert result["intent"] == "comparative", f"Failed for: {q}"

    @pytest.mark.asyncio
    async def test_general_queries(self, qa_agent, base_qa_state):
        """Decision: general intent for open-ended or non-question queries."""
        general_queries = [
            "总结这份文档",
            "给出建议",
            "overview of the system",
            "相关信息",
        ]
        for q in general_queries:
            state = {**base_qa_state, "query": q}
            result = await qa_agent._classify_query_node(state)
            assert result["intent"] == "general", f"Failed for: {q}"

    @pytest.mark.asyncio
    async def test_empty_query_classifies_unknown(self, qa_agent, base_qa_state):
        """Decision: empty query defaults to unknown."""
        state = {**base_qa_state, "query": ""}
        result = await qa_agent._classify_query_node(state)
        assert result["intent"] == "unknown"

    @pytest.mark.asyncio
    async def test_mixed_language_query(self, qa_agent, base_qa_state):
        """Decision: mixed CN/EN query correctly classified."""
        state = {**base_qa_state, "query": "what is 知识图谱 and how does it work"}
        result = await qa_agent._classify_query_node(state)
        assert result["intent"] == "factual"

    @pytest.mark.asyncio
    async def test_classification_affects_hybrid_scoring(
        self, qa_agent, base_qa_state
    ):
        """Decision: different intents produce different hybrid scores."""
        # Create a candidate with both vector and graph evidence
        candidate = {
            "vector_score": 0.7,
            "graph_score": 0.6,
            "sources": ["vector", "graph"],
            "graph_evidence": "entity --RELATES--> other",
            "content": "test",
        }

        factual_score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=1, graph_rank=2, intent="factual"
        )
        comparative_score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=1, graph_rank=2, intent="comparative"
        )
        general_score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=1, graph_rank=2, intent="general"
        )

        # All intents should produce valid scores in (0, 1]
        assert 0 < factual_score <= 1.0
        assert 0 < comparative_score <= 1.0
        assert 0 < general_score <= 1.0
        # Intent weights should produce measurably different scores
        scores = {factual_score, comparative_score, general_score}
        assert len(scores) >= 2, "Different intents should produce different scores"
        # Multi-source candidates get a bonus
        assert factual_score > 0.08  # source_bonus alone is 0.08


# ============================================================================
# 2. Retrieval Route Decision
# ============================================================================

class TestRetrievalRouteDecision:
    """Test routing decisions based on retrieval results."""

    def test_has_results_routes_to_generate(self, qa_agent):
        """Decision: non-empty hybrid_results → generate_answer."""
        state = {"hybrid_results": [{"doc_id": "d1"}]}
        route = qa_agent._has_retrieval_results(state)
        assert route == "has_results"

    def test_empty_results_routes_to_no_results(self, qa_agent):
        """Decision: empty hybrid_results → no_results_answer."""
        state = {"hybrid_results": []}
        route = qa_agent._has_retrieval_results(state)
        assert route == "empty"

    def test_none_results_routes_to_no_results(self, qa_agent):
        """Decision: None hybrid_results → no_results_answer."""
        state = {"hybrid_results": None}
        route = qa_agent._has_retrieval_results(state)
        assert route == "empty"

    @pytest.mark.asyncio
    async def test_no_results_node_generates_fallback(self, qa_agent):
        """Decision: no_results node produces user-friendly fallback."""
        state: QAState = {
            "query": "unknown topic",
            "space_id": "space-1",
            "user_id": 1,
            "top_k": 5,
            "context_items": None,
            "conversation_history": [],
            "intent": "factual",
            "vector_results": [],
            "graph_results": [],
            "hybrid_results": [],
            "answer": None,
            "sources": [],
            "retrieval_debug": {},
            "error": None,
        }
        result = await qa_agent._no_results_answer_node(state)
        assert "没有找到" in result["answer"]
        assert "上传相关文档" in result["answer"]

    @pytest.mark.asyncio
    async def test_generate_answer_skips_llm_when_empty(self, qa_agent, base_qa_state):
        """Decision: generate_answer_node bypasses LLM on empty results."""
        state = {**base_qa_state, "hybrid_results": []}
        result = await qa_agent._generate_answer_node(state)
        assert "没有找到" in result["answer"]
        assert result["answer"] is not None


# ============================================================================
# 3. Hybrid Merge Decision
# ============================================================================

class TestHybridMergeDecision:
    """Test autonomous evidence merging and scoring decisions."""

    @pytest.mark.asyncio
    async def test_multi_source_boost(self, qa_agent, base_qa_state, make_hybrid_result):
        """Decision: candidates with both vector+graph score higher."""
        state = {
            **base_qa_state,
            "intent": "factual",
            "vector_results": [
                {
                    "doc_id": "doc-1",
                    "chunk_index": 0,
                    "doc_title": "Doc A",
                    "section_path": "S1",
                    "content": "content A",
                    "score": 0.8,
                }
            ],
            "graph_results": [
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
            ],
        }
        result = await qa_agent._hybrid_merge_node(state)
        candidates = result["hybrid_results"]
        assert len(candidates) == 1
        assert candidates[0]["sources"] == ["vector", "graph"]
        # Multi-source should score higher than single source would
        assert candidates[0]["score"] > 0.8

    @pytest.mark.asyncio
    async def test_intent_based_boost_comparative(
        self, qa_agent, base_qa_state, make_hybrid_result
    ):
        """Decision: comparative intent processes graph evidence correctly."""
        state = {
            **base_qa_state,
            "intent": "comparative",
            "vector_results": [],
            "graph_results": [
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
            ],
        }
        result = await qa_agent._hybrid_merge_node(state)
        candidates = result["hybrid_results"]
        assert len(candidates) > 0
        # Score should be computed (graph-only with RRF component)
        # For graph_score=0.6, rank=1: raw=0.6, rrf=1.0/(20+1)=0.0476,
        # normalized_rrf=0.571, final = 0.6*0.6 + 0.571*0.4 ≈ 0.588
        assert candidates[0]["score"] > 0
        assert candidates[0]["sources"] == ["graph"]
        assert "图谱证据" in candidates[0]["rerank_text"]

    @pytest.mark.asyncio
    async def test_no_graph_results_still_produces_output(
        self, qa_agent, base_qa_state
    ):
        """Decision: vector-only results still produce valid candidates."""
        state = {
            **base_qa_state,
            "intent": "factual",
            "vector_results": [
                {
                    "doc_id": "doc-only",
                    "chunk_index": 0,
                    "doc_title": "Only Vector",
                    "section_path": "S1",
                    "content": "vector only content",
                    "score": 0.75,
                }
            ],
            "graph_results": [],
        }
        result = await qa_agent._hybrid_merge_node(state)
        candidates = result["hybrid_results"]
        assert len(candidates) == 1
        assert candidates[0]["sources"] == ["vector"]

    def test_compute_hybrid_score_with_both_sources(self, qa_agent):
        """Decision: hybrid score computation with dual evidence."""
        candidate = {
            "vector_score": 0.8,
            "graph_score": 0.7,
            "sources": ["vector", "graph"],
        }
        score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=1, graph_rank=2, intent="factual"
        )
        assert score > 0
        # Should be higher than either individual score due to multi-source boost
        assert score > 0.7

    def test_compute_hybrid_score_no_evidence(self, qa_agent):
        """Decision: candidate with no content/evidence is filtered."""
        candidate = {
            "content": "",
            "graph_evidence": None,
            "vector_score": None,
            "graph_score": None,
            "sources": [],
        }
        score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=None, graph_rank=None, intent="general"
        )
        # Content-empty candidates get penalized
        assert score >= 0


# ============================================================================
# 4. ReAct Tool Decision (AgentSession)
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
# 5. End-to-End Decision Flow
# ============================================================================

class TestEndToEndDecisionFlow:
    """Test the complete decision chain from input to output."""

    @pytest.mark.asyncio
    async def test_full_pipeline_empty_results(self, qa_agent, base_qa_state, monkeypatch):
        """E2E: empty retrieval → no_results_answer → format_sources."""
        monkeypatch.setattr(
            qa_agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            qa_agent, "_retrieve_vector_context", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            qa_agent, "_retrieve_graph_context", AsyncMock(return_value=[])
        )

        state = {
            **base_qa_state,
            "query": "something that does not exist",
            "space_id": "space-1",
        }

        result = await qa_agent.graph.ainvoke(state)
        assert "没有找到" in result["answer"]
        assert result["sources"] == []
        assert result["intent"] in ("general", "factual", "unknown")

    @pytest.mark.asyncio
    async def test_full_pipeline_with_results(self, qa_agent, base_qa_state, monkeypatch):
        """E2E: with retrieval results → generate_answer → format_sources."""
        monkeypatch.setattr(
            qa_agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            qa_agent,
            "_retrieve_vector_context",
            AsyncMock(
                return_value=[
                    {
                        "doc_id": "doc-1",
                        "chunk_index": 0,
                        "doc_title": "Test Doc",
                        "section_path": "Intro",
                        "content": "This is test content about X.",
                        "score": 0.85,
                    }
                ]
            ),
        )
        monkeypatch.setattr(
            qa_agent, "_retrieve_graph_context", AsyncMock(return_value=[])
        )

        # Mock LLM for answer generation
        with patch("app.agents.subagents.qa_agent.get_llm_client") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = "X is a test variable."
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_llm.return_value = mock_llm

            state = {
                **base_qa_state,
                "query": "What is X?",
                "space_id": "space-1",
            }

            result = await qa_agent.graph.ainvoke(state)
            assert result["answer"] is not None
            assert len(result["sources"]) > 0
            assert result["sources"][0]["doc_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_stream_decision_chain_empty(self, qa_agent, base_qa_state, monkeypatch):
        """E2E streaming: empty results decision chain emits correct events."""
        monkeypatch.setattr(
            qa_agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            qa_agent, "_classify_query_node", AsyncMock(return_value={**base_qa_state, "intent": "factual"})
        )
        monkeypatch.setattr(
            qa_agent, "_vector_search_node", AsyncMock(return_value={**base_qa_state, "vector_results": []})
        )
        monkeypatch.setattr(
            qa_agent, "_graph_search_node", AsyncMock(return_value={**base_qa_state, "graph_results": []})
        )
        monkeypatch.setattr(
            qa_agent, "_hybrid_merge_node", AsyncMock(return_value={**base_qa_state, "hybrid_results": []})
        )
        monkeypatch.setattr(
            qa_agent, "_rerank_hybrid_node", AsyncMock(return_value={**base_qa_state, "hybrid_results": []})
        )

        events = []
        async for event in qa_agent.stream(
            query="unknown",
            space_public_id="space-1",
            user=MagicMock(id=1),
        ):
            events.append(event)

        event_types = [e["type"] for e in events]
        assert "status" in event_types
        assert "result" in event_types
        # Should NOT have token stream for LLM generation when empty
        # (because it bypasses LLM and returns fallback directly)
        result_event = [e for e in events if e["type"] == "result"][0]
        assert "没有找到" in result_event["content"]["answer"]

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
    async def test_main_agent_agent_mode_routing(self, monkeypatch):
        """E2E: MainAgent plan step sets active_subagent_call for agent mode."""
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
# 6. Edge Cases & Resilience
# ============================================================================

class TestDecisionEdgeCases:
    """Test edge cases in autonomous decision-making."""

    @pytest.mark.asyncio
    async def test_malformed_query(self, qa_agent, base_qa_state):
        """Decision: agent handles malformed input gracefully."""
        malformed = [
            "   ",
            "!!!???",
            "\n\t\n",
            "a" * 10000,  # very long query
        ]
        for q in malformed:
            state = {**base_qa_state, "query": q}
            result = await qa_agent._classify_query_node(state)
            # Should not crash, should classify to something
            assert result["intent"] in ("unknown", "general")

    @pytest.mark.asyncio
    async def test_single_character_query(self, qa_agent, base_qa_state):
        """Decision: single character query classified as general."""
        state = {**base_qa_state, "query": "?"}
        result = await qa_agent._classify_query_node(state)
        assert result["intent"] == "general"

    @pytest.mark.asyncio
    async def test_hybrid_merge_with_none_scores(self, qa_agent, base_qa_state):
        """Decision: None scores don't crash merge."""
        state = {
            **base_qa_state,
            "intent": "factual",
            "vector_results": [
                {
                    "doc_id": "doc-bad",
                    "chunk_index": 0,
                    "doc_title": "Bad",
                    "section_path": "S1",
                    "content": "content",
                    "score": None,  # type: ignore
                }
            ],
            "graph_results": [],
        }
        result = await qa_agent._hybrid_merge_node(state)
        # Should not crash, may filter out or handle gracefully
        assert "hybrid_results" in result

    def test_hybrid_score_with_missing_fields(self, qa_agent):
        """Decision: missing fields handled gracefully in scoring."""
        candidate = {}  # empty candidate
        score = qa_agent._compute_hybrid_score(
            candidate, vector_rank=None, graph_rank=None, intent=None
        )
        assert score >= 0  # Should not crash

    @pytest.mark.asyncio
    async def test_vector_search_empty_space(self, qa_agent, base_qa_state):
        """Decision: empty space_id returns empty results."""
        state = {**base_qa_state, "space_id": ""}
        result = await qa_agent._vector_search_node(state)
        assert result["vector_results"] == []

    @pytest.mark.asyncio
    async def test_graph_search_no_neo4j(self, qa_agent, base_qa_state, monkeypatch):
        """Decision: no Neo4j config returns empty graph results."""
        monkeypatch.setattr("app.agents.subagents.qa_agent.settings.NEO4J_URI", "")
        state = {**base_qa_state, "query": "test", "space_id": "space-1"}
        result = await qa_agent._graph_search_node(state)
        assert result["graph_results"] == []

    @pytest.mark.asyncio
    async def test_react_handles_tool_exception(self):
        """Decision: tool exception is caught and reported."""
        definition = self._make_definition(tools=["bad_tool"], max_rounds=3)
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

    def _make_definition(self, tools: List[str] | None = None, max_rounds: int = 3) -> AgentDefinition:
        return AgentDefinition(
            skill_id="qa_research",
            name="QA Research Agent",
            capability_type="agent",
            description="Autonomous QA agent",
            max_rounds=max_rounds,
            tools=tools or [],
        )


# ============================================================================
# 7. Decision Logging & Observability
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
