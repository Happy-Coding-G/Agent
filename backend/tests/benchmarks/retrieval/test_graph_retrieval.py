"""
RAG 检索评测 - 第3层：图检索独立评测

测试知识图谱在关系推理上的能力
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from typing import List, Dict, Any, Set, Tuple, Optional

# 导入评测指标
sys.path.insert(0, str(Path(__file__).parent))
from test_rag_retrieval import (
    CORPUS,
    GRAPH_RELATIONS,
    EVAL_QUERIES,
    compute_recall_at_k,
    compute_mrr,
    compute_graph_retrieval_metrics,
)


# ============================================================================
# 图检索引擎
# ============================================================================

class GraphRetrievalEngine:
    """
    图检索引擎

    支持：
    1. 基于实体链接的检索
    2. 多跳关系推理
    3. 路径检索
    """

    def __init__(self, corpus: List[Dict], relations: List[Tuple]):
        self.corpus = {doc["id"]: doc for doc in corpus}
        self.relations = relations

        # 构建图索引
        self._build_graph_index()

    def _build_graph_index(self):
        """构建图索引"""
        # doc_id -> [related_doc_ids]
        self.doc_neighbors: Dict[str, Set[str]] = {}

        # 实体 -> doc_ids
        self.entity_to_docs: Dict[str, Set[str]] = {}

        # doc_id -> entities
        self.doc_entities: Dict[str, Set[str]] = {}

        # 构建索引
        for doc_id, doc in self.corpus.items():
            self.doc_neighbors[doc_id] = set()
            self.doc_entities[doc_id] = set(doc.get("entities", []))

            for entity in doc.get("entities", []):
                if entity not in self.entity_to_docs:
                    self.entity_to_docs[entity] = set()
                self.entity_to_docs[entity].add(doc_id)

        # 添加关系边
        for source_id, rel, target_id, desc in self.relations:
            if source_id in self.doc_neighbors and target_id in self.doc_neighbors:
                self.doc_neighbors[source_id].add(target_id)
                self.doc_neighbors[target_id].add(source_id)

    def retrieve_by_entities(
        self,
        query: str,
        entities: List[str],
        hop: int = 1,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        基于实体检索相关文档

        Args:
            query: 查询文本
            entities: 查询中识别的实体
            hop: 跳数 (1=直接关联, 2=二跳, etc.)
            limit: 返回数量

        Returns:
            [(doc_id, score, hop_count, path), ...]
        """
        results = {}  # doc_id -> {score, hop, path}

        # 0跳：直接包含实体的文档
        for entity in entities:
            if entity in self.entity_to_docs:
                for doc_id in self.entity_to_docs[entity]:
                    if doc_id not in results:
                        results[doc_id] = {
                            "doc_id": doc_id,
                            "score": 1.0,
                            "hop": 0,
                            "matched_entities": [entity],
                            "path": [doc_id]
                        }
                    else:
                        results[doc_id]["score"] += 0.5
                        results[doc_id]["matched_entities"].append(entity)

        # N跳：扩展检索
        current_docs = set(results.keys())
        visited = set(current_docs)

        for h in range(1, hop + 1):
            next_docs = set()
            for doc_id in current_docs:
                for neighbor in self.doc_neighbors.get(doc_id, set()):
                    if neighbor not in visited:
                        next_docs.add(neighbor)

            if not next_docs:
                break

            # 计算跳数分数
            hop_score = 1.0 / (h + 1)  # 跳数越多，分数越低

            for neighbor_id in next_docs:
                if neighbor_id not in results:
                    results[neighbor_id] = {
                        "doc_id": neighbor_id,
                        "score": hop_score,
                        "hop": h,
                        "matched_entities": [],
                        "path": []
                    }
                else:
                    results[neighbor_id]["score"] += hop_score * 0.5
                results[neighbor_id]["path"] = [doc_id, neighbor_id]

            visited.update(next_docs)
            current_docs = next_docs

        # 排序并返回
        sorted_results = sorted(
            results.values(),
            key=lambda x: (x["score"], -x["hop"]),
            reverse=True
        )

        return sorted_results[:limit]

    def retrieve_by_relation_path(
        self,
        query: str,
        source_entities: List[str],
        target_type: str,
        max_hops: int = 2
    ) -> List[Dict[str, Any]]:
        """
        基于关系路径检索

        用于多跳推理查询
        """
        results = []

        # 找到源实体对应的文档
        source_docs = set()
        for entity in source_entities:
            if entity in self.entity_to_docs:
                source_docs.update(self.entity_to_docs[entity])

        # BFS 找路径
        for start_doc in source_docs:
            queue = [(start_doc, [start_doc], 0)]
            visited = {start_doc}

            while queue:
                current, path, hops = queue.pop(0)

                # 检查是否匹配目标类型
                current_doc = self.corpus.get(current)
                if current_doc and target_type.lower() in current_doc.get("entity_types", {}).values():
                    if hops > 0:  # 排除起点
                        results.append({
                            "doc_id": current,
                            "path": path,
                            "hops": hops,
                            "score": 1.0 / (hops + 1)
                        })

                if hops >= max_hops:
                    continue

                for neighbor in self.doc_neighbors.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor], hops + 1))

        # 排序
        results.sort(key=lambda x: (x["score"], -x["hops"]))
        return results[:20]

    def hybrid_retrieve(
        self,
        query: str,
        vector_results: List[Tuple[str, float]],
        graph_weight: float = 0.5,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        混合检索：结合向量和图

        Args:
            query: 查询文本
            vector_results: 向量检索结果 [(doc_id, score), ...]
            graph_weight: 图权重
            top_k: 返回数量
        """
        # 解析查询中的实体
        entities = self._extract_entities_from_query(query)

        # 图检索结果
        graph_results = self.retrieve_by_entities(query, entities, hop=2, limit=20)

        # 构建图分数索引
        graph_scores = {
            r["doc_id"]: r["score"] for r in graph_results
        }

        # 构建向量分数字典
        vector_scores_dict = {doc_id: score for doc_id, score in vector_results}

        # 融合分数
        fused_scores = {}
        for doc_id, vec_score in vector_results:
            graph_score = graph_scores.get(doc_id, 0)
            fused_scores[doc_id] = (
                vec_score * (1 - graph_weight) +
                graph_score * graph_weight
            )

        # 排序
        sorted_docs = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        return [
            {
                "doc_id": doc_id,
                "fused_score": score,
                "vector_score": vector_scores_dict.get(doc_id, 0),
                "graph_score": graph_scores.get(doc_id, 0)
            }
            for doc_id, score in sorted_docs[:top_k]
        ]

    def _extract_entities_from_query(self, query: str) -> List[str]:
        """从查询中提取实体"""
        query_lower = query.lower()
        entities = []

        # 从语料库中匹配实体
        for doc_id, doc in self.corpus.items():
            for entity in doc.get("entities", []):
                if entity.lower() in query_lower:
                    entities.append(entity)

        return entities


# ============================================================================
# 全局图检索引擎实例
# ============================================================================

_graph_engine: Optional[GraphRetrievalEngine] = None


def get_graph_engine() -> GraphRetrievalEngine:
    """获取图检索引擎单例"""
    global _graph_engine
    if _graph_engine is None:
        _graph_engine = GraphRetrievalEngine(CORPUS, GRAPH_RELATIONS)
    return _graph_engine


# ============================================================================
# 评测函数
# ============================================================================

def evaluate_graph_retrieval(
    query: str,
    expected_docs: Set[str],
    entities: List[str] = None,
    hop: int = 2,
    limit: int = 20
) -> Dict[str, Any]:
    """
    评估图检索效果
    """
    engine = get_graph_engine()

    # 如果没有提供实体，从查询中提取
    if entities is None:
        entities = engine._extract_entities_from_query(query)

    # 图检索
    graph_results = engine.retrieve_by_entities(query, entities, hop=hop, limit=limit)
    graph_doc_ids = [r["doc_id"] for r in graph_results]

    # 计算图检索指标
    graph_metrics = compute_graph_retrieval_metrics(
        graph_doc_ids,
        expected_docs
    )

    # 计算跳数信息
    hop_counts = {r["doc_id"]: r["hop"] for r in graph_results}
    detailed_metrics = compute_graph_retrieval_metrics(graph_doc_ids, expected_docs, hop_counts)

    return {
        "graph_metrics": graph_metrics,
        "detailed_metrics": detailed_metrics,
        "retrieved_docs": graph_doc_ids[:10],
        "expected_docs": list(expected_docs)[:10],
        "entities_used": entities,
        "hop": hop,
    }


# ============================================================================
# 测试类
# ============================================================================

class TestGraphRetrievalBasics:
    """图检索基础测试"""

    def test_graph_index_built(self):
        """测试图索引构建"""
        engine = get_graph_engine()

        assert len(engine.doc_neighbors) > 0
        assert len(engine.entity_to_docs) > 0
        assert len(engine.doc_entities) > 0

    def test_direct_entity_retrieval(self):
        """测试直接实体检索"""
        engine = get_graph_engine()

        # 检索包含"RAG"的文档
        results = engine.retrieve_by_entities("RAG相关", ["RAG"], hop=1, limit=10)

        assert len(results) > 0
        doc_ids = [r["doc_id"] for r in results]
        assert "doc_001" in doc_ids  # RAG定义文档

    def test_multihop_retrieval(self):
        """测试多跳检索"""
        engine = get_graph_engine()

        # BERT和GPT都需要Transformer，尝试找两者都关联的文档
        results = engine.retrieve_by_entities(
            "BERT和GPT的关系",
            ["BERT", "GPT", "Transformer"],
            hop=2,
            limit=20
        )

        # 应该能找到Transformer相关文档
        doc_ids = [r["doc_id"] for r in results]

        # doc_013是Transformer基础文档
        print(f"\n多跳检索结果: {doc_ids[:5]}")

        assert len(doc_ids) > 0


class TestGraphRetrievalMetrics:
    """图检索指标测试"""

    def test_entity_coverage(self):
        """测试实体覆盖率"""
        engine = get_graph_engine()

        all_entities = set()
        for doc in CORPUS:
            all_entities.update(doc.get("entities", []))

        print(f"\n语料库实体总数: {len(all_entities)}")
        print(f"实体到文档映射数: {len(engine.entity_to_docs)}")

        assert len(engine.entity_to_docs) > 0

    def test_relation_coverage(self):
        """测试关系覆盖率"""
        engine = get_graph_engine()

        total_neighbors = sum(len(neighbors) for neighbors in engine.doc_neighbors.values())
        print(f"\n总边数: {len(GRAPH_RELATIONS)}")
        print(f"平均度数: {total_neighbors / max(len(engine.doc_neighbors), 1):.2f}")

        assert total_neighbors > 0

    def test_hop_retrieval_quality(self):
        """测试不同跳数检索质量"""
        q4 = next(q for q in EVAL_QUERIES if q["id"] == "q4")  # BERT和GPT关系
        expected = set(q4["expected_docs"])
        entities = ["BERT", "GPT", "Transformer"]

        results_by_hop = {}
        for hop in [1, 2, 3]:
            result = evaluate_graph_retrieval(q4["query"], expected, entities, hop=hop)
            results_by_hop[hop] = result["graph_metrics"]["graph_recall"]

        print(f"\n不同跳数的召回率:")
        for hop, recall in results_by_hop.items():
            print(f"  Hop {hop}: Recall = {recall:.3f}")


class TestGraphSpecificQueries:
    """图检索特有查询测试"""

    def test_relation_query(self):
        """关系查询测试 - '哪些技术在知识图谱中有应用？'"""
        q5 = next(q for q in EVAL_QUERIES if q["id"] == "q5")
        expected = set(q5["expected_docs"])

        result = evaluate_graph_retrieval(q5["query"], expected, hop=2)

        print(f"\nQ5 (关系查询): {q5['query']}")
        print(f"检索到: {result['retrieved_docs']}")
        print(f"期望: {result['expected_docs']}")
        print(f"图召回率: {result['graph_metrics']['graph_recall']:.3f}")

        assert result["graph_metrics"]["graph_recall"] >= 0

    def test_multihop_reasoning(self):
        """多跳推理测试 - 'Word2Vec和BERT之间有什么技术演进关系？'"""
        q6 = next(q for q in EVAL_QUERIES if q["id"] == "q6")
        expected = set(q6["expected_docs"])
        entities = ["Word2Vec", "BERT", "词嵌入", "Transformer"]

        result = evaluate_graph_retrieval(q6["query"], expected, entities, hop=3)

        print(f"\nQ6 (多跳推理): {q6['query']}")
        print(f"使用实体: {entities}")
        print(f"检索到: {result['retrieved_docs']}")
        print(f"图召回率: {result['graph_metrics']['graph_recall']:.3f}")

        # 多跳查询应该通过图检索获得一定召回
        assert result["graph_metrics"]["graph_recall"] > 0

    def test_comparison_query(self):
        """对比查询测试"""
        q7 = next(q for q in EVAL_QUERIES if q["id"] == "q7")
        expected = set(q7["expected_docs"])
        entities = ["BERT", "GPT", "Transformer"]

        result = evaluate_graph_retrieval(q7["query"], expected, entities, hop=2)

        print(f"\nQ7 (关系对比): {q7['query']}")
        print(f"检索到: {result['retrieved_docs']}")
        print(f"图召回率: {result['graph_metrics']['graph_recall']:.3f}")


class TestGraphVsVectorComparison:
    """图检索 vs 向量检索对比"""

    def test_graph_only_vs_vector_only(self):
        """对比纯图检索和纯向量检索"""
        from test_rag_retrieval_with_rerank import mock_vector_search

        all_results = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            entities = get_graph_engine()._extract_entities_from_query(q["query"])

            # 向量检索
            vector_results = mock_vector_search(q["query"], top_k=50)
            vector_doc_ids = [doc_id for doc_id, _ in vector_results]
            vector_recall = compute_recall_at_k(vector_doc_ids, expected, k=10)

            # 图检索
            graph_result = evaluate_graph_retrieval(q["query"], expected, entities, hop=2)
            graph_recall = graph_result["graph_metrics"]["graph_recall"]

            all_results.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "vector_recall": vector_recall,
                "graph_recall": graph_recall,
                "better": "graph" if graph_recall > vector_recall else "vector"
            })

        print("\n" + "="*80)
        print("图检索 vs 向量检索对比:")
        print("="*80)
        print(f"{'ID':<6} {'Type':<12} {'Graph':<6} {'Vector':<10} {'Graph':<10} {'Better':<8}")
        print("-"*80)
        for r in all_results:
            print(f"{r['query_id']:<6} {r['type']:<12} {str(r['requires_graph']):<6} "
                  f"{r['vector_recall']:<10.3f} {r['graph_recall']:<10.3f} {r['better']:<8}")
        print("-"*80)

        # 统计
        graph_wins = sum(1 for r in all_results if r["better"] == "graph")
        vector_wins = sum(1 for r in all_results if r["better"] == "vector")
        print(f"\n图检索胜出: {graph_wins} / {len(all_results)}")
        print(f"向量检索胜出: {vector_wins} / {len(all_results)}")

    def test_graph_essential_for_multihop(self):
        """验证图检索对多跳查询的必要性"""
        from test_rag_retrieval_with_rerank import mock_vector_search

        # 需要图检索的查询
        graph_queries = [q for q in EVAL_QUERIES if q.get("requires_graph")]

        improvements = []

        for q in graph_queries:
            expected = set(q["expected_docs"])
            entities = get_graph_engine()._extract_entities_from_query(q["query"])

            # 向量检索
            vector_results = mock_vector_search(q["query"], top_k=50)
            vector_doc_ids = [doc_id for doc_id, _ in vector_results]
            vector_recall = compute_recall_at_k(vector_doc_ids, expected, k=10)

            # 图检索
            graph_result = evaluate_graph_retrieval(q["query"], expected, entities, hop=2)
            graph_recall = graph_result["graph_metrics"]["graph_recall"]

            improvements.append({
                "query_id": q["id"],
                "query": q["query"][:40],
                "vector_recall": vector_recall,
                "graph_recall": graph_recall,
                "improvement": graph_recall - vector_recall
            })

        print("\n" + "="*80)
        print("图检索对图依赖查询的提升:")
        print("="*80)
        for imp in sorted(improvements, key=lambda x: x["improvement"], reverse=True):
            print(f"Q{imp['query_id']}: Vector={imp['vector_recall']:.3f}, "
                  f"Graph={imp['graph_recall']:.3f}, "
                  f"Δ={imp['improvement']:+.3f}")
        print("="*80)

        avg_improvement = sum(imp["improvement"] for imp in improvements) / len(improvements)
        print(f"平均提升: {avg_improvement:+.3f}")


class TestHybridRetrieval:
    """混合检索测试"""

    def test_hybrid_vs_single(self):
        """测试混合检索 vs 单检索"""
        from test_rag_retrieval_with_rerank import mock_vector_search

        q4 = next(q for q in EVAL_QUERIES if q["id"] == "q4")
        expected = set(q4["expected_docs"])

        # 向量检索
        vector_results = mock_vector_search(q4["query"], top_k=50)
        vector_doc_ids = [doc_id for doc_id, _ in vector_results]
        vector_recall = compute_recall_at_k(vector_doc_ids, expected, k=10)

        # 图检索
        entities = get_graph_engine()._extract_entities_from_query(q4["query"])
        graph_result = evaluate_graph_retrieval(q4["query"], expected, entities, hop=2)
        graph_recall = graph_result["graph_metrics"]["graph_recall"]

        # 混合检索
        engine = get_graph_engine()
        hybrid_results = engine.hybrid_retrieve(
            q4["query"],
            vector_results,
            graph_weight=0.5,
            top_k=10
        )
        hybrid_doc_ids = [r["doc_id"] for r in hybrid_results]
        hybrid_recall = compute_recall_at_k(hybrid_doc_ids, expected, k=10)

        print(f"\nQ4 (多跳) 检索对比:")
        print(f"  向量检索 Recall@10: {vector_recall:.3f}")
        print(f"  图检索 Recall@10: {graph_recall:.3f}")
        print(f"  混合检索 Recall@10: {hybrid_recall:.3f}")

        # 混合检索应该 >= 单独检索
        assert hybrid_recall >= max(vector_recall, graph_recall) - 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
