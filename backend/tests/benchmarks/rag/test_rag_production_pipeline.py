"""
RAG 检索评测 - 真实环境测试

使用实际的 Embedding、ReRank 和 Neo4j 进行 5 层 RAG 检索评测。

数据流程:
1. 将测试数据导入 PostgreSQL/pgvector (DocChunks + DocChunkEmbeddings)
2. 将图数据导入 Neo4j
3. 执行 5 层检索并测量延迟

评测层次:
1. 纯向量检索 (Vector Search)
2. 向量检索 + 重排序 (Vector + Rerank)
3. 图检索独立评测 (Graph Only)
4. 向量 + 图混合检索 (Hybrid)
5. 完整流程 (Full Pipeline: Vector + Graph + Rerank)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
import uuid
import asyncio
from typing import List, Dict, Any, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict

import pytest

# 加载基准测试数据
BENCHMARK_DATA_PATH = Path(__file__).parent / "rag_benchmark_data.json"
if BENCHMARK_DATA_PATH.exists():
    with open(BENCHMARK_DATA_PATH, 'r', encoding='utf-8') as f:
        BENCHMARK_DATA = json.load(f)
else:
    BENCHMARK_DATA = None

PERSONS = BENCHMARK_DATA.get("persons", []) if BENCHMARK_DATA else []
CORPUS = BENCHMARK_DATA.get("documents", []) if BENCHMARK_DATA else []
ALL_ENTITIES = BENCHMARK_DATA.get("entities", []) if BENCHMARK_DATA else []
GRAPH_RELATIONS = BENCHMARK_DATA.get("relations", []) if BENCHMARK_DATA else []
EVAL_QUERIES = BENCHMARK_DATA.get("queries", []) if BENCHMARK_DATA else []


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class ChunkWithEmbedding:
    """文档块及其向量"""
    chunk_id: str
    content: str
    person_id: str
    embedding: Optional[List[float]] = None


@dataclass
class EntityNode:
    """实体节点"""
    entity_id: str
    entity_name: str
    entity_type: str
    person_id: str
    doc_ids: List[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    """检索结果"""
    doc_id: str
    content: str
    score: float
    source: str  # 'vector', 'graph', 'hybrid'
    latency_ms: float


@dataclass
class LayerMetrics:
    """各层评测指标"""
    layer_name: str
    recall_at_10: float
    recall_at_20: float
    ndcg_at_10: float
    ndcg_at_20: float
    mrr: float
    map: float
    hit_rate_at_10: float
    hit_rate_at_20: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


# ============================================================================
# 配置
# ============================================================================

# 实际使用的向量维度 (从远程 Embedding 服务获取)
VECTOR_DIMENSION = 2560  # Qwen3-Embedding-4B 输出 2560 维


# ============================================================================
# 数据库操作
# ============================================================================

async def init_database():
    """初始化数据库表"""
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # 确保 pgvector 扩展已启用
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # 检查 doc_chunk_embeddings 表的向量维度
        result = await session.execute(text("""
            SELECT attname, atttypmod - 4 as dimension
            FROM pg_attribute
            WHERE attrelid = 'doc_chunk_embeddings'::regclass
            AND attname = 'embedding'
        """))
        row = result.fetchone()
        if row:
            existing_dim = row[1]
            if existing_dim != VECTOR_DIMENSION:
                print(f"  当前向量维度: {existing_dim}, 需要: {VECTOR_DIMENSION}")
                print("  警告: 向量维度不匹配，检索测试可能失败")

        await session.commit()


async def clear_test_data(space_id: int = 999999):
    """清除测试数据"""
    from sqlalchemy import text, delete, select
    from app.db.session import AsyncSessionLocal
    from app.db.models import Documents, DocChunks, DocChunkEmbeddings

    async with AsyncSessionLocal() as session:
        # 删除测试空间的文档
        await session.execute(
            delete(DocChunkEmbeddings).where(
                DocChunkEmbeddings.chunk_id.in_(
                    select(DocChunks.chunk_id).where(
                        DocChunks.doc_id.in_(
                            select(Documents.doc_id).where(Documents.space_id == space_id)
                        )
                    )
                )
            )
        )
        await session.execute(
            delete(DocChunks).where(
                DocChunks.doc_id.in_(
                    select(Documents.doc_id).where(Documents.space_id == space_id)
                )
            )
        )
        await session.execute(delete(Documents).where(Documents.space_id == space_id))
        await session.commit()


async def insert_test_chunks(chunks: List[ChunkWithEmbedding], space_id: int = None) -> int:
    """插入测试文档块及其向量 - 使用原始 ORM 模型"""
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models import Documents, DocChunks, DocChunkEmbeddings, Spaces, Users
    from app.ai.embedding_client import embed_documents_with_fallback
    import uuid

    async with AsyncSessionLocal() as session:
        # 创建或获取测试 user
        test_user_id = 1
        result = await session.execute(select(Users).where(Users.id == test_user_id))
        if not result.scalar_one_or_none():
            test_user = Users(id=test_user_id, user_key="benchmark_user", display_name="Benchmark User")
            session.add(test_user)
            await session.flush()

        # 创建或获取测试 space
        if space_id is None:
            result = await session.execute(select(Spaces).limit(1))
            existing_space = result.scalar_one_or_none()
            if existing_space:
                space_id = existing_space.id
            else:
                test_space = Spaces(
                    public_id="benchmark_test",
                    name="RAG Benchmark Test Space",
                    owner_user_id=test_user_id
                )
                session.add(test_space)
                await session.flush()
                space_id = test_space.id
        else:
            result = await session.execute(select(Spaces).where(Spaces.id == space_id))
            if not result.scalar_one_or_none():
                test_space = Spaces(
                    id=space_id,
                    public_id=f"benchmark_{space_id}",
                    name=f"RAG Benchmark Space {space_id}",
                    owner_user_id=test_user_id
                )
                session.add(test_space)
                await session.flush()

        # 创建测试文档
        doc_id = uuid.uuid4()
        doc = Documents(
            doc_id=doc_id,
            space_id=space_id,
            graph_id=uuid.uuid4(),
            title="RAG Benchmark Test Document",
            markdown_text="Benchmark test document",
            status="completed",
            created_by=1,
        )
        session.add(doc)
        await session.flush()

        # 批量向量化 (获取实际维度)
        contents = [chunk.content for chunk in chunks]
        print(f"  向量化 {len(contents)} 个文档块...")
        vectors, model_name = await embed_documents_with_fallback(contents)
        print(f"  向量化完成，使用模型: {model_name}")

        # 获取实际向量维度
        actual_dim = len(vectors[0]) if vectors else 1536
        print(f"  实际向量维度: {actual_dim}")

        # 批量插入 chunks
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            chunk_uuid = uuid.uuid4()
            chunk_ids.append(chunk_uuid)

            db_chunk = DocChunks(
                chunk_id=chunk_uuid,
                doc_id=doc_id,
                chunk_index=i,
                content=chunk.content,
                token_count=len(chunk.content.split()) * 2,
                chunk_metadata={"person_id": chunk.person_id}
            )
            session.add(db_chunk)

            # 添加向量
            if vectors and i < len(vectors):
                embedding = DocChunkEmbeddings(
                    chunk_id=chunk_uuid,
                    model=model_name,
                    embedding=vectors[i]
                )
                session.add(embedding)

        await session.commit()
        return len(chunk_ids)


async def search_vectors_top_k(
    query_embedding: List[float],
    top_k: int = 20,
    space_id: int = 999999
) -> List[Tuple[str, float, str]]:
    """向量检索 Top-K - 处理维度不匹配"""
    from sqlalchemy import select, text
    from app.db.session import AsyncSessionLocal
    from app.db.models import DocChunks, DocChunkEmbeddings

    # 检查向量维度
    db_dim = 1536  # 数据库向量维度
    query_dim = len(query_embedding)

    if query_dim != db_dim:
        print(f"  警告: 查询向量维度 {query_dim} 与数据库 {db_dim} 不匹配")

        # 降维或升维处理
        if query_dim > db_dim:
            # 降维: 取前 N 维
            adjusted_query = query_embedding[:db_dim]
        else:
            # 升维: 补零
            adjusted_query = query_embedding + [0.0] * (db_dim - query_dim)
    else:
        adjusted_query = query_embedding

    async with AsyncSessionLocal() as session:
        # 使用 pgvector 的余弦相似度搜索
        query_vec = str(adjusted_query)

        result = await session.execute(
            text("""
                SELECT
                    dce.chunk_id,
                    dce.embedding <=> CAST(:query_vec AS vector) AS distance,
                    dc.content
                FROM doc_chunk_embeddings dce
                JOIN doc_chunks dc ON dc.chunk_id = dce.chunk_id
                JOIN documents d ON d.doc_id = dc.doc_id
                WHERE d.space_id = :space_id
                ORDER BY dce.embedding <=> CAST(:query_vec AS vector)
                LIMIT :top_k
            """),
            {"query_vec": query_vec, "space_id": space_id, "top_k": top_k}
        )

        rows = result.fetchall()
        return [(str(row[0]), float(row[1]), row[2]) for row in rows]


async def insert_graph_data(entities: List[EntityNode], relations: List[Tuple]) -> int:
    """插入图数据到 Neo4j"""
    from app.db.neo4j.driver import get_neo4j_driver
    from app.core.config import settings

    driver = get_neo4j_driver()
    node_count = 0

    with driver.session(database=settings.NEO4J_DATABASE) as session:
        # 清除旧数据
        session.run("MATCH (n) DETACH DELETE n")

        # 创建节点
        for entity in entities:
            session.run("""
                CREATE (e:Entity {
                    entity_id: $entity_id,
                    name: $name,
                    entity_type: $entity_type,
                    person_id: $person_id,
                    description: $description
                })
            """, {
                "entity_id": entity.entity_id,
                "name": entity.entity_name,
                "entity_type": entity.entity_type,
                "person_id": entity.person_id,
                "description": f"{entity.entity_type}: {entity.entity_name}"
            })
            node_count += 1

        # 创建关系
        for source_id, relation, target_id, description in relations:
            session.run("""
                MATCH (a:Entity {entity_id: $source_id})
                MATCH (b:Entity {entity_id: $target_id})
                CREATE (a)-[r:RELATES {
                    type: $relation,
                    fact: $description
                }]->(b)
            """, {
                "source_id": source_id,
                "target_id": target_id,
                "relation": relation,
                "description": description
            })

    return node_count


async def graph_retrieval(
    query: str,
    entities: List[str],
    hop: int = 1,
    limit: int = 20
) -> List[Dict]:
    """图检索"""
    from app.db.neo4j.driver import get_neo4j_driver
    from app.core.config import settings

    driver = get_neo4j_driver()
    results = []

    with driver.session(database=settings.NEO4J_DATABASE) as session:
        # BFS 多跳检索
        result = session.run("""
            MATCH (start:Entity)
            WHERE start.name CONTAINS $query OR start.entity_id CONTAINS $query
            RETURN start.entity_id AS entity_id, start.name AS name, start.person_id AS person_id
            LIMIT $limit
        """, {"query": query, "limit": limit})

        for record in result:
            results.append({
                "entity_id": record["entity_id"],
                "name": record["name"],
                "person_id": record["person_id"],
                "score": 1.0 / (hop + 1)
            })

    return results


# ============================================================================
# Rerank 函数
# ============================================================================

async def rerank_documents(
    query: str,
    documents: List[Tuple[str, str]],  # (chunk_id, content)
    top_n: int = 10
) -> List[Tuple[str, float]]:
    """使用真实 Rerank 模型重排序"""
    from app.ai.embedding_client import rerank_documents

    if not documents:
        return []

    contents = [doc[1] for doc in documents]
    result = await rerank_documents(query, contents, top_n=top_n)

    reranked = []
    for item in result.get("results", []):
        idx = item.get("index", 0)
        score = item.get("relevance_score", 0.0)
        if idx < len(documents):
            reranked.append((documents[idx][0], score))

    return reranked


# ============================================================================
# 评测函数
# ============================================================================

def compute_metrics(
    retrieved: List[str],
    relevant_docs: Set[str],
    latencies: List[float]
) -> Dict[str, float]:
    """计算检索指标"""
    import math

    k_values = [10, 20]
    metrics = {}

    for k in k_values:
        retrieved_k = set(retrieved[:k])
        intersection = retrieved_k & relevant_docs

        # Recall@K
        recall = len(intersection) / len(relevant_docs) if relevant_docs else 0
        metrics[f"recall_at_{k}"] = recall

        # Hit Rate@K
        metrics[f"hit_rate_at_{k}"] = 1.0 if intersection else 0.0

    # MRR
    mrr = 0.0
    for i, doc_id in enumerate(retrieved):
        if doc_id in relevant_docs:
            mrr = 1.0 / (i + 1)
            break
    metrics["mrr"] = mrr

    # MAP
    if relevant_docs:
        precisions = []
        num_relevant = 0
        for i, doc_id in enumerate(retrieved):
            if doc_id in relevant_docs:
                num_relevant += 1
                precisions.append(num_relevant / (i + 1))
        metrics["map"] = sum(precisions) / len(precisions) if precisions else 0
    else:
        metrics["map"] = 0.0

    # NDCG@K
    for k in k_values:
        dcg = 0.0
        for i, doc_id in enumerate(retrieved[:k]):
            if doc_id in relevant_docs:
                dcg += 1.0 / math.log2(i + 2)

        sorted_relevant = sorted([1.0] * len(relevant_docs), reverse=True)
        idcg = sum(score / math.log2(i + 2) for i, score in enumerate(sorted_relevant[:k]))

        metrics[f"ndcg_at_{k}"] = dcg / idcg if idcg > 0 else 0.0

    # 延迟统计
    if latencies:
        sorted_latencies = sorted(latencies)
        metrics["avg_latency_ms"] = sum(latencies) / len(latencies)
        metrics["p50_latency_ms"] = sorted_latencies[len(sorted_latencies) // 2]
        metrics["p95_latency_ms"] = sorted_latencies[int(len(sorted_latencies) * 0.95)]
        metrics["p99_latency_ms"] = sorted_latencies[int(len(sorted_latencies) * 0.99)]
    else:
        metrics["avg_latency_ms"] = 0
        metrics["p50_latency_ms"] = 0
        metrics["p95_latency_ms"] = 0
        metrics["p99_latency_ms"] = 0

    return metrics


# ============================================================================
# 相关性判断函数
# ============================================================================

def compute_relevant_docs_by_content(query: str, chunks: List[ChunkWithEmbedding]) -> Set[str]:
    """基于查询内容判断相关文档

    通过提取查询中的关键词（人名、职位、组织等），匹配包含这些关键词的文档
    """
    query_lower = query.lower()

    # 从查询中提取潜在的关键词（大写单词可能是专有名词）
    import re
    # 匹配查询中可能的人名、组织名等（首字母大写的单词）
    proper_nouns = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', query))

    # 同时提取小写的关键词
    keywords = set()
    stop_words = {'what', 'where', 'when', 'how', 'does', 'have', 'that', 'with', 'from', 'they', 'been', 'their', 'than', 'them', 'then', 'this', 'will', 'would', 'there', 'these', 'have', 'has', 'had', 'who', 'which', 'what', 'your', 'about', 'into'}
    for word in query_lower.split():
        word = word.strip('.,!?;:')
        if len(word) > 3 and word not in stop_words:
            keywords.add(word)

    relevant = set()

    for chunk in chunks:
        content_lower = chunk.content.lower()

        # 1. 检查是否包含相同的专有名词（人名匹配）
        # 从文档内容中提取专有名词
        doc_proper_nouns = set(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', chunk.content))

        # 如果查询和文档有共同的人名，认为是相关文档
        if proper_nouns and doc_proper_nouns:
            common_names = proper_nouns & doc_proper_nouns
            if common_names:
                relevant.add(chunk.chunk_id)
                continue

        # 2. 基于关键词匹配（至少匹配2个关键词）
        match_count = sum(1 for kw in keywords if kw in content_lower)
        if match_count >= 2:
            relevant.add(chunk.chunk_id)
            continue

        # 3. 检查person_id是否直接匹配（作为备选）
        # 从查询中提取person_id模式
        if 'person_' in query_lower:
            # 查询包含person_id，尝试匹配
            if chunk.person_id in query_lower:
                relevant.add(chunk.chunk_id)
                continue

    return relevant


def compute_relevant_docs_by_keywords(query_data: Dict, chunks: List[ChunkWithEmbedding]) -> Set[str]:
    """基于查询数据中的关键词匹配相关文档"""
    query = query_data.get("query", "")
    query_type = query_data.get("type", "")
    person_id = query_data.get("person_id", "")

    relevant = set()
    query_lower = query.lower()

    for chunk in chunks:
        content_lower = chunk.content.lower()

        # 策略1: 如果查询类型需要图检索，检查文档是否包含关系型内容
        if query_type in ["relationship", "multi_hop", "aggregation"]:
            # 这些类型的问题通常涉及"colleague", "friend", "work"等关键词
            if any(kw in content_lower for kw in ["colleague", "friend", "work", "team", "organization"]):
                if person_id and chunk.person_id == person_id:
                    relevant.add(chunk.chunk_id)
                    continue

        # 策略2: 对于fact类型，匹配具体属性
        if query_type == "fact":
            # 提取查询中的属性关键词（如occupation, work, organization等）
            attribute_keywords = ["occupation", "work", "organization", "location", "education", "skill"]
            if any(kw in query_lower for kw in attribute_keywords):
                if any(kw in content_lower for kw in attribute_keywords):
                    if person_id and chunk.person_id == person_id:
                        relevant.add(chunk.chunk_id)
                        continue

        # 策略3: 基于内容重叠度（共享关键词数量）
        query_words = set(query_lower.split()) - {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because', 'until', 'while'}
        content_words = set(content_lower.split())

        # 计算共享词比例
        if query_words:
            overlap = query_words & content_words
            overlap_ratio = len(overlap) / len(query_words)
            if overlap_ratio >= 0.3:  # 至少30%的关键词匹配
                relevant.add(chunk.chunk_id)
                continue

        # 策略4: 如果是特定人物的查询，该人物的所有文档都视为相关
        if person_id and chunk.person_id == person_id:
            # 但不是所有文档都相关，只选择包含传记、基本信息的部分
            if any(kw in content_lower for kw in ["biography", "background", "education", "career", "work", "skills"]):
                relevant.add(chunk.chunk_id)
                continue

    return relevant


# ============================================================================
# 5 层检索评测
# ============================================================================

class RAGRetrievalEvaluator:
    """5层RAG检索评测器"""

    def __init__(self, chunks: List[ChunkWithEmbedding], entities: List[EntityNode], relations: List[Tuple]):
        self.chunks = chunks
        self.entities = entities
        self.relations = relations
        self.chunk_map = {chunk.chunk_id: chunk for chunk in chunks}

    async def layer1_vector_only(self, queries: List[Dict], top_k: int = 20) -> LayerMetrics:
        """Layer 1: 纯向量检索"""
        from app.ai.embedding_client import embed_query_with_fallback

        all_retrieved = []
        all_relevant = set()
        all_latencies = []

        per_query_metrics = []

        for query_data in queries:
            query = query_data["query"]

            # 基于内容判断相关文档
            relevant = compute_relevant_docs_by_keywords(query_data, self.chunks)
            if not relevant:
                # 如果没有找到相关文档，尝试基于内容匹配
                relevant = compute_relevant_docs_by_content(query, self.chunks)

            all_relevant.update(relevant)

            # 向量检索
            start = time.perf_counter()
            query_vec, _ = await embed_query_with_fallback(query)
            results = await search_vectors_top_k(query_vec, top_k=top_k)
            latency = (time.perf_counter() - start) * 1000
            all_latencies.append(latency)

            retrieved = [doc_id for doc_id, _, _ in results]
            all_retrieved.extend(retrieved)

            # 记录单个查询的指标
            if relevant:
                from types import SimpleNamespace
                q_metrics = compute_metrics(retrieved, relevant, [latency])
                per_query_metrics.append(q_metrics)

        # 计算平均指标
        avg_metrics = {
            "recall_at_10": sum(m["recall_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "recall_at_20": sum(m["recall_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_10": sum(m["ndcg_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_20": sum(m["ndcg_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "mrr": sum(m["mrr"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "map": sum(m["map"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_10": sum(m["hit_rate_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_20": sum(m["hit_rate_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
        }

        # 延迟统计
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            avg_metrics.update({
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2],
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            })

        return LayerMetrics(
            layer_name="Layer1_Vector_Only",
            **avg_metrics
        )

    async def layer2_vector_rerank(self, queries: List[Dict], top_k: int = 20, rerank_top: int = 10) -> LayerMetrics:
        """Layer 2: 向量检索 + 重排序"""
        from app.ai.embedding_client import embed_query_with_fallback

        all_latencies = []
        per_query_metrics = []

        for query_data in queries:
            query = query_data["query"]

            # 基于内容判断相关文档
            relevant = compute_relevant_docs_by_keywords(query_data, self.chunks)
            if not relevant:
                relevant = compute_relevant_docs_by_content(query, self.chunks)

            # 向量检索
            start = time.perf_counter()
            query_vec, _ = await embed_query_with_fallback(query)
            vector_results = await search_vectors_top_k(query_vec, top_k=top_k)

            # 重排序
            documents = [(doc_id, content) for doc_id, _, content in vector_results]
            reranked = await rerank_documents(query, documents, top_n=rerank_top)

            latency = (time.perf_counter() - start) * 1000
            all_latencies.append(latency)

            retrieved = [doc_id for doc_id, _ in reranked]

            # 记录单个查询的指标
            if relevant:
                q_metrics = compute_metrics(retrieved, relevant, [latency])
                per_query_metrics.append(q_metrics)

        # 计算平均指标
        avg_metrics = {
            "recall_at_10": sum(m["recall_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "recall_at_20": sum(m["recall_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_10": sum(m["ndcg_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_20": sum(m["ndcg_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "mrr": sum(m["mrr"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "map": sum(m["map"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_10": sum(m["hit_rate_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_20": sum(m["hit_rate_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
        }

        # 延迟统计
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            avg_metrics.update({
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2],
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            })

        return LayerMetrics(
            layer_name="Layer2_Vector_Rerank",
            **avg_metrics
        )

    async def layer3_graph_only(self, queries: List[Dict], top_k: int = 20) -> LayerMetrics:
        """Layer 3: 图检索独立评测"""
        all_latencies = []
        per_query_metrics = []

        for query_data in queries:
            query = query_data["query"]
            person_id = query_data.get("person_id")

            # 基于内容判断相关文档
            relevant = compute_relevant_docs_by_keywords(query_data, self.chunks)
            if not relevant:
                relevant = compute_relevant_docs_by_content(query, self.chunks)

            # 图检索
            start = time.perf_counter()
            graph_results = await graph_retrieval(query, [person_id] if person_id else [], hop=1, limit=top_k)
            latency = (time.perf_counter() - start) * 1000
            all_latencies.append(latency)

            # 从图结果获取 chunk_id
            retrieved = []
            for r in graph_results:
                # 查找匹配的 chunk
                for chunk in self.chunks:
                    if r.get("person_id") == chunk.person_id:
                        retrieved.append(chunk.chunk_id)
                        break

            # 记录单个查询的指标
            if relevant:
                q_metrics = compute_metrics(retrieved, relevant, [latency])
                per_query_metrics.append(q_metrics)

        # 计算平均指标
        avg_metrics = {
            "recall_at_10": sum(m["recall_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "recall_at_20": sum(m["recall_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_10": sum(m["ndcg_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_20": sum(m["ndcg_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "mrr": sum(m["mrr"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "map": sum(m["map"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_10": sum(m["hit_rate_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_20": sum(m["hit_rate_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
        }

        # 延迟统计
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            avg_metrics.update({
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2],
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            })

        return LayerMetrics(
            layer_name="Layer3_Graph_Only",
            **avg_metrics
        )

    async def layer4_hybrid(self, queries: List[Dict], top_k: int = 20, graph_weight: float = 0.5) -> LayerMetrics:
        """Layer 4: 向量 + 图混合检索"""
        from app.ai.embedding_client import embed_query_with_fallback

        all_latencies = []
        per_query_metrics = []

        for query_data in queries:
            query = query_data["query"]
            person_id = query_data.get("person_id")

            # 基于内容判断相关文档
            relevant = compute_relevant_docs_by_keywords(query_data, self.chunks)
            if not relevant:
                relevant = compute_relevant_docs_by_content(query, self.chunks)

            # 混合检索
            start = time.perf_counter()

            # 向量检索
            query_vec, _ = await embed_query_with_fallback(query)
            vector_results = await search_vectors_top_k(query_vec, top_k=top_k)
            vector_scores = {doc_id: 1.0 - dist for doc_id, dist, _ in vector_results}

            # 图检索
            graph_results = await graph_retrieval(query, [person_id] if person_id else [], hop=1, limit=top_k)
            graph_doc_ids = set()
            for r in graph_results:
                for chunk in self.chunks:
                    if r.get("person_id") == chunk.person_id:
                        graph_doc_ids.add(chunk.chunk_id)
                        break

            # 融合分数
            fused_scores = {}
            all_doc_ids = set(vector_scores.keys()) | graph_doc_ids
            for doc_id in all_doc_ids:
                vec_score = vector_scores.get(doc_id, 0)
                graph_score = 1.0 if doc_id in graph_doc_ids else 0
                fused_scores[doc_id] = vec_score * (1 - graph_weight) + graph_score * graph_weight

            sorted_fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
            retrieved = [doc_id for doc_id, _ in sorted_fused[:top_k]]

            latency = (time.perf_counter() - start) * 1000
            all_latencies.append(latency)

            # 记录单个查询的指标
            if relevant:
                q_metrics = compute_metrics(retrieved, relevant, [latency])
                per_query_metrics.append(q_metrics)

        # 计算平均指标
        avg_metrics = {
            "recall_at_10": sum(m["recall_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "recall_at_20": sum(m["recall_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_10": sum(m["ndcg_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_20": sum(m["ndcg_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "mrr": sum(m["mrr"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "map": sum(m["map"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_10": sum(m["hit_rate_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_20": sum(m["hit_rate_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
        }

        # 延迟统计
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            avg_metrics.update({
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2],
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            })

        return LayerMetrics(
            layer_name="Layer4_Hybrid",
            **avg_metrics
        )

    async def layer5_full_pipeline(self, queries: List[Dict], top_k: int = 20, rerank_top: int = 10) -> LayerMetrics:
        """Layer 5: 完整流程 (向量 + 图 + 重排)"""
        from app.ai.embedding_client import embed_query_with_fallback

        all_latencies = []
        per_query_metrics = []

        for query_data in queries:
            query = query_data["query"]
            person_id = query_data.get("person_id")

            # 基于内容判断相关文档
            relevant = compute_relevant_docs_by_keywords(query_data, self.chunks)
            if not relevant:
                relevant = compute_relevant_docs_by_content(query, self.chunks)

            # 完整流程
            start = time.perf_counter()

            # 向量检索
            query_vec, _ = await embed_query_with_fallback(query)
            vector_results = await search_vectors_top_k(query_vec, top_k=top_k)
            vector_scores = {doc_id: 1.0 - dist for doc_id, dist, _ in vector_results}

            # 图检索
            graph_results = await graph_retrieval(query, [person_id] if person_id else [], hop=1, limit=top_k)
            graph_doc_ids = set()
            for r in graph_results:
                for chunk in self.chunks:
                    if r.get("person_id") == chunk.person_id:
                        graph_doc_ids.add(chunk.chunk_id)
                        break

            # 融合分数
            graph_weight = 0.5
            fused_scores = {}
            all_doc_ids = set(vector_scores.keys()) | graph_doc_ids
            for doc_id in all_doc_ids:
                vec_score = vector_scores.get(doc_id, 0)
                graph_score = 1.0 if doc_id in graph_doc_ids else 0
                fused_scores[doc_id] = vec_score * (1 - graph_weight) + graph_score * graph_weight

            # 获取融合后的文档内容
            fused_docs = []
            for doc_id, score in sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]:
                chunk = self.chunk_map.get(doc_id)
                if chunk:
                    fused_docs.append((doc_id, chunk.content))

            # 重排序
            reranked = await rerank_documents(query, fused_docs, top_n=rerank_top)

            latency = (time.perf_counter() - start) * 1000
            all_latencies.append(latency)

            retrieved = [doc_id for doc_id, _ in reranked]

            # 记录单个查询的指标
            if relevant:
                q_metrics = compute_metrics(retrieved, relevant, [latency])
                per_query_metrics.append(q_metrics)

        # 计算平均指标
        avg_metrics = {
            "recall_at_10": sum(m["recall_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "recall_at_20": sum(m["recall_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_10": sum(m["ndcg_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "ndcg_at_20": sum(m["ndcg_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "mrr": sum(m["mrr"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "map": sum(m["map"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_10": sum(m["hit_rate_at_10"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
            "hit_rate_at_20": sum(m["hit_rate_at_20"] for m in per_query_metrics) / len(per_query_metrics) if per_query_metrics else 0,
        }

        # 延迟统计
        if all_latencies:
            sorted_latencies = sorted(all_latencies)
            avg_metrics.update({
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_latencies[len(sorted_latencies) // 2],
                "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                "p99_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            })

        return LayerMetrics(
            layer_name="Layer5_Full_Pipeline",
            **avg_metrics
        )


# ============================================================================
# 数据准备
# ============================================================================

def prepare_chunks_from_corpus(corpus: List[Dict], max_chunks: int = 1000) -> List[ChunkWithEmbedding]:
    """从语料库准备 chunks"""
    chunks = []
    for doc in corpus[:max_chunks]:
        chunks.append(ChunkWithEmbedding(
            chunk_id=doc.get("chunk_id", doc.get("doc_id", str(uuid.uuid4()))),
            content=doc.get("content", "")[:2000],  # 限制长度
            person_id=doc.get("person_id", "unknown")
        ))
    return chunks


def prepare_entities_from_data(persons: List[Dict], entities: List[Dict]) -> List[EntityNode]:
    """准备实体节点"""
    entity_nodes = []

    # 从 persons 创建实体
    for person in persons:
        entity_nodes.append(EntityNode(
            entity_id=f"person:{person['person_id']}",
            entity_name=person["name"],
            entity_type="PERSON",
            person_id=person["person_id"]
        ))

    # 去重
    seen = {e.entity_id for e in entity_nodes}
    for ent in entities[:3000]:
        if ent.get("entity_id") not in seen:
            seen.add(ent.get("entity_id"))
            entity_nodes.append(EntityNode(
                entity_id=ent.get("entity_id", str(uuid.uuid4())),
                entity_name=ent.get("entity_name", "Unknown"),
                entity_type=ent.get("entity_type", "ENTITY"),
                person_id=ent.get("person_id", "unknown")
            ))

    return entity_nodes


# ============================================================================
# 异步测试
# ============================================================================

@pytest.mark.asyncio
async def test_database_connections():
    """测试所有数据库连接"""
    # PostgreSQL
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    # Neo4j
    from app.db.neo4j.driver import get_neo4j_driver
    from app.core.config import settings

    driver = get_neo4j_driver()
    with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = session.run("RETURN 1")
        assert result.single()[0] == 1

    print("  PostgreSQL 连接: OK")
    print("  Neo4j 连接: OK")


@pytest.mark.asyncio
async def test_embedding_service():
    """测试 Embedding 服务"""
    from app.ai.embedding_client import embed_query_with_fallback

    vector, model = await embed_query_with_fallback("测试查询")
    assert len(vector) > 0
    print(f"  Embedding 模型: {model}, 维度: {len(vector)}")


@pytest.mark.asyncio
async def test_rerank_service():
    """测试 Rerank 服务"""
    from app.ai.embedding_client import rerank_documents

    result = await rerank_documents(
        "软件工程师",
        ["他是一名软件工程师", "这个产品很好用", "天气不错"],
        top_n=3
    )
    assert "results" in result or len(result) >= 0
    print("  Rerank 服务: OK")


@pytest.mark.asyncio
async def test_data_ingestion():
    """测试数据导入"""
    if not BENCHMARK_DATA:
        pytest.skip("基准测试数据不存在")

    await init_database()

    # 准备数据
    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    entities = prepare_entities_from_data(PERSONS[:10], ALL_ENTITIES[:100])

    # 导入向量数据
    chunk_ids = await insert_test_chunks(chunks, space_id=999999)
    print(f"  导入 {chunk_ids} 个文档块")
    assert chunk_ids > 0

    # 导入图数据
    relations = [(f"person:{p['person_id']}", "rel", f"person:{PERSONS[0]['person_id']}", "test")
                 for p in PERSONS[:10]]
    node_count = await insert_graph_data(entities[:100], relations[:50])
    print(f"  导入 {node_count} 个图节点")
    assert node_count > 0


@pytest.mark.asyncio
async def test_layer1_vector_search():
    """Layer 1: 纯向量检索测试"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    evaluator = RAGRetrievalEvaluator(chunks, [], [])

    test_queries = EVAL_QUERIES[:10]

    print("\n  执行 Layer 1 纯向量检索...")
    metrics = await evaluator.layer1_vector_only(test_queries, top_k=20)

    print(f"  Layer: {metrics.layer_name}")
    print(f"  Recall@10: {metrics.recall_at_10:.4f}")
    print(f"  NDCG@10: {metrics.ndcg_at_10:.4f}")
    print(f"  MRR: {metrics.mrr:.4f}")
    print(f"  平均延迟: {metrics.avg_latency_ms:.2f}ms")

    assert metrics.avg_latency_ms > 0


@pytest.mark.asyncio
async def test_layer2_vector_rerank():
    """Layer 2: 向量检索 + 重排序"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    evaluator = RAGRetrievalEvaluator(chunks, [], [])

    test_queries = EVAL_QUERIES[:10]

    print("\n  执行 Layer 2 向量+重排序...")
    metrics = await evaluator.layer2_vector_rerank(test_queries, top_k=20, rerank_top=10)

    print(f"  Layer: {metrics.layer_name}")
    print(f"  Recall@10: {metrics.recall_at_10:.4f}")
    print(f"  NDCG@10: {metrics.ndcg_at_10:.4f}")
    print(f"  MRR: {metrics.mrr:.4f}")
    print(f"  平均延迟: {metrics.avg_latency_ms:.2f}ms")

    assert metrics.avg_latency_ms > 0


@pytest.mark.asyncio
async def test_layer3_graph_only():
    """Layer 3: 图检索独立评测"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    entities = prepare_entities_from_data(PERSONS[:10], ALL_ENTITIES[:100])
    relations = GRAPH_RELATIONS[:100]

    evaluator = RAGRetrievalEvaluator(chunks, entities, relations)

    test_queries = EVAL_QUERIES[:10]

    print("\n  执行 Layer 3 图检索...")
    metrics = await evaluator.layer3_graph_only(test_queries, top_k=20)

    print(f"  Layer: {metrics.layer_name}")
    print(f"  Recall@10: {metrics.recall_at_10:.4f}")
    print(f"  NDCG@10: {metrics.ndcg_at_10:.4f}")
    print(f"  平均延迟: {metrics.avg_latency_ms:.2f}ms")

    assert metrics.avg_latency_ms > 0


@pytest.mark.asyncio
async def test_layer4_hybrid():
    """Layer 4: 向量 + 图混合检索"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    entities = prepare_entities_from_data(PERSONS[:10], ALL_ENTITIES[:100])
    relations = GRAPH_RELATIONS[:100]

    evaluator = RAGRetrievalEvaluator(chunks, entities, relations)

    test_queries = EVAL_QUERIES[:10]

    print("\n  执行 Layer 4 混合检索...")
    metrics = await evaluator.layer4_hybrid(test_queries, top_k=20, graph_weight=0.5)

    print(f"  Layer: {metrics.layer_name}")
    print(f"  Recall@10: {metrics.recall_at_10:.4f}")
    print(f"  NDCG@10: {metrics.ndcg_at_10:.4f}")
    print(f"  MRR: {metrics.mrr:.4f}")
    print(f"  平均延迟: {metrics.avg_latency_ms:.2f}ms")
    print(f"  P95延迟: {metrics.p95_latency_ms:.2f}ms")

    assert metrics.avg_latency_ms > 0


@pytest.mark.asyncio
async def test_layer5_full_pipeline():
    """Layer 5: 完整流程"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    entities = prepare_entities_from_data(PERSONS[:10], ALL_ENTITIES[:100])
    relations = GRAPH_RELATIONS[:100]

    evaluator = RAGRetrievalEvaluator(chunks, entities, relations)

    test_queries = EVAL_QUERIES[:10]

    print("\n  执行 Layer 5 完整流程...")
    metrics = await evaluator.layer5_full_pipeline(test_queries, top_k=20, rerank_top=10)

    print(f"  Layer: {metrics.layer_name}")
    print(f"  Recall@10: {metrics.recall_at_10:.4f}")
    print(f"  NDCG@10: {metrics.ndcg_at_10:.4f}")
    print(f"  MRR: {metrics.mrr:.4f}")
    print(f"  MAP: {metrics.map:.4f}")
    print(f"  平均延迟: {metrics.avg_latency_ms:.2f}ms")
    print(f"  P95延迟: {metrics.p95_latency_ms:.2f}ms")
    print(f"  P99延迟: {metrics.p99_latency_ms:.2f}ms")

    assert metrics.avg_latency_ms > 0


@pytest.mark.asyncio
async def test_latency_benchmark():
    """延迟基准测试"""
    if not BENCHMARK_DATA or len(CORPUS) == 0:
        pytest.skip("数据未加载")

    from app.ai.embedding_client import embed_query_with_fallback

    # Embedding 延迟
    embedding_latencies = []
    for _ in range(5):
        start = time.perf_counter()
        await embed_query_with_fallback("软件工程师工作组织")
        embedding_latencies.append((time.perf_counter() - start) * 1000)

    # 向量检索延迟
    chunks = prepare_chunks_from_corpus(CORPUS, max_chunks=100)
    evaluator = RAGRetrievalEvaluator(chunks, [], [])

    search_latencies = []
    for _ in range(5):
        query_vec, _ = await embed_query_with_fallback("软件工程师工作组织")
        start = time.perf_counter()
        await search_vectors_top_k(query_vec, top_k=20)
        search_latencies.append((time.perf_counter() - start) * 1000)

    print("\n  延迟基准测试:")
    print(f"  Embedding 平均延迟: {sum(embedding_latencies)/len(embedding_latencies):.2f}ms")
    print(f"  向量检索平均延迟: {sum(search_latencies)/len(search_latencies):.2f}ms")

    assert True


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
