"""QAAgent retrieval optimization tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.subagents.qa_agent import QAAgent
from app.agents.core.main_agent import MainAgent, AgentType


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


class TestQAAgentInitialization:
    def test_can_instantiate_without_errors(self, mock_db_session):
        """回归测试：QAAgent 应能正常实例化（验证 threading 导入已修复）。"""
        qa = QAAgent(mock_db_session)
        assert qa is not None
        assert qa.graph is not None


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


class TestQAAgentGraphInvoke:
    @pytest.mark.asyncio
    async def test_graph_ainvoke_runs_without_invalid_update(self, agent, monkeypatch):
        """回归测试：graph.ainvoke 真实执行时不应出现并发写入错误。"""
        monkeypatch.setattr(
            agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            agent, "_retrieve_vector_context", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            agent, "_retrieve_graph_context", AsyncMock(return_value=[])
        )

        initial_state = {
            "query": "test query",
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

        result = await agent.graph.ainvoke(initial_state)
        assert "answer" in result
        assert "sources" in result


class TestQAAgentGraphRouting:
    def test_has_retrieval_results_branch(self, agent):
        """回归测试：no_results 条件边在图中真实生效。"""
        state_with = {"hybrid_results": [{"doc_id": "d1"}]}
        state_empty = {"hybrid_results": []}
        assert agent._has_retrieval_results(state_with) == "has_results"
        assert agent._has_retrieval_results(state_empty) == "empty"

    @pytest.mark.asyncio
    async def test_no_results_answer_node(self, agent):
        """回归测试：空结果节点返回默认兜底回答。"""
        state = {"hybrid_results": [], "answer": None}
        result = await agent._no_results_answer_node(state)
        assert "没有找到与您问题相关的文档内容" in result["answer"]


class TestQAAgentHistoryPassing:
    @pytest.mark.asyncio
    async def test_run_accepts_conversation_history(self, agent, monkeypatch):
        """回归测试：run() 能正确接收并透传 conversation_history。"""
        monkeypatch.setattr(
            agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "answer": "test",
            "sources": [],
            "vector_results": [],
            "graph_results": [],
            "hybrid_results": [],
        })
        agent.graph = mock_graph

        history = [{"query": "之前的问题", "answer": "之前的回答"}]
        result = await agent.run(
            query="后续问题",
            space_public_id="space-1",
            user=MagicMock(id=1),
            conversation_history=history,
            session_id="sess_qa_1",
        )
        call_args = mock_graph.ainvoke.call_args[0][0]
        assert call_args["conversation_history"] == history


class TestQAAgentSessionIdMemory:
    @pytest.mark.asyncio
    async def test_stream_with_session_id_persists_memory(self, agent, monkeypatch):
        """回归测试：stream() 在 session_id 存在时会持久化 QA 记忆。"""
        monkeypatch.setattr(
            agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            agent, "_classify_query_node", AsyncMock(return_value={"intent": "factual"})
        )
        monkeypatch.setattr(
            agent, "_vector_search_node", AsyncMock(return_value={"vector_results": []})
        )
        monkeypatch.setattr(
            agent, "_graph_search_node", AsyncMock(return_value={"graph_results": []})
        )
        monkeypatch.setattr(
            agent, "_hybrid_merge_node", AsyncMock(return_value={"hybrid_results": []})
        )
        monkeypatch.setattr(
            agent, "_rerank_hybrid_node", AsyncMock(return_value={"hybrid_results": []})
        )

        persist_mock = AsyncMock()
        monkeypatch.setattr(agent, "_persist_qa_memory", persist_mock)

        chunks = []
        async for chunk in agent.stream(
            query="hello",
            space_public_id="space-1",
            user=MagicMock(id=1),
            session_id="sess_qa_2",
        ):
            chunks.append(chunk)

        assert any(c["type"] == "result" for c in chunks)
        persist_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_without_session_id_skips_persistence(self, agent, monkeypatch):
        """回归测试：stream() 在没有 session_id 时不持久化记忆。"""
        monkeypatch.setattr(
            agent, "_require_space", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            agent, "_classify_query_node", AsyncMock(return_value={"intent": "factual"})
        )
        monkeypatch.setattr(
            agent, "_vector_search_node", AsyncMock(return_value={"vector_results": []})
        )
        monkeypatch.setattr(
            agent, "_graph_search_node", AsyncMock(return_value={"graph_results": []})
        )
        monkeypatch.setattr(
            agent, "_hybrid_merge_node", AsyncMock(return_value={"hybrid_results": []})
        )
        monkeypatch.setattr(
            agent, "_rerank_hybrid_node", AsyncMock(return_value={"hybrid_results": []})
        )

        persist_mock = AsyncMock()
        monkeypatch.setattr(agent, "_persist_qa_memory", persist_mock)

        chunks = []
        async for chunk in agent.stream(
            query="hello",
            space_public_id="space-1",
            user=MagicMock(id=1),
            session_id=None,
        ):
            chunks.append(chunk)

        persist_mock.assert_not_called()