"""
QAAgent - Enhanced knowledge retrieval agent with hybrid search.

Unified interface for RAG-based question answering:
- Space-aware permission checking
- Streaming and non-streaming support
- Hybrid search (pgvector + Neo4j)
- Rich source attribution
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from typing import Any, Optional, AsyncGenerator, Dict, List, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, select, tuple_

from app.agents.core import QAState, QA_SYSTEM_PROMPT
from app.ai.embedding_client import embed_query_with_fallback
from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import DocChunkEmbeddings, DocChunks, Documents, Users
from app.repositories.space_repo import SpaceRepository
from app.services.base import SpaceAwareService, get_llm_client
from app.services.graph.neo4j_client import get_neo4j_driver

logger = logging.getLogger(__name__)


MAX_FINAL_RESULTS = 12
VECTOR_RECALL_MULTIPLIER = 6
VECTOR_RECALL_MIN = 24
VECTOR_RECALL_MAX = 60
GRAPH_RECALL_MULTIPLIER = 4
GRAPH_RECALL_MIN = 12
GRAPH_RECALL_MAX = 24
RERANK_POOL_MULTIPLIER = 4
RERANK_POOL_MIN = 12
RERANK_POOL_MAX = 24
HYBRID_RRF_K = 20
MIN_VECTOR_SCORE = 0.15

QUERY_NOISE_PHRASES = (
    "请问",
    "请",
    "帮我",
    "一下",
    "一下子",
    "什么是",
    "什么",
    "如何",
    "怎么",
    "为什么",
    "告诉我",
    "解释",
    "介绍",
    "描述",
)

ENGLISH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "tell",
    "about",
    "please",
}


class RetrievalCandidate(TypedDict, total=False):
    """统一检索结果结构体，用于向量检索与图检索的结果合并与重排。"""

    chunk_id: Optional[str]
    doc_id: str
    chunk_index: int
    doc_title: str
    section_path: Optional[str]
    content: str
    score: float
    vector_score: Optional[float]
    graph_score: Optional[float]
    graph_evidence: Optional[str]
    rerank_text: str
    match_terms: List[str]
    sources: List[str]


class QAAgent(SpaceAwareService):
    """
    QA Agent with hybrid search and unified interface.

    Usage:
        # Non-streaming
        result = await agent.run(
            query="What is the main topic?",
            space_public_id="xxx",
            user=user,
            top_k=5
        )

        # Streaming
        async for event in agent.stream(
            query="What is the main topic?",
            space_public_id="xxx",
            user=user
        ):
            print(event)  # {type: "token", content: "..."}
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._neo4j_driver = None
        self._neo4j_lock = threading.Lock()
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph for QA pipeline.

        hybrid_merge 后通过条件边检查：若检索结果为空则直接跳到
        format_sources（跳过 generate_answer 中昂贵的 LLM 调用），
        generate_answer_node 内部已有空结果兜底逻辑会设置默认回答。
        """
        builder = StateGraph(QAState)

        builder.add_node("classify_query", RunnableLambda(self._classify_query_node))
        builder.add_node("vector_search", RunnableLambda(self._vector_search_node))
        builder.add_node("graph_search", RunnableLambda(self._graph_search_node))
        builder.add_node("hybrid_merge", RunnableLambda(self._hybrid_merge_node))
        builder.add_node("rerank_hybrid", RunnableLambda(self._rerank_hybrid_node))
        builder.add_node("generate_answer", RunnableLambda(self._generate_answer_node))
        builder.add_node(
            "no_results_answer", RunnableLambda(self._no_results_answer_node)
        )
        builder.add_node("format_sources", RunnableLambda(self._format_sources_node))

        builder.add_edge("classify_query", "vector_search")
        builder.add_edge("classify_query", "graph_search")
        builder.add_edge("vector_search", "hybrid_merge")
        builder.add_edge("graph_search", "hybrid_merge")
        builder.add_edge("hybrid_merge", "rerank_hybrid")
        builder.add_edge("rerank_hybrid", "generate_answer")
        builder.add_edge("generate_answer", "format_sources")
        builder.add_edge("no_results_answer", "format_sources")
        builder.add_edge("format_sources", END)

        builder.set_entry_point("classify_query")
        return builder.compile()

    @staticmethod
    def _has_retrieval_results(state: QAState) -> str:
        """检查 hybrid_merge 是否产生了结果。"""
        return "has_results" if state.get("hybrid_results") else "empty"

    @staticmethod
    async def _no_results_answer_node(state: QAState) -> QAState:
        """检索结果为空时直接生成默认回答，跳过 LLM 调用。"""
        state["answer"] = (
            "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。"
        )
        return state

    async def run(
        self,
        query: str,
        space_public_id: str,
        user: Users,
        top_k: int = 5,
        context_items: Optional[List[Dict[str, Any]]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Run QA in non-streaming mode.

        Returns:
            {
                "success": bool,
                "agent_type": "qa",
                "answer": str,
                "sources": List[Dict],
                "retrieval_debug": Dict,
                "error": Optional[str]
            }
        """
        # Permission check
        space = await self._require_space(space_public_id, user)

        initial_state: QAState = {
            "query": query,
            "space_id": space_public_id,
            "user_id": user.id,
            "top_k": top_k,
            "context_items": context_items,
            "conversation_history": conversation_history or [],
            "intent": None,
            "vector_results": [],
            "graph_results": [],
            "hybrid_results": [],
            "answer": None,
            "sources": [],
            "retrieval_debug": {},
            "error": None,
        }

        try:
            result = await self.graph.ainvoke(initial_state)

            return {
                "success": True,
                "agent_type": "qa",
                "answer": result.get("answer", ""),
                "sources": result.get("sources", []),
                "retrieval_debug": {
                    "vector_results_count": len(result.get("vector_results", [])),
                    "graph_results_count": len(result.get("graph_results", [])),
                    "hybrid_results_count": len(result.get("hybrid_results", [])),
                    "intent": result.get("intent"),
                },
                "error": None,
            }
        except Exception as e:
            logger.exception(f"QAAgent error: {e}")
            return {
                "success": False,
                "agent_type": "qa",
                "answer": f"处理问题时出现错误: {str(e)}",
                "sources": [],
                "retrieval_debug": {},
                "error": str(e),
            }

    async def stream(
        self,
        query: str,
        space_public_id: str,
        user: Users,
        top_k: int = 5,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run QA in streaming mode.

        架构变更说明（2026-04-15）：
        为了消除 stream() 与 run() 之间的双份代码维护问题，
        stream() 现在统一走 self.graph.ainvoke() 完成完整的检索与生成逻辑，
        然后将最终答案分块模拟流式输出给用户。这样保证了两种模式的行为一致性。

        Yields events:
            {"type": "status", "content": "retrieving"}
            {"type": "sources", "content": [...]}
            {"type": "token", "content": "..."}
            {"type": "result", "content": {...}}
            {"type": "error", "content": "..."}
        """
        try:
            await self._require_space(space_public_id, user)

            yield {"type": "status", "content": "retrieving"}

            initial_state: QAState = {
                "query": query,
                "space_id": space_public_id,
                "user_id": user.id,
                "top_k": top_k,
                "context_items": None,
                "conversation_history": conversation_history or [],
                "intent": None,
                "vector_results": [],
                "graph_results": [],
                "hybrid_results": [],
                "answer": None,
                "sources": [],
                "retrieval_debug": {},
                "error": None,
            }

            # 统一走 LangGraph，复用所有节点逻辑（classify → vector → graph → merge → rerank → generate → format）
            yield {"type": "status", "content": "searching_knowledge_base"}
            state = await self.graph.ainvoke(initial_state)

            # Yield sources
            yield {"type": "sources", "content": state.get("sources", [])}

            # Step: Generate streaming answer
            yield {"type": "status", "content": "generating"}

            answer = state.get("answer") or ""
            if not answer:
                answer = "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。"

            # 将完整答案分块模拟流式输出，保持前端打字机效果
            chunk_size = max(1, len(answer) // 20)
            for i in range(0, len(answer), chunk_size):
                yield {"type": "token", "content": answer[i : i + chunk_size]}
                await asyncio.sleep(0.02)

            # Final result
            yield {
                "type": "result",
                "content": {
                    "success": True,
                    "agent_type": "qa",
                    "answer": answer,
                    "sources": state.get("sources", []),
                    "retrieval_debug": {
                        "vector_count": len(state.get("vector_results", [])),
                        "graph_count": len(state.get("graph_results", [])),
                        "hybrid_count": len(state.get("hybrid_results", [])),
                    },
                },
            }

        except ServiceError as e:
            yield {"type": "error", "content": str(e.detail)}
        except Exception as e:
            logger.exception(f"QAAgent stream error: {e}")
            yield {"type": "error", "content": f"处理问题时出现错误: {str(e)}"}

    # ==========================================================================
    # Graph Nodes
    # ==========================================================================

    async def _classify_query_node(self, state: QAState) -> QAState:
        """Classify query intent."""
        query = state.get("query", "").strip().lower()

        if not query:
            state["intent"] = "unknown"
        elif any(
            kw in query
            for kw in [
                "什么",
                "谁",
                "何时",
                "哪里",
                "为什么",
                "如何",
                "what",
                "who",
                "when",
                "where",
                "why",
                "how",
            ]
        ):
            state["intent"] = "factual"
        elif any(
            kw in query
            for kw in ["解释", "描述", "告诉我", "explain", "describe", "tell me"]
        ):
            state["intent"] = "explanatory"
        elif any(kw in query for kw in ["比较", "区别", "difference", "compare"]):
            state["intent"] = "comparative"
        else:
            state["intent"] = "general"

        return state

    async def _vector_search_node(self, state: QAState) -> QAState:
        """Vector search with space filtering."""
        query = state.get("query", "")
        space_public_id = state.get("space_id")
        top_k = state.get("top_k", 5)

        if not query or not space_public_id:
            state["vector_results"] = []
            return state

        try:
            results = await self._retrieve_vector_context(
                query,
                space_public_id=space_public_id,
                top_k=top_k,
            )
            state["vector_results"] = results
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            state["vector_results"] = []

        return state

    async def _graph_search_node(self, state: QAState) -> QAState:
        """Knowledge graph search."""
        query = state.get("query", "")
        space_public_id = state.get("space_id")
        top_k = state.get("top_k", 3)

        if not query or not space_public_id:
            state["graph_results"] = []
            return state

        try:
            results = await self._retrieve_graph_context(
                query,
                space_public_id=space_public_id,
                top_k=top_k,
            )
            state["graph_results"] = results
        except Exception as e:
            logger.warning(f"Graph search failed: {e}")
            state["graph_results"] = []

        return state

    async def _hybrid_merge_node(self, state: QAState) -> QAState:
        """Merge vector and graph results at chunk level with confidence boost."""
        vector_results = state.get("vector_results", [])
        graph_results = state.get("graph_results", [])
        intent = state.get("intent")
        top_k = self._normalize_top_k(state.get("top_k", 5))

        candidates: Dict[tuple[str, int], RetrievalCandidate] = {}
        vector_rank_map = {
            (str(item.get("doc_id") or ""), int(item.get("chunk_index", -1))): rank
            for rank, item in enumerate(vector_results, start=1)
            if item.get("doc_id")
        }
        graph_rank_map = {
            (str(item.get("doc_id") or ""), int(item.get("chunk_index", -1))): rank
            for rank, item in enumerate(graph_results, start=1)
            if item.get("doc_id")
        }

        def _ensure_candidate(doc_id: str, chunk_index: int) -> RetrievalCandidate:
            key = (doc_id, chunk_index)
            if key not in candidates:
                candidates[key] = {
                    "chunk_id": None,
                    "doc_id": doc_id,
                    "chunk_index": chunk_index,
                    "doc_title": "Unknown",
                    "section_path": None,
                    "content": "",
                    "score": 0.0,
                    "vector_score": None,
                    "graph_score": None,
                    "graph_evidence": None,
                    "rerank_text": "",
                    "match_terms": [],
                    "sources": [],
                }
            return candidates[key]

        # Inject vector candidates
        for item in vector_results:
            doc_id = item.get("doc_id") or ""
            chunk_index = item.get("chunk_index", 0)
            if not doc_id:
                continue
            cand = _ensure_candidate(doc_id, chunk_index)
            cand["chunk_id"] = item.get("chunk_id")
            cand["doc_title"] = item.get("doc_title", cand["doc_title"])
            cand["section_path"] = item.get("section_path") or cand["section_path"]
            cand["content"] = item.get("content", cand["content"])
            cand["vector_score"] = self._normalize_score(item.get("score", 0.0))
            if "vector" not in cand["sources"]:
                cand["sources"].append("vector")

        # Inject graph candidates
        for item in graph_results:
            doc_id = item.get("doc_id") or ""
            chunk_index = item.get("chunk_index", 0)
            if not doc_id:
                continue
            cand = _ensure_candidate(doc_id, chunk_index)
            cand["doc_title"] = item.get("doc_title", cand["doc_title"])
            cand["section_path"] = item.get("section_path", cand["section_path"])
            incoming_content = item.get("content", "")
            if incoming_content and len(incoming_content) > len(cand["content"]):
                cand["content"] = incoming_content
            cand["graph_score"] = self._normalize_score(item.get("score", 0.0))
            if item.get("graph_evidence"):
                cand["graph_evidence"] = self._merge_graph_evidence(
                    cand.get("graph_evidence"),
                    item.get("graph_evidence"),
                )
            if item.get("match_terms"):
                cand["match_terms"] = self._merge_match_terms(
                    cand.get("match_terms", []),
                    item.get("match_terms", []),
                )
            if "graph" not in cand["sources"]:
                cand["sources"].append("graph")

        merged: List[RetrievalCandidate] = []
        for key, cand in candidates.items():
            if not cand.get("content") and not cand.get("graph_evidence"):
                continue
            cand["score"] = round(
                self._compute_hybrid_score(
                    cand,
                    vector_rank=vector_rank_map.get(key),
                    graph_rank=graph_rank_map.get(key),
                    intent=intent,
                ),
                6,
            )
            cand["rerank_text"] = self._build_rerank_text(cand)
            merged.append(cand)

        merged.sort(key=lambda x: x["score"], reverse=True)
        state["hybrid_results"] = merged[
            : self._compute_recall_limit(
                top_k,
                multiplier=RERANK_POOL_MULTIPLIER,
                minimum=RERANK_POOL_MIN,
                maximum=RERANK_POOL_MAX,
            )
        ]
        return state

    async def _rerank_hybrid_node(self, state: QAState) -> QAState:
        """Rerank unified hybrid candidates."""
        query = state.get("query", "")
        top_k = self._normalize_top_k(state.get("top_k", 5))
        candidates = state.get("hybrid_results", [])

        if not candidates:
            state["hybrid_results"] = []
            return state

        if not settings.REMOTE_RERANK_ENABLED:
            state["hybrid_results"] = candidates[:top_k]
            return state

        try:
            from app.ai.embedding_client import rerank_documents

            rerank_inputs = [
                (index, cand.get("rerank_text") or cand.get("content", ""))
                for index, cand in enumerate(candidates)
                if (cand.get("rerank_text") or cand.get("content", "")).strip()
            ]
            if not rerank_inputs:
                state["hybrid_results"] = candidates[:top_k]
                return state

            rerank_result = await rerank_documents(
                query=query,
                documents=[text for _index, text in rerank_inputs],
                top_n=top_k,
            )

            reranked: List[RetrievalCandidate] = []
            for r in rerank_result.get("results", []):
                idx = r.get("index", 0)
                if idx < 0 or idx >= len(rerank_inputs):
                    continue
                score = r.get("relevance_score", 0.0)
                source_index = rerank_inputs[idx][0]
                cand = dict(candidates[source_index])
                cand["score"] = round(float(score), 6)
                reranked.append(cand)

            if reranked:
                state["hybrid_results"] = reranked[:top_k]
            else:
                state["hybrid_results"] = candidates[:top_k]

        except Exception as e:
            logger.warning(f"Hybrid rerank failed, using merged scores: {e}")
            state["hybrid_results"] = candidates[:top_k]

        return state

    async def _generate_answer_node(self, state: QAState) -> QAState:
        """Generate answer using LLM."""
        query = state.get("query", "")
        hybrid_results = state.get("hybrid_results", [])

        if not hybrid_results:
            state["answer"] = (
                "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。"
            )
            return state

        context_text = self._build_context_text(hybrid_results)
        prompt = self._build_qa_prompt(
            query, context_text, state.get("conversation_history")
        )

        try:
            llm = get_llm_client(temperature=0.2)
            response = await llm.ainvoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            state["answer"] = content if isinstance(content, str) else str(content)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            state["answer"] = "生成回答时出现错误，请稍后重试。"

        return state

    async def _format_sources_node(self, state: QAState) -> QAState:
        """Format source citations."""
        hybrid_results = state.get("hybrid_results", [])
        sources = []

        for item in hybrid_results:
            src_list = item.get("sources", [])
            sources.append(
                {
                    "doc_id": item.get("doc_id"),
                    "title": item.get("doc_title", "Unknown"),
                    "section": item.get("section_path", "-"),
                    "score": item.get("score", 0),
                    "source_type": ",".join(src_list)
                    if isinstance(src_list, list)
                    else str(src_list or "unknown"),
                    "excerpt": (item.get("content", "")[:200] + "...")
                    if item.get("content")
                    else "",
                }
            )

        state["sources"] = sources
        return state

    # ==========================================================================
    # Retrieval Methods
    # ==========================================================================

    async def _retrieve_vector_context(
        self,
        query: str,
        space_public_id: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve context from pgvector with space filtering.

        Args:
            query: Search query
            space_public_id: Space public ID for permission filtering
            top_k: Number of results
        """
        top_k = self._normalize_top_k(top_k)
        recall_k = self._compute_recall_limit(
            top_k,
            multiplier=VECTOR_RECALL_MULTIPLIER,
            minimum=VECTOR_RECALL_MIN,
            maximum=VECTOR_RECALL_MAX,
        )

        space_repo = SpaceRepository(self.db)
        space = await space_repo.get_by_public_id(space_public_id)
        if not space:
            raise ServiceError(404, "Space not found")

        query_vector, _ = await embed_query_with_fallback(query)
        similarity = (
            1 - DocChunkEmbeddings.embedding.cosine_distance(query_vector)
        ).label("similarity")

        stmt = (
            select(DocChunks, Documents, similarity)
            .join(DocChunkEmbeddings, DocChunkEmbeddings.chunk_id == DocChunks.chunk_id)
            .join(Documents, Documents.doc_id == DocChunks.doc_id)
            .where(Documents.space_id == space.id)
            .where(DocChunkEmbeddings.embedding.isnot(None))
            .order_by(desc("similarity"))
            .limit(recall_k)
        )
        rows = (await self.db.execute(stmt)).all()

        if not rows:
            return []

        result: List[Dict[str, Any]] = []
        for chunk, doc, similarity_score in rows:
            score = self._normalize_score(similarity_score)
            if score <= 0.0:
                continue
            result.append(
                {
                    "chunk_id": str(chunk.chunk_id),
                    "doc_id": str(doc.doc_id),
                    "chunk_index": chunk.chunk_index,
                    "doc_title": doc.title or f"Document {str(doc.doc_id)[:8]}",
                    "section_path": chunk.section_path,
                    "content": chunk.content,
                    "score": round(score, 6),
                }
            )

        if not result:
            return []

        strong_results = [item for item in result if item["score"] >= MIN_VECTOR_SCORE]
        return strong_results or result[: max(top_k * 2, top_k)]

    async def _retrieve_graph_context(
        self,
        query: str,
        space_public_id: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Retrieve context from Neo4j knowledge graph at chunk level."""
        neo4j_uri = (settings.NEO4J_URI or "").strip()
        if not neo4j_uri:
            return []

        top_k = self._normalize_top_k(top_k)
        recall_k = self._compute_recall_limit(
            top_k,
            multiplier=GRAPH_RECALL_MULTIPLIER,
            minimum=GRAPH_RECALL_MIN,
            maximum=GRAPH_RECALL_MAX,
        )

        space_repo = SpaceRepository(self.db)
        space = await space_repo.get_by_public_id(space_public_id)
        if not space:
            raise ServiceError(404, "Space not found")

        doc_rows = (
            await self.db.execute(
                select(Documents.doc_id, Documents.title, Documents.graph_id).where(
                    Documents.space_id == space.id
                )
            )
        ).all()

        graph_ids = [str(row.graph_id) for row in doc_rows if row.graph_id]
        if not graph_ids:
            return []

        doc_title_map = {
            str(row.doc_id): (row.title or f"Document {str(row.doc_id)[:8]}")
            for row in doc_rows
        }
        terms = self._extract_query_terms(query)
        if not terms:
            return []

        try:
            driver = get_neo4j_driver()
            if not driver:
                return []

            aggregated: Dict[tuple[str, int], Dict[str, Any]] = {}
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                query_text = """
                    MATCH (e)
                    WHERE e.graph_id IN $graph_ids
                    OPTIONAL MATCH (e)-[r]-(other)
                    WITH e, r, other,
                         [term IN $terms WHERE
                            toLower(coalesce(e.name, \"\")) CONTAINS term OR
                            toLower(coalesce(e.description, \"\")) CONTAINS term OR
                            toLower(coalesce(other.name, \"\")) CONTAINS term OR
                            toLower(coalesce(other.description, \"\")) CONTAINS term OR
                            toLower(coalesce(r.fact, \"\")) CONTAINS term
                         ] AS matched_terms
                    WHERE size(matched_terms) > 0
                    RETURN coalesce(e.doc_id, \"\") AS doc_id,
                           e.graph_id AS graph_id,
                           coalesce(e.name, \"\") AS entity_name,
                           labels(e) AS labels,
                           coalesce(e.description, \"\") AS description,
                           CASE WHEN r IS NULL THEN \"\" ELSE type(r) END AS relation_name,
                           coalesce(other.name, \"\") AS related_entity,
                           coalesce(r.fact, \"\") AS fact,
                           coalesce(r.episode_ref, \"\") AS episode_ref,
                           coalesce(r.confidence, 1.0) AS confidence,
                           matched_terms AS matched_terms
                    ORDER BY size(matched_terms) DESC, confidence DESC
                    LIMIT $limit
                    """
                records = session.run(
                    query_text,
                    graph_ids=graph_ids,
                    terms=terms,
                    limit=recall_k,
                )
                for record in records:
                    doc_id = str(record.get("doc_id") or "")
                    if not doc_id:
                        continue

                    episode_ref = record.get("episode_ref") or ""
                    chunk_index = self._parse_chunk_index(episode_ref)
                    entity_name = record.get("entity_name") or ""
                    labels = record.get("labels") or []
                    description = record.get("description") or ""
                    relation_name = record.get("relation_name") or ""
                    related_entity = record.get("related_entity") or ""
                    fact = record.get("fact") or ""
                    confidence = float(record.get("confidence") or 1.0)
                    matched_terms = [
                        str(term)
                        for term in (record.get("matched_terms") or [])
                        if str(term).strip()
                    ]
                    score = self._score_graph_match(
                        matched_terms=matched_terms,
                        confidence=confidence,
                        has_fact=bool(fact),
                        has_episode_ref=chunk_index >= 0,
                        entity_name=entity_name,
                    )
                    key = (doc_id, chunk_index)
                    evidence = self._build_graph_evidence(
                        entity_name=entity_name,
                        labels=labels,
                        description=description,
                        relation_name=relation_name,
                        related_entity=related_entity,
                        fact=fact,
                        matched_terms=matched_terms,
                    )

                    existing = aggregated.get(key)
                    if not existing:
                        aggregated[key] = {
                            "chunk_id": None,
                            "doc_id": doc_id,
                            "chunk_index": chunk_index,
                            "doc_title": doc_title_map.get(
                                doc_id, entity_name or f"Document {doc_id[:8]}"
                            ),
                            "section_path": relation_name or None,
                            "content": "",
                            "score": round(score, 6),
                            "graph_score": round(score, 6),
                            "graph_evidence": evidence,
                            "match_terms": matched_terms[:4],
                        }
                        continue

                    existing["score"] = round(max(existing["score"], score), 6)
                    existing["graph_score"] = existing["score"]
                    existing["section_path"] = (
                        existing.get("section_path") or relation_name or None
                    )
                    existing["graph_evidence"] = self._merge_graph_evidence(
                        existing.get("graph_evidence"),
                        evidence,
                    )
                    existing["match_terms"] = self._merge_match_terms(
                        existing.get("match_terms", []),
                        matched_terms,
                    )

            results = list(aggregated.values())
            if not results:
                return []

            hydrated_chunks = await self._hydrate_graph_chunks(results, doc_title_map)
            for item in results:
                chunk_payload = hydrated_chunks.get(
                    (item["doc_id"], int(item.get("chunk_index", -1)))
                )
                if chunk_payload:
                    item.update(chunk_payload)
                else:
                    item["doc_title"] = doc_title_map.get(
                        item["doc_id"], item["doc_title"]
                    )
                    item["content"] = (
                        item.get("content") or item.get("graph_evidence") or ""
                    )

            results.sort(key=lambda item: item.get("score", 0.0), reverse=True)
            return results[:recall_k]

        except Exception as e:
            logger.warning(f"Neo4j search failed: {e}")
            return []

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def _build_qa_prompt(
        self,
        query: str,
        context_text: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Build QA prompt with optional conversation history."""
        history_text = ""
        if conversation_history:
            turns = []
            for turn in conversation_history[-4:]:
                q = turn.get("query", "")
                a = turn.get("answer", "")
                if q:
                    turns.append(f"用户：{q}")
                if a:
                    turns.append(f"助手：{a}")
            if turns:
                history_text = "\n".join(turns) + "\n\n"

        return (
            "你是一个基于知识库的问答助手。请根据提供的上下文回答用户问题。\n\n"
            "规则：\n"
            "1. 始终基于上下文回答，不要编造信息\n"
            "2. 如果上下文不足，明确说明\n"
            "3. 引用来源时标注 [文档标题]\n"
            "4. 回答简洁、准确\n\n"
            f"{history_text}"
            f"上下文：\n{context_text}\n\n"
            f"用户问题：{query}\n\n"
            "请回答："
        )

    def _build_context_text(self, items: List[Dict[str, Any]]) -> str:
        """Build context text from retrieved items."""
        if not items:
            return "（无可用上下文）"

        blocks = []
        for idx, item in enumerate(items[:MAX_FINAL_RESULTS], start=1):
            content = item.get("content", "") or item.get("graph_evidence", "")
            if item.get("graph_evidence") and item.get("graph_evidence") not in content:
                content = f"{content}\n图谱证据: {item.get('graph_evidence')}".strip()
            blocks.append(
                f"[{idx}] {item.get('doc_title', 'Unknown')} "
                f"| section={item.get('section_path') or '-'} "
                f"| score={item.get('score', 0):.4f}\n"
                f"{content}"
            )
        return "\n\n".join(blocks)

    def _normalize_top_k(self, value: Any) -> int:
        """Normalize top_k to a safe range for retrieval and prompting."""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 5
        return max(1, min(parsed, MAX_FINAL_RESULTS))

    def _compute_recall_limit(
        self,
        top_k: int,
        *,
        multiplier: int,
        minimum: int,
        maximum: int,
    ) -> int:
        """Compute a bounded recall window for coarse retrieval."""
        return max(1, min(max(top_k * multiplier, minimum), maximum))

    def _normalize_score(self, value: Any) -> float:
        """Clamp heterogeneous retrieval scores into [0, 1]."""
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0

        if math.isnan(score) or math.isinf(score):
            return 0.0
        if score <= 0.0:
            return 0.0
        return min(score, 1.0)

    def _get_intent_weights(self, intent: Optional[str]) -> tuple[float, float]:
        """Use intent to bias vector vs graph fusion before rerank."""
        if intent == "factual":
            return 0.95, 1.15
        if intent == "explanatory":
            return 1.15, 0.85
        if intent == "comparative":
            return 1.05, 1.0
        return 1.0, 0.9

    def _compute_hybrid_score(
        self,
        candidate: RetrievalCandidate,
        *,
        vector_rank: Optional[int],
        graph_rank: Optional[int],
        intent: Optional[str],
    ) -> float:
        """Fuse vector and graph candidates with score normalization plus weighted RRF."""
        vector_weight, graph_weight = self._get_intent_weights(intent)

        raw_sum = 0.0
        weight_sum = 0.0
        rrf_sum = 0.0

        if candidate.get("vector_score") is not None:
            raw_sum += vector_weight * self._normalize_score(
                candidate.get("vector_score")
            )
            weight_sum += vector_weight
            if vector_rank is not None:
                rrf_sum += vector_weight / (HYBRID_RRF_K + max(vector_rank, 1))

        if candidate.get("graph_score") is not None:
            raw_sum += graph_weight * self._normalize_score(
                candidate.get("graph_score")
            )
            weight_sum += graph_weight
            if graph_rank is not None:
                rrf_sum += graph_weight / (HYBRID_RRF_K + max(graph_rank, 1))

        raw_component = raw_sum / weight_sum if weight_sum else 0.0
        normalized_rrf = min(rrf_sum * 12.0, 1.0)
        source_bonus = (
            0.08
            if candidate.get("vector_score") is not None
            and candidate.get("graph_score") is not None
            else 0.0
        )
        return min(1.0, raw_component * 0.6 + normalized_rrf * 0.4 + source_bonus)

    def _build_rerank_text(self, candidate: RetrievalCandidate) -> str:
        """Build richer rerank input with both chunk content and graph evidence."""
        parts = [f"文档: {candidate.get('doc_title', 'Unknown')}"]
        if candidate.get("section_path"):
            parts.append(f"章节: {candidate.get('section_path')}")
        if candidate.get("content"):
            parts.append(f"正文:\n{candidate.get('content')}")
        if candidate.get("graph_evidence"):
            parts.append(f"图谱证据:\n{candidate.get('graph_evidence')}")
        if candidate.get("sources"):
            parts.append(f"检索通道: {', '.join(candidate.get('sources', []))}")
        return "\n".join(parts)

    def _build_graph_evidence(
        self,
        *,
        entity_name: str,
        labels: Any,
        description: str,
        relation_name: str,
        related_entity: str,
        fact: str,
        matched_terms: List[str],
    ) -> str:
        """Render graph facts into a compact evidence string for rerank and prompting."""
        label = labels[0] if isinstance(labels, list) and labels else "Entity"
        head = f"{entity_name or 'Entity'} [{label}]"
        if relation_name and related_entity:
            head += f" --{relation_name}--> {related_entity}"

        details = []
        if fact:
            details.append(fact)
        elif description:
            details.append(description)
        if matched_terms:
            details.append(f"命中词: {', '.join(matched_terms[:3])}")

        if details:
            return f"{head} | {'；'.join(details)}"
        return head

    def _merge_graph_evidence(
        self,
        current: Optional[str],
        incoming: Optional[str],
    ) -> Optional[str]:
        """Merge graph evidence snippets while keeping them compact and de-duplicated."""
        pieces = []
        for value in [current, incoming]:
            if not value:
                continue
            for line in str(value).split("\n"):
                stripped = line.strip()
                if stripped and stripped not in pieces:
                    pieces.append(stripped)
        if not pieces:
            return None
        return "\n".join(pieces[:3])

    def _merge_match_terms(
        self,
        current: List[str],
        incoming: List[str],
    ) -> List[str]:
        """Merge matched query terms without duplication."""
        merged: List[str] = []
        for value in [*(current or []), *(incoming or [])]:
            normalized = str(value).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged[:4]

    def _extract_query_terms(self, query: str) -> List[str]:
        """Extract graph-friendly search terms from Chinese and English queries."""
        normalized = query.lower()
        for phrase in QUERY_NOISE_PHRASES:
            normalized = normalized.replace(phrase, " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return []

        terms: List[str] = []
        seen: set[str] = set()

        def add_term(term: str) -> bool:
            cleaned = term.strip(" -_:,.!?;，。！？；：")
            if len(cleaned) < 2:
                return False
            if cleaned in seen:
                return False
            if cleaned in ENGLISH_STOPWORDS:
                return False
            seen.add(cleaned)
            terms.append(cleaned)
            return True

        cjk_budget = 4
        for cjk_phrase in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            for variant in self._expand_cjk_terms(cjk_phrase):
                add_term(variant)
                if len(terms) >= cjk_budget:
                    break
            if len(terms) >= cjk_budget:
                break

        for english_term in re.findall(r"[a-z0-9][a-z0-9_:-]{1,}", normalized):
            add_term(english_term)
            if len(terms) >= 6:
                return terms

        if not terms:
            add_term(normalized[:64])
        return terms[:6]

    def _expand_cjk_terms(self, phrase: str) -> List[str]:
        """Expand long Chinese phrases into overlapping 2-4 char keywords."""
        if len(phrase) <= 4:
            return [phrase]

        variants: List[str] = []
        for size in range(min(4, len(phrase)), 1, -1):
            for start in range(0, len(phrase) - size + 1):
                variants.append(phrase[start : start + size])
        return variants

    def _parse_chunk_index(self, episode_ref: str) -> int:
        """Extract chunk index from Neo4j episode_ref."""
        if ":chunk_" not in episode_ref:
            return -1
        try:
            return int(episode_ref.rsplit(":chunk_", 1)[1])
        except ValueError:
            return -1

    def _safe_uuid(self, value: Any) -> Optional[uuid.UUID]:
        """Parse UUID values defensively for DB lookups."""
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None

    def _score_graph_match(
        self,
        *,
        matched_terms: List[str],
        confidence: float,
        has_fact: bool,
        has_episode_ref: bool,
        entity_name: str,
    ) -> float:
        """Score graph matches with structural evidence and term overlap."""
        normalized_confidence = self._normalize_score(confidence)
        exact_name_hit = any(term in entity_name.lower() for term in matched_terms)

        score = 0.25
        score += min(len(matched_terms), 3) * 0.18
        score += normalized_confidence * 0.18
        if has_fact:
            score += 0.14
        if has_episode_ref:
            score += 0.10
        if exact_name_hit:
            score += 0.12
        return min(score, 1.0)

    async def _hydrate_graph_chunks(
        self,
        items: List[Dict[str, Any]],
        doc_title_map: Dict[str, str],
    ) -> Dict[tuple[str, int], Dict[str, Any]]:
        """Hydrate graph hits back to concrete chunk payloads for unified rerank."""
        pairs = set()
        for item in items:
            doc_uuid = self._safe_uuid(item.get("doc_id"))
            chunk_index = int(item.get("chunk_index", -1))
            if doc_uuid is None or chunk_index < 0:
                continue
            pairs.add((doc_uuid, chunk_index))

        if not pairs:
            return {}

        stmt = (
            select(DocChunks, Documents)
            .join(Documents, Documents.doc_id == DocChunks.doc_id)
            .where(tuple_(DocChunks.doc_id, DocChunks.chunk_index).in_(list(pairs)))
        )
        rows = (await self.db.execute(stmt)).all()

        hydrated: Dict[tuple[str, int], Dict[str, Any]] = {}
        for chunk, doc in rows:
            hydrated[(str(chunk.doc_id), chunk.chunk_index)] = {
                "chunk_id": str(chunk.chunk_id),
                "doc_title": doc.title
                or doc_title_map.get(
                    str(doc.doc_id), f"Document {str(doc.doc_id)[:8]}"
                ),
                "section_path": chunk.section_path,
                "content": chunk.content,
            }
        return hydrated
