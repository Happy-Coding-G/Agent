from __future__ import annotations

import logging
import math
import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, tuple_

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)

# Constants
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
    "请问", "请", "帮我", "一下", "一下子", "什么是", "什么", "如何", "怎么", "为什么",
    "告诉我", "解释", "介绍", "描述",
)
ENGLISH_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "what", "who", "when", "where",
    "why", "how", "tell", "about", "please",
}


class VectorSearchInput(BaseModel):
    query: str = Field(description="用户查询")
    space_id: str = Field(description="空间public_id")
    top_k: int = Field(default=10, description="返回结果数量")


class GraphSearchInput(BaseModel):
    query: str = Field(description="用户查询")
    space_id: str = Field(description="空间public_id")
    top_k: int = Field(default=10, description="返回结果数量")


class RerankInput(BaseModel):
    query: str = Field(description="用户查询")
    space_id: str = Field(description="空间public_id")
    candidate_refs: List[Dict[str, Any]] = Field(description="候选引用列表")
    top_k: int = Field(default=5, description="返回结果数量")


class QAHybridSearchInput(BaseModel):
    query: str = Field(description="用户查询")
    space_id: str = Field(description="空间public_id")
    top_k: int = Field(default=5, description="返回结果数量")


class QAGenerateAnswerInput(BaseModel):
    query: str = Field(description="用户查询")
    contexts: List[Dict[str, Any]] = Field(description="检索到的上下文片段")
    conversation_history: Optional[List[Dict[str, str]]] = Field(default=None, description="对话历史")


async def _vector_search_internal(db, query: str, space, recall_limit: int, final_top_k: int) -> List[Dict[str, Any]]:
    from app.ai.embedding_client import embed_query_with_fallback
    from app.db.models import DocChunkEmbeddings, DocChunks, Documents

    vector_results: List[Dict[str, Any]] = []
    try:
        query_vector, _ = await embed_query_with_fallback(query)
        target_dim = 1536
        actual_dim = len(query_vector)
        if actual_dim != target_dim:
            query_vector = query_vector[:target_dim] if actual_dim > target_dim else query_vector + [0.0] * (target_dim - actual_dim)
        similarity = (1 - DocChunkEmbeddings.embedding.cosine_distance(query_vector)).label("similarity")
        stmt = (
            select(DocChunks, Documents, similarity)
            .join(DocChunkEmbeddings, DocChunkEmbeddings.chunk_id == DocChunks.chunk_id)
            .join(Documents, Documents.doc_id == DocChunks.doc_id)
            .where(Documents.space_id == space.id)
            .where(DocChunkEmbeddings.embedding.isnot(None))
            .order_by(desc("similarity"))
            .limit(recall_limit)
        )
        rows = (await db.execute(stmt)).all()
        for chunk, doc, sim_score in rows:
            score = _normalize_score(sim_score)
            if score <= 0.0:
                continue
            vector_results.append({
                "chunk_id": str(chunk.chunk_id),
                "doc_id": str(doc.doc_id),
                "chunk_index": chunk.chunk_index,
                "doc_title": doc.title or f"Document {str(doc.doc_id)[:8]}",
                "section_path": chunk.section_path,
                "content": chunk.content,
                "score": round(score, 6),
            })
        strong = [r for r in vector_results if r["score"] >= MIN_VECTOR_SCORE]
        vector_results = strong or vector_results[:max(final_top_k * 2, final_top_k)]
    except Exception as e:
        logger.warning(f"Vector search failed: {e}")
    return vector_results


async def _graph_search_internal(db, query: str, space, recall_limit: int) -> List[Dict[str, Any]]:
    from app.core.config import settings
    from app.db.models import Documents
    from app.services.graph.neo4j_client import get_neo4j_driver

    graph_results: List[Dict[str, Any]] = []
    try:
        neo4j_uri = (settings.NEO4J_URI or "").strip()
        if neo4j_uri:
            doc_rows = (await db.execute(select(Documents.doc_id, Documents.title, Documents.graph_id).where(Documents.space_id == space.id))).all()
            graph_ids = [str(r.graph_id) for r in doc_rows if r.graph_id]
            doc_title_map = {str(r.doc_id): (r.title or f"Document {str(r.doc_id)[:8]}") for r in doc_rows}
            terms = _extract_query_terms(query)
            if graph_ids and terms:
                driver = get_neo4j_driver()
                if driver:
                    aggregated: Dict[tuple[str, int], Dict[str, Any]] = {}
                    with driver.session(database=settings.NEO4J_DATABASE) as session:
                        cypher = """
                            MATCH (e)
                            WHERE e.graph_id IN $graph_ids
                            OPTIONAL MATCH (e)-[r]-(other)
                            WITH e, r, other,
                                 [term IN $terms WHERE
                                    toLower(coalesce(e.name, "")) CONTAINS term OR
                                    toLower(coalesce(e.description, "")) CONTAINS term OR
                                    toLower(coalesce(other.name, "")) CONTAINS term OR
                                    toLower(coalesce(other.description, "")) CONTAINS term OR
                                    toLower(coalesce(r.fact, "")) CONTAINS term
                                 ] AS matched_terms
                            WHERE size(matched_terms) > 0
                            RETURN coalesce(e.doc_id, "") AS doc_id,
                                   e.graph_id AS graph_id,
                                   coalesce(e.name, "") AS entity_name,
                                   labels(e) AS labels,
                                   coalesce(e.description, "") AS description,
                                   CASE WHEN r IS NULL THEN "" ELSE type(r) END AS relation_name,
                                   coalesce(other.name, "") AS related_entity,
                                   coalesce(r.fact, "") AS fact,
                                   coalesce(r.episode_ref, "") AS episode_ref,
                                   coalesce(r.confidence, 1.0) AS confidence,
                                   matched_terms AS matched_terms
                            ORDER BY size(matched_terms) DESC, confidence DESC
                            LIMIT $limit
                        """
                        records = session.run(cypher, graph_ids=graph_ids, terms=terms, limit=recall_limit)
                        for record in records:
                            doc_id = str(record.get("doc_id") or "")
                            if not doc_id:
                                continue
                            episode_ref = record.get("episode_ref") or ""
                            chunk_index = _parse_chunk_index(episode_ref)
                            entity_name = record.get("entity_name") or ""
                            labels = record.get("labels") or []
                            description = record.get("description") or ""
                            relation_name = record.get("relation_name") or ""
                            related_entity = record.get("related_entity") or ""
                            fact = record.get("fact") or ""
                            confidence = float(record.get("confidence") or 1.0)
                            matched_terms = [str(t) for t in (record.get("matched_terms") or []) if str(t).strip()]
                            score = _score_graph_match(matched_terms, confidence, bool(fact), chunk_index >= 0, entity_name)
                            key = (doc_id, chunk_index)
                            evidence = _build_graph_evidence(entity_name, labels, description, relation_name, related_entity, fact, matched_terms)
                            existing = aggregated.get(key)
                            if not existing:
                                aggregated[key] = {
                                    "chunk_id": None, "doc_id": doc_id, "chunk_index": chunk_index,
                                    "doc_title": doc_title_map.get(doc_id, entity_name or f"Document {doc_id[:8]}"),
                                    "section_path": relation_name or None, "content": "",
                                    "score": round(score, 6), "graph_score": round(score, 6),
                                    "graph_evidence": evidence, "match_terms": matched_terms[:4],
                                }
                            else:
                                existing["score"] = round(max(existing["score"], score), 6)
                                existing["graph_score"] = existing["score"]
                                existing["section_path"] = existing.get("section_path") or relation_name or None
                                existing["graph_evidence"] = _merge_graph_evidence(existing.get("graph_evidence"), evidence)
                                existing["match_terms"] = _merge_match_terms(existing.get("match_terms", []), matched_terms)
                    results = list(aggregated.values())
                    if results:
                        hydrated = await _hydrate_graph_chunks(db, results, doc_title_map)
                        for item in results:
                            payload = hydrated.get((item["doc_id"], int(item.get("chunk_index", -1))))
                            if payload:
                                item.update(payload)
                            else:
                                item["doc_title"] = doc_title_map.get(item["doc_id"], item["doc_title"])
                                item["content"] = item.get("content") or item.get("graph_evidence") or ""
                        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                        graph_results = results[:recall_limit]
    except Exception as e:
        logger.warning(f"Graph search failed: {e}")
    return graph_results


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def _resolve_space(space_id: str):
        from app.repositories.space_repo import SpaceRepository
        space_repo = SpaceRepository(db)
        return await space_repo.get_by_public_id(space_id)

    async def vector_search(query: str, space_id: str, top_k: int = 10) -> Dict[str, Any]:
        """执行向量检索，返回统一 candidate 格式。"""
        try:
            space = await _resolve_space(space_id)
            if not space:
                return {"success": False, "error": "Space not found", "query": query, "candidates": [], "confidence": "low", "debug": {}}

            top_k = _normalize_top_k(top_k)
            vector_recall = _compute_recall_limit(top_k, multiplier=VECTOR_RECALL_MULTIPLIER, minimum=VECTOR_RECALL_MIN, maximum=VECTOR_RECALL_MAX)

            vector_results = await _vector_search_internal(db, query, space, vector_recall, top_k)
            candidates = [_to_candidate(r, "vector") for r in vector_results]
            confidence = _assess_overall_confidence(candidates)

            return {
                "success": True,
                "query": query,
                "candidates": candidates,
                "confidence": confidence,
                "debug": {"recall_limit": vector_recall, "raw_count": len(vector_results)},
            }
        except Exception as e:
            logger.exception(f"vector_search failed: {e}")
            return {"success": False, "error": str(e), "query": query, "candidates": [], "confidence": "low", "debug": {}}

    async def graph_search(query: str, space_id: str, top_k: int = 10) -> Dict[str, Any]:
        """执行知识图谱检索，返回统一 candidate 格式。"""
        try:
            space = await _resolve_space(space_id)
            if not space:
                return {"success": False, "error": "Space not found", "query": query, "candidates": [], "confidence": "low", "debug": {}}

            top_k = _normalize_top_k(top_k)
            graph_recall = _compute_recall_limit(top_k, multiplier=GRAPH_RECALL_MULTIPLIER, minimum=GRAPH_RECALL_MIN, maximum=GRAPH_RECALL_MAX)

            graph_results = await _graph_search_internal(db, query, space, graph_recall)
            candidates = [_to_candidate(r, "graph") for r in graph_results]
            confidence = _assess_overall_confidence(candidates)

            return {
                "success": True,
                "query": query,
                "candidates": candidates,
                "confidence": confidence,
                "debug": {"recall_limit": graph_recall, "raw_count": len(graph_results)},
            }
        except Exception as e:
            logger.exception(f"graph_search failed: {e}")
            return {"success": False, "error": str(e), "query": query, "candidates": [], "confidence": "low", "debug": {}}

    async def rerank(query: str, space_id: str, candidate_refs: List[Dict[str, Any]], top_k: int = 5) -> Dict[str, Any]:
        """合并多路候选并远程重排，返回统一 candidate 格式。"""
        from app.ai.embedding_client import rerank_documents
        from app.core.config import settings

        try:
            space = await _resolve_space(space_id)
            if not space:
                return {"success": False, "error": "Space not found", "query": query, "candidates": [], "confidence": "low", "debug": {}}

            top_k = _normalize_top_k(top_k)

            # 1. Deduplicate by (doc_id, chunk_index)
            seen: set = set()
            unique_refs: List[Dict[str, Any]] = []
            for ref in candidate_refs:
                key = (ref.get("doc_id"), ref.get("chunk_index"))
                if key in seen:
                    continue
                seen.add(key)
                unique_refs.append(ref)

            if not unique_refs:
                return {
                    "success": True,
                    "query": query,
                    "candidates": [],
                    "confidence": "low",
                    "debug": {
                        "input_count": len(candidate_refs),
                        "dedup_count": 0,
                        "rerank_service": False,
                        "fallback_reason": "empty_input",
                    },
                }

            # 2. Load full content from DB
            hydrated = await _load_candidates_by_refs(db, unique_refs)

            # 3. Build document texts
            documents: List[str] = []
            for ref in unique_refs:
                doc_id = ref.get("doc_id")
                chunk_index = ref.get("chunk_index", 0)
                payload = hydrated.get((str(doc_id), int(chunk_index)))

                title = payload.get("doc_title", "Unknown") if payload else "Unknown"
                section = payload.get("section_path") if payload else None
                content = payload.get("content", "") if payload else ""

                doc_text = f"文档: {title}"
                if section:
                    doc_text += f"\n章节: {section}"
                if content:
                    doc_text += f"\n正文:\n{content[:800]}"

                documents.append(doc_text)

            # 4. Call remote rerank service
            reranked_candidates: List[Dict[str, Any]] = []
            fallback_reason: Optional[str] = None
            used_rerank_service = False

            if settings.REMOTE_RERANK_ENABLED:
                try:
                    rerank_result = await rerank_documents(
                        query=query,
                        documents=documents,
                        top_n=min(top_k, len(documents)),
                        return_documents=False,
                    )
                    used_rerank_service = True

                    results = rerank_result.get("results", [])
                    for r in results:
                        doc_idx = r.get("index")
                        if doc_idx is None or doc_idx < 0 or doc_idx >= len(unique_refs):
                            continue
                        ref = unique_refs[doc_idx]
                        payload = hydrated.get((str(ref.get("doc_id")), int(ref.get("chunk_index", 0))), {})

                        candidate = {
                            "candidate_id": ref.get("candidate_id", f"rerank:{ref.get('doc_id')}:{ref.get('chunk_index', 0)}"),
                            "chunk_id": payload.get("chunk_id"),
                            "doc_id": ref.get("doc_id"),
                            "chunk_index": ref.get("chunk_index", 0),
                            "doc_title": payload.get("doc_title", "Unknown"),
                            "section_path": payload.get("section_path"),
                            "content": payload.get("content", ""),
                            "score": round(_normalize_score(r.get("relevance_score", ref.get("original_score", 0.0))), 6),
                            "source_type": ref.get("source_type", "unknown"),
                            "confidence": _assess_single_confidence(r.get("relevance_score", ref.get("original_score", 0.0))),
                            "metadata": {},
                        }
                        reranked_candidates.append(candidate)
                except Exception as e:
                    logger.warning(f"Remote rerank failed, falling back to original scores: {e}")
                    fallback_reason = f"rerank_error: {e}"
            else:
                fallback_reason = "remote_rerank_disabled"

            # 5. Fallback: sort by original_score
            if not reranked_candidates:
                sorted_refs = sorted(unique_refs, key=lambda x: _normalize_score(x.get("original_score", 0.0)), reverse=True)
                for ref in sorted_refs[:top_k]:
                    payload = hydrated.get((str(ref.get("doc_id")), int(ref.get("chunk_index", 0))), {})
                    candidate = {
                        "candidate_id": ref.get("candidate_id", f"rerank:{ref.get('doc_id')}:{ref.get('chunk_index', 0)}"),
                        "chunk_id": payload.get("chunk_id"),
                        "doc_id": ref.get("doc_id"),
                        "chunk_index": ref.get("chunk_index", 0),
                        "doc_title": payload.get("doc_title", "Unknown"),
                        "section_path": payload.get("section_path"),
                        "content": payload.get("content", ""),
                        "score": round(_normalize_score(ref.get("original_score", 0.0)), 6),
                        "source_type": ref.get("source_type", "unknown"),
                        "confidence": _assess_single_confidence(ref.get("original_score", 0.0)),
                        "metadata": {},
                    }
                    reranked_candidates.append(candidate)

            confidence = _assess_overall_confidence(reranked_candidates)

            return {
                "success": True,
                "query": query,
                "candidates": reranked_candidates[:top_k],
                "confidence": confidence,
                "debug": {
                    "input_count": len(candidate_refs),
                    "dedup_count": len(unique_refs),
                    "rerank_service": used_rerank_service,
                    "fallback_reason": fallback_reason,
                },
            }
        except Exception as e:
            logger.exception(f"rerank failed: {e}")
            return {"success": False, "error": str(e), "query": query, "candidates": [], "confidence": "low", "debug": {"fallback_reason": f"exception: {e}"}}

    async def qa_hybrid_search(query: str, space_id: str, top_k: int = 5) -> Dict[str, Any]:
        """执行向量+图谱混合检索（向后兼容）。"""
        from app.core.errors import ServiceError

        try:
            space = await _resolve_space(space_id)
            if not space:
                return {"success": False, "error": "Space not found", "results": [], "sources": []}

            top_k = _normalize_top_k(top_k)
            vector_recall = _compute_recall_limit(top_k, multiplier=VECTOR_RECALL_MULTIPLIER, minimum=VECTOR_RECALL_MIN, maximum=VECTOR_RECALL_MAX)
            graph_recall = _compute_recall_limit(top_k, multiplier=GRAPH_RECALL_MULTIPLIER, minimum=GRAPH_RECALL_MIN, maximum=GRAPH_RECALL_MAX)

            vector_results = await _vector_search_internal(db, query, space, vector_recall, top_k)
            graph_results = await _graph_search_internal(db, query, space, graph_recall)

            merged = _hybrid_merge(vector_results, graph_results, top_k)

            sources = []
            for item in merged:
                src_list = item.get("sources", [])
                sources.append({
                    "doc_id": item.get("doc_id"),
                    "title": item.get("doc_title", "Unknown"),
                    "section": item.get("section_path", "-"),
                    "score": item.get("score", 0),
                    "source_type": ",".join(src_list) if isinstance(src_list, list) else str(src_list or "unknown"),
                    "excerpt": (item.get("content", "")[:200] + "...") if item.get("content") else "",
                })

            return {
                "success": True,
                "query": query,
                "space_id": space_id,
                "results": merged,
                "sources": sources,
                "debug": {
                    "vector_count": len(vector_results),
                    "graph_count": len(graph_results),
                    "hybrid_count": len(merged),
                },
            }
        except ServiceError as e:
            return {"success": False, "error": e.detail, "results": [], "sources": []}
        except Exception as e:
            logger.exception(f"qa_hybrid_search failed: {e}")
            return {"success": False, "error": str(e), "results": [], "sources": []}

    async def qa_generate_answer(
        query: str,
        contexts: List[Dict[str, Any]],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """基于检索到的上下文生成回答。"""
        from app.services.base import get_llm_client

        if not contexts:
            return {
                "success": True,
                "answer": "抱歉，我没有找到与您问题相关的文档内容。请尝试调整您的问题或先上传相关文档。",
                "sources": [],
            }

        context_text = _build_context_text(contexts)
        prompt = _build_qa_prompt(query, context_text, conversation_history)

        try:
            llm = get_llm_client(temperature=0.2)
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            answer = content if isinstance(content, str) else str(content)

            sources = []
            for ctx in contexts[:MAX_FINAL_RESULTS]:
                src_list = ctx.get("sources", [])
                sources.append({
                    "doc_id": ctx.get("doc_id"),
                    "title": ctx.get("doc_title", "Unknown"),
                    "section": ctx.get("section_path", "-"),
                    "source_type": ",".join(src_list) if isinstance(src_list, list) else str(src_list or "unknown"),
                })

            return {"success": True, "answer": answer, "sources": sources}
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return {"success": False, "answer": "生成回答时出现错误，请稍后重试。", "sources": [], "error": str(e)}

    return [
        StructuredTool.from_function(
            name="vector_search",
            func=vector_search,
            description="执行向量检索，返回与用户查询语义相似的文档片段。返回统一 candidate 格式，含 confidence 评估。",
            args_schema=VectorSearchInput,
            coroutine=vector_search,
        ),
        StructuredTool.from_function(
            name="graph_search",
            func=graph_search,
            description="执行知识图谱检索，返回与查询关键词匹配的实体和关系片段。返回统一 candidate 格式，含 graph_evidence。",
            args_schema=GraphSearchInput,
            coroutine=graph_search,
        ),
        StructuredTool.from_function(
            name="rerank",
            func=rerank,
            description="合并多路检索候选并远程重排。输入 candidate_refs 轻量引用，输出按 relevance_score 排序的候选。支持降级到 original_score 排序。",
            args_schema=RerankInput,
            coroutine=rerank,
        ),
        StructuredTool.from_function(
            name="qa_hybrid_search",
            func=qa_hybrid_search,
            description="执行向量+知识图谱混合检索，召回与用户查询相关的文档片段。返回带有评分和来源的上下文列表。（向后兼容）",
            args_schema=QAHybridSearchInput,
            coroutine=qa_hybrid_search,
        ),
        StructuredTool.from_function(
            name="qa_generate_answer",
            func=qa_generate_answer,
            description="基于检索到的上下文片段生成自然语言回答。必须传入 contexts（来自 qa_hybrid_search 或 rerank 的结果）。",
            args_schema=QAGenerateAnswerInput,
            coroutine=qa_generate_answer,
        ),
    ]


# ---------------------------------------------------------------------------
# Helper functions (extracted from QAAgent)
# ---------------------------------------------------------------------------

def _normalize_top_k(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 5
    return max(1, min(parsed, MAX_FINAL_RESULTS))


def _compute_recall_limit(top_k: int, *, multiplier: int, minimum: int, maximum: int) -> int:
    return max(1, min(max(top_k * multiplier, minimum), maximum))


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(score) or math.isinf(score):
        return 0.0
    if score <= 0.0:
        return 0.0
    return min(score, 1.0)


def _extract_query_terms(query: str) -> List[str]:
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
        if len(cleaned) < 2 or cleaned in seen or cleaned in ENGLISH_STOPWORDS:
            return False
        seen.add(cleaned)
        terms.append(cleaned)
        return True

    cjk_budget = 4
    for cjk_phrase in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        for variant in _expand_cjk_terms(cjk_phrase):
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


def _expand_cjk_terms(phrase: str) -> List[str]:
    if len(phrase) <= 4:
        return [phrase]
    variants: List[str] = []
    for size in range(min(4, len(phrase)), 1, -1):
        for start in range(0, len(phrase) - size + 1):
            variants.append(phrase[start : start + size])
    return variants


def _parse_chunk_index(episode_ref: str) -> int:
    if ":chunk_" not in episode_ref:
        return -1
    try:
        return int(episode_ref.rsplit(":chunk_", 1)[1])
    except ValueError:
        return -1


def _safe_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _to_candidate(item: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    score = _normalize_score(item.get("score", 0.0))
    return {
        "candidate_id": f"{source_type}:{item.get('doc_id')}:{item.get('chunk_index', 0)}",
        "chunk_id": item.get("chunk_id"),
        "doc_id": item.get("doc_id"),
        "chunk_index": item.get("chunk_index", 0),
        "doc_title": item.get("doc_title", "Unknown"),
        "section_path": item.get("section_path"),
        "content": item.get("content", ""),
        "score": round(score, 6),
        "source_type": source_type,
        "confidence": _assess_single_confidence(score),
        "metadata": {
            "graph_evidence": item.get("graph_evidence"),
            "match_terms": item.get("match_terms"),
        } if source_type == "graph" else {},
    }


def _assess_single_confidence(score: float) -> str:
    score = _normalize_score(score)
    if score >= 0.7:
        return "high"
    elif score >= 0.4:
        return "medium"
    else:
        return "low"


def _assess_overall_confidence(candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return "low"
    top_score = _normalize_score(candidates[0].get("score", 0.0))
    if top_score >= 0.7:
        return "high"
    elif top_score >= 0.4:
        return "medium"
    else:
        return "low"


async def _load_candidates_by_refs(db, candidate_refs: List[Dict[str, Any]]) -> Dict[tuple[str, int], Dict[str, Any]]:
    from app.db.models import DocChunks, Documents
    pairs = set()
    for ref in candidate_refs:
        doc_id = ref.get("doc_id")
        chunk_index = ref.get("chunk_index")
        if doc_id is None or chunk_index is None:
            continue
        doc_uuid = _safe_uuid(doc_id)
        if doc_uuid is None:
            continue
        pairs.add((doc_uuid, int(chunk_index)))
    if not pairs:
        return {}
    stmt = (
        select(DocChunks, Documents)
        .join(Documents, Documents.doc_id == DocChunks.doc_id)
        .where(tuple_(DocChunks.doc_id, DocChunks.chunk_index).in_(list(pairs)))
    )
    rows = (await db.execute(stmt)).all()
    hydrated: Dict[tuple[str, int], Dict[str, Any]] = {}
    for chunk, doc in rows:
        hydrated[(str(chunk.doc_id), chunk.chunk_index)] = {
            "chunk_id": str(chunk.chunk_id),
            "doc_title": doc.title or f"Document {str(doc.doc_id)[:8]}",
            "section_path": chunk.section_path,
            "content": chunk.content,
        }
    return hydrated


def _score_graph_match(matched_terms: List[str], confidence: float, has_fact: bool, has_episode_ref: bool, entity_name: str) -> float:
    normalized_confidence = _normalize_score(confidence)
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


def _build_graph_evidence(entity_name: str, labels: Any, description: str, relation_name: str, related_entity: str, fact: str, matched_terms: List[str]) -> str:
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


def _merge_graph_evidence(current: Optional[str], incoming: Optional[str]) -> Optional[str]:
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


def _merge_match_terms(current: List[str], incoming: List[str]) -> List[str]:
    merged: List[str] = []
    for value in [*(current or []), *(incoming or [])]:
        normalized = str(value).strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged[:4]


async def _hydrate_graph_chunks(db, items: List[Dict[str, Any]], doc_title_map: Dict[str, str]) -> Dict[tuple[str, int], Dict[str, Any]]:
    from app.db.models import DocChunks, Documents
    pairs = set()
    for item in items:
        doc_uuid = _safe_uuid(item.get("doc_id"))
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
    rows = (await db.execute(stmt)).all()
    hydrated: Dict[tuple[str, int], Dict[str, Any]] = {}
    for chunk, doc in rows:
        hydrated[(str(chunk.doc_id), chunk.chunk_index)] = {
            "chunk_id": str(chunk.chunk_id),
            "doc_title": doc.title or doc_title_map.get(str(doc.doc_id), f"Document {str(doc.doc_id)[:8]}"),
            "section_path": chunk.section_path,
            "content": chunk.content,
        }
    return hydrated


def _hybrid_merge(vector_results: List[Dict[str, Any]], graph_results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    candidates: Dict[tuple[str, int], Dict[str, Any]] = {}
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

    def ensure_candidate(doc_id: str, chunk_index: int) -> Dict[str, Any]:
        key = (doc_id, chunk_index)
        if key not in candidates:
            candidates[key] = {
                "chunk_id": None, "doc_id": doc_id, "chunk_index": chunk_index,
                "doc_title": "Unknown", "section_path": None, "content": "",
                "score": 0.0, "vector_score": None, "graph_score": None,
                "graph_evidence": None, "rerank_text": "", "match_terms": [], "sources": [],
            }
        return candidates[key]

    for item in vector_results:
        doc_id = item.get("doc_id") or ""
        chunk_index = item.get("chunk_index", 0)
        if not doc_id:
            continue
        cand = ensure_candidate(doc_id, chunk_index)
        cand["chunk_id"] = item.get("chunk_id")
        cand["doc_title"] = item.get("doc_title", cand["doc_title"])
        cand["section_path"] = item.get("section_path") or cand["section_path"]
        cand["content"] = item.get("content", cand["content"])
        cand["vector_score"] = _normalize_score(item.get("score", 0.0))
        if "vector" not in cand["sources"]:
            cand["sources"].append("vector")

    for item in graph_results:
        doc_id = item.get("doc_id") or ""
        chunk_index = item.get("chunk_index", 0)
        if not doc_id:
            continue
        cand = ensure_candidate(doc_id, chunk_index)
        cand["doc_title"] = item.get("doc_title", cand["doc_title"])
        cand["section_path"] = item.get("section_path", cand["section_path"])
        incoming_content = item.get("content", "")
        if incoming_content and len(incoming_content) > len(cand["content"]):
            cand["content"] = incoming_content
        cand["graph_score"] = _normalize_score(item.get("score", 0.0))
        if item.get("graph_evidence"):
            cand["graph_evidence"] = _merge_graph_evidence(cand.get("graph_evidence"), item.get("graph_evidence"))
        if item.get("match_terms"):
            cand["match_terms"] = _merge_match_terms(cand.get("match_terms", []), item.get("match_terms", []))
        if "graph" not in cand["sources"]:
            cand["sources"].append("graph")

    merged: List[Dict[str, Any]] = []
    for key, cand in candidates.items():
        if not cand.get("content") and not cand.get("graph_evidence"):
            continue
        cand["score"] = round(_compute_hybrid_score(cand, vector_rank=vector_rank_map.get(key), graph_rank=graph_rank_map.get(key)), 6)
        cand["rerank_text"] = _build_rerank_text(cand)
        merged.append(cand)

    merged.sort(key=lambda x: x["score"], reverse=True)
    recall_limit = _compute_recall_limit(top_k, multiplier=RERANK_POOL_MULTIPLIER, minimum=RERANK_POOL_MIN, maximum=RERANK_POOL_MAX)
    return merged[:recall_limit][:top_k]


def _compute_hybrid_score(candidate: Dict[str, Any], *, vector_rank: Optional[int], graph_rank: Optional[int]) -> float:
    vector_weight, graph_weight = 1.0, 0.9
    raw_sum = 0.0
    weight_sum = 0.0
    rrf_sum = 0.0
    if candidate.get("vector_score") is not None:
        raw_sum += vector_weight * _normalize_score(candidate.get("vector_score"))
        weight_sum += vector_weight
        if vector_rank is not None:
            rrf_sum += vector_weight / (HYBRID_RRF_K + max(vector_rank, 1))
    if candidate.get("graph_score") is not None:
        raw_sum += graph_weight * _normalize_score(candidate.get("graph_score"))
        weight_sum += graph_weight
        if graph_rank is not None:
            rrf_sum += graph_weight / (HYBRID_RRF_K + max(graph_rank, 1))
    raw_component = raw_sum / weight_sum if weight_sum else 0.0
    normalized_rrf = min(rrf_sum * 12.0, 1.0)
    source_bonus = 0.08 if candidate.get("vector_score") is not None and candidate.get("graph_score") is not None else 0.0
    return min(1.0, raw_component * 0.6 + normalized_rrf * 0.4 + source_bonus)


def _build_rerank_text(candidate: Dict[str, Any]) -> str:
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


def _build_context_text(items: List[Dict[str, Any]]) -> str:
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


def _build_qa_prompt(query: str, context_text: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> str:
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
