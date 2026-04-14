"""
QAAgent - Enhanced knowledge retrieval agent with hybrid search.

Unified interface for RAG-based question answering:
- Space-aware permission checking
- Streaming and non-streaming support
- Hybrid search (pgvector + Neo4j)
- Rich source attribution
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional, AsyncGenerator, Dict, List

from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agents.core import QAState, QA_SYSTEM_PROMPT
from app.ai.embedding_client import embed_query_with_fallback
from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import DocChunkEmbeddings, DocChunks, Documents, Users
from app.repositories.space_repo import SpaceRepository
from app.services.base import SpaceAwareService, get_llm_client

logger = logging.getLogger(__name__)


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
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph for QA pipeline."""
        builder = StateGraph(QAState)

        builder.add_node("classify_query", RunnableLambda(self._classify_query_node))
        builder.add_node("vector_search", RunnableLambda(self._vector_search_node))
        builder.add_node("graph_search", RunnableLambda(self._graph_search_node))
        builder.add_node("hybrid_merge", RunnableLambda(self._hybrid_merge_node))
        builder.add_node("generate_answer", RunnableLambda(self._generate_answer_node))
        builder.add_node("format_sources", RunnableLambda(self._format_sources_node))

        builder.add_edge("classify_query", "vector_search")
        builder.add_edge("classify_query", "graph_search")
        builder.add_edge("vector_search", "hybrid_merge")
        builder.add_edge("graph_search", "hybrid_merge")
        builder.add_edge("hybrid_merge", "generate_answer")
        builder.add_edge("generate_answer", "format_sources")
        builder.add_edge("format_sources", END)

        builder.set_entry_point("classify_query")
        return builder.compile()

    async def run(
        self,
        query: str,
        space_public_id: str,
        user: Users,
        top_k: int = 5,
        context_items: Optional[List[Dict]] = None,
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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run QA in streaming mode.

        Yields events:
            {"type": "status", "content": "retrieving"}
            {"type": "sources", "content": [...]}
            {"type": "token", "content": "..."}
            {"type": "result", "content": {...}}
            {"type": "error", "content": "..."}
        """
        try:
            # Permission check
            space = await self._require_space(space_public_id, user)

            yield {"type": "status", "content": "retrieving"}

            # Build state
            state: QAState = {
                "query": query,
                "space_id": space_public_id,
                "user_id": user.id,
                "top_k": top_k,
                "context_items": None,
                "intent": None,
                "vector_results": [],
                "graph_results": [],
                "hybrid_results": [],
                "answer": None,
                "sources": [],
                "retrieval_debug": {},
                "error": None,
            }

            # Step 1: Classify
            state = await self._classify_query_node(state)

            # Step 2: Retrieve (both vector and graph)
            yield {"type": "status", "content": "searching_knowledge_base"}

            state = await self._vector_search_node(state)
            state = await self._graph_search_node(state)
            state = await self._hybrid_merge_node(state)

            # Yield sources
            yield {"type": "sources", "content": state.get("hybrid_results", [])}

            # Step 3: Generate streaming answer
            yield {"type": "status", "content": "generating"}

            hybrid_results = state.get("hybrid_results", [])

            if not hybrid_results:
                answer = "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。"
                yield {"type": "token", "content": answer}
                state["answer"] = answer
            else:
                context_text = self._build_context_text(hybrid_results)
                prompt = self._build_qa_prompt(query, context_text)

                llm = get_llm_client(temperature=0.2)
                full_answer = ""

                async for chunk in llm.astream(prompt):
                    content = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if content:
                        full_answer += content
                        yield {"type": "token", "content": content}

                state["answer"] = full_answer

            # Step 4: Format sources
            state = await self._format_sources_node(state)

            # Final result
            yield {
                "type": "result",
                "content": {
                    "success": True,
                    "agent_type": "qa",
                    "answer": state.get("answer"),
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
        elif any(kw in query for kw in ["什么", "谁", "何时", "哪里", "为什么", "如何", "what", "who", "when", "where", "why", "how"]):
            state["intent"] = "factual"
        elif any(kw in query for kw in ["解释", "描述", "告诉我", "explain", "describe", "tell me"]):
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
        top_k = state.get("top_k", 3)

        if not query:
            state["graph_results"] = []
            return state

        try:
            results = await self._retrieve_graph_context(query, top_k=top_k)
            state["graph_results"] = results
        except Exception as e:
            logger.warning(f"Graph search failed: {e}")
            state["graph_results"] = []

        return state

    async def _hybrid_merge_node(self, state: QAState) -> QAState:
        """Merge and deduplicate results."""
        vector_results = state.get("vector_results", [])
        graph_results = state.get("graph_results", [])

        seen_ids = set()
        merged: List[Dict[str, Any]] = []

        # Prioritize graph results
        for item in graph_results:
            doc_id = item.get("doc_id")
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                item["source"] = "graph"
                merged.append(item)

        # Add vector results
        for item in vector_results:
            doc_id = item.get("doc_id")
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                item["source"] = "vector"
                merged.append(item)

        state["hybrid_results"] = merged
        return state

    async def _generate_answer_node(self, state: QAState) -> QAState:
        """Generate answer using LLM."""
        query = state.get("query", "")
        hybrid_results = state.get("hybrid_results", [])

        if not hybrid_results:
            state["answer"] = "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。"
            return state

        context_text = self._build_context_text(hybrid_results)
        prompt = self._build_qa_prompt(query, context_text)

        try:
            llm = get_llm_client(temperature=0.2)
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
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
            sources.append({
                "doc_id": item.get("doc_id"),
                "title": item.get("doc_title", "Unknown"),
                "section": item.get("section_path", "-"),
                "score": item.get("score", 0),
                "source_type": item.get("source", "unknown"),
                "excerpt": (item.get("content", "")[:200] + "...") if item.get("content") else "",
            })

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
        # Get space DB ID
        space_repo = SpaceRepository(self.db)
        space = await space_repo.get_by_public_id(space_public_id)
        if not space:
            raise ServiceError(404, "Space not found")

        # Query with space filter
        stmt = (
            select(DocChunks, DocChunkEmbeddings, Documents)
            .join(DocChunkEmbeddings, DocChunkEmbeddings.chunk_id == DocChunks.chunk_id)
            .join(Documents, Documents.doc_id == DocChunks.doc_id)
            .where(Documents.space_id == space.id)
        )
        rows = (await self.db.execute(stmt)).all()

        if not rows:
            return []

        # Extract vectors
        vector_rows: List[tuple[DocChunks, Documents, List[float]]] = []
        for chunk, embedding_row, doc in rows:
            vector = self._to_float_list(embedding_row.embedding)
            if not vector:
                continue
            vector_rows.append((chunk, doc, vector))

        if not vector_rows:
            return []

        # Embed query
        expected_dim = self._most_common_dimension(
            [vector for _chunk, _doc, vector in vector_rows]
        )
        query_vector, _ = await embed_query_with_fallback(
            query, target_dimension=expected_dim
        )

        if not query_vector:
            return []

        # Score and rank
        scored: List[tuple[float, DocChunks, Documents]] = []
        for chunk, doc, vector in vector_rows:
            if len(vector) != len(query_vector):
                continue
            score = self._cosine_similarity(query_vector, vector)
            scored.append((score, chunk, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        top_items = scored[:max(1, min(top_k, 12))]

        # Format results
        result: List[Dict[str, Any]] = []
        for score, chunk, doc in top_items:
            result.append({
                "score": round(score, 6),
                "doc_id": str(doc.doc_id),
                "doc_title": doc.title or f"Document {str(doc.doc_id)[:8]}",
                "section_path": chunk.section_path,
                "content": chunk.content,
            })

        return result

    async def _retrieve_graph_context(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Retrieve context from Neo4j knowledge graph."""
        neo4j_uri = (settings.NEO4J_URI or "").strip()
        if not neo4j_uri:
            return []

        try:
            from neo4j import GraphDatabase

            if self._neo4j_driver is None:
                self._neo4j_driver = GraphDatabase.driver(
                    neo4j_uri,
                    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
                )

            results = []
            keywords = query.lower().split()[:3]

            with self._neo4j_driver.session(database=settings.NEO4J_DATABASE) as session:
                for keyword in keywords:
                    query_text = """
                    MATCH (e:Entity)
                    WHERE toLower(e.id) CONTAINS $keyword
                       OR toLower(e.description) CONTAINS $keyword
                    MATCH (e)-[r]-(other)
                    RETURN e.id AS entity_id,
                           e.type AS entity_type,
                           e.description AS description,
                           type(r) AS relation,
                           other.id AS related_entity
                    LIMIT 5
                    """
                    records = session.run(query_text, keyword=keyword)
                    for record in records:
                        results.append({
                            "doc_id": record.get("entity_id"),
                            "doc_title": record.get("entity_id"),
                            "section_path": record.get("relation"),
                            "content": f"{record.get('entity_type')}: {record.get('description', '')}",
                            "score": 0.8,
                        })

            return results[:top_k]

        except Exception as e:
            logger.warning(f"Neo4j search failed: {e}")
            return []

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def _build_qa_prompt(self, query: str, context_text: str) -> str:
        """Build QA prompt."""
        return (
            "你是一个基于知识库的问答助手。请根据提供的上下文回答用户问题。\n\n"
            "规则：\n"
            "1. 始终基于上下文回答，不要编造信息\n"
            "2. 如果上下文不足，明确说明\n"
            "3. 引用来源时标注 [文档标题]\n"
            "4. 回答简洁、准确\n\n"
            f"上下文：\n{context_text}\n\n"
            f"用户问题：{query}\n\n"
            "请回答："
        )

    def _build_context_text(self, items: List[Dict[str, Any]]) -> str:
        """Build context text from retrieved items."""
        if not items:
            return "（无可用上下文）"

        blocks = []
        for idx, item in enumerate(items, start=1):
            blocks.append(
                f"[{idx}] {item.get('doc_title', 'Unknown')} "
                f"| section={item.get('section_path') or '-'} "
                f"| score={item.get('score', 0):.4f}\n"
                f"{item.get('content', '')}"
            )
        return "\n\n".join(blocks)

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity."""
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _most_common_dimension(self, vectors: List[List[float]]) -> Optional[int]:
        """Find most common vector dimension."""
        counts: Dict[int, int] = {}
        for vector in vectors:
            dim = len(vector)
            if dim > 0:
                counts[dim] = counts.get(dim, 0) + 1

        if not counts:
            return None
        return max(counts.items(), key=lambda x: x[1])[0]

    def _to_float_list(self, value: Any) -> List[float]:
        """Convert value to list of floats."""
        if value is None:
            return []
        if isinstance(value, list):
            return [float(x) for x in value]
        if isinstance(value, tuple):
            return [float(x) for x in value]
        if isinstance(value, str):
            text = value.strip().strip("[]")
            if not text:
                return []
            try:
                return [float(piece.strip()) for piece in text.split(",")]
            except ValueError:
                return []
        try:
            return [float(x) for x in value]
        except Exception:
            return []
