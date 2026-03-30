"""
RAG 检索评测 - 第4&5层：混合检索 + 完整流程

第4层：向量 + 图混合检索
第5层：完整流程 (向量 + 图 + 重排)
"""
import sys
from pathlib import Path

# 将tests目录加入path
tests_dir = str(Path(__file__).parent)
backend_dir = str(Path(__file__).parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

import pytest
from typing import List, Dict, Any, Set, Tuple

# 导入评测指标和工具
from test_rag_retrieval import (
    CORPUS,
    GRAPH_RELATIONS,
    EVAL_QUERIES,
    compute_recall_at_k,
    compute_ndcg_at_k,
    compute_mrr,
    compute_map,
    compute_hybrid_metrics,
)
from test_rag_retrieval_with_rerank import mock_vector_search, mock_rerank
from test_graph_retrieval import get_graph_engine, GraphRetrievalEngine


# ============================================================================
# 融合策略
# ============================================================================

def reciprocal_rank_fusion(
    vector_results: List[Tuple[str, float]],
    graph_results: List[str],
    k: int = 60
) -> List[Tuple[str, float]]:
    """
    RRF (Reciprocal Rank Fusion)

    Score = 1 / (k + rank)
    """
    scores = {}

    # 向量检索分数
    for rank, (doc_id, score) in enumerate(vector_results):
        rrf_score = 1 / (k + rank + 1)
        scores[doc_id] = scores.get(doc_id, 0) + 0.6 * rrf_score  # 0.6是向量权重

    # 图检索分数
    for rank, doc_id in enumerate(graph_results):
        rrf_score = 1 / (k + rank + 1)
        scores[doc_id] = scores.get(doc_id, 0) + 0.4 * rrf_score  # 0.4是图权重

    # 排序
    sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_docs


def weighted_score_fusion(
    vector_results: List[Tuple[str, float]],
    graph_results: List[Dict],
    alpha: float = 0.6
) -> List[Tuple[str, float]]:
    """
    加权分数融合

    Score = alpha * vector_score + (1-alpha) * graph_score
    """
    scores = {}

    # 向量检索分数
    for doc_id, vec_score in vector_results:
        scores[doc_id] = scores.get(doc_id, 0) + alpha * vec_score

    # 图检索分数
    for result in graph_results:
        doc_id = result["doc_id"]
        graph_score = result.get("score", 0.5)
        scores[doc_id] = scores.get(doc_id, 0) + (1 - alpha) * graph_score

    sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_docs


def distribution_calibration(
    vector_scores: Dict[str, float],
    graph_scores: Dict[str, float],
    vector_weight: float = 0.6
) -> Dict[str, float]:
    """
    SCG (Score Distribution Calibration)

    将两个分数分布对齐后再融合
    """
    if not vector_scores:
        return graph_scores
    if not graph_scores:
        return vector_scores

    # 归一化向量分数
    vec_min, vec_max = min(vector_scores.values()), max(vector_scores.values())
    vec_range = vec_max - vec_min if vec_max != vec_min else 1
    norm_vector = {k: (v - vec_min) / vec_range for k, v in vector_scores.items()}

    # 归一化图分数
    graph_min, graph_max = min(graph_scores.values()), max(graph_scores.values())
    graph_range = graph_max - graph_min if graph_max != graph_min else 1
    norm_graph = {k: (v - graph_min) / graph_range for k, v in graph_scores.items()}

    # 融合
    all_docs = set(norm_vector.keys()) | set(norm_graph.keys())
    fused_scores = {}

    for doc_id in all_docs:
        vec_s = norm_vector.get(doc_id, 0)
        graph_s = norm_graph.get(doc_id, 0)
        fused_scores[doc_id] = vector_weight * vec_s + (1 - vector_weight) * graph_s

    return fused_scores


# ============================================================================
# 完整流程评测
# ============================================================================

class FullPipelineEvaluator:
    """
    完整RAG检索流程评测

    支持评测：
    1. 向量检索单独
    2. 向量 + 图混合
    3. 向量 + 图 + Rerank
    """

    def __init__(self):
        self.graph_engine = get_graph_engine()

    def evaluate_layer1_vector_only(
        self,
        query: str,
        expected_docs: Set[str],
        top_k: int = 20
    ) -> Dict[str, Any]:
        """第1层：纯向量检索"""
        vector_results = mock_vector_search(query, top_k=top_k)
        doc_ids = [doc_id for doc_id, _ in vector_results]

        return {
            "method": "vector_only",
            "doc_ids": doc_ids,
            "recall@10": compute_recall_at_k(doc_ids, expected_docs, k=10),
            "recall@20": compute_recall_at_k(doc_ids, expected_docs, k=20),
            "ndcg@10": compute_ndcg_at_k(doc_ids, expected_docs, k=10),
            "mrr": compute_mrr(doc_ids, expected_docs),
        }

    def evaluate_layer2_vector_rerank(
        self,
        query: str,
        expected_docs: Set[str],
        vector_top_k: int = 50,
        rerank_top_k: int = 10
    ) -> Dict[str, Any]:
        """第2层：向量 + Rerank"""
        # 向量检索
        vector_results = mock_vector_search(query, top_k=vector_top_k)

        # Rerank
        rerank_results = mock_rerank(query, vector_results, top_n=rerank_top_k)
        doc_ids = [r["doc_id"] for r in rerank_results]

        return {
            "method": "vector_rerank",
            "doc_ids": doc_ids,
            "recall@10": compute_recall_at_k(doc_ids, expected_docs, k=10),
            "recall@20": compute_recall_at_k(doc_ids, expected_docs, k=20),
            "ndcg@10": compute_ndcg_at_k(doc_ids, expected_docs, k=10),
            "mrr": compute_mrr(doc_ids, expected_docs),
        }

    def evaluate_layer3_graph_only(
        self,
        query: str,
        expected_docs: Set[str],
        entities: List[str] = None,
        hop: int = 2,
        top_k: int = 20
    ) -> Dict[str, Any]:
        """第3层：纯图检索"""
        if entities is None:
            entities = self.graph_engine._extract_entities_from_query(query)

        graph_results = self.graph_engine.retrieve_by_entities(
            query, entities, hop=hop, limit=top_k
        )
        doc_ids = [r["doc_id"] for r in graph_results]

        return {
            "method": "graph_only",
            "doc_ids": doc_ids,
            "recall@10": compute_recall_at_k(doc_ids, expected_docs, k=10),
            "recall@20": compute_recall_at_k(doc_ids, expected_docs, k=20),
            "ndcg@10": compute_ndcg_at_k(doc_ids, expected_docs, k=10),
            "mrr": compute_mrr(doc_ids, expected_docs),
        }

    def evaluate_layer4_hybrid(
        self,
        query: str,
        expected_docs: Set[str],
        fusion_method: str = "rrf",
        alpha: float = 0.6,
        top_k: int = 20
    ) -> Dict[str, Any]:
        """第4层：向量 + 图混合检索"""
        entities = self.graph_engine._extract_entities_from_query(query)

        # 向量检索
        vector_results = mock_vector_search(query, top_k=top_k * 2)

        # 图检索
        graph_results = self.graph_engine.retrieve_by_entities(
            query, entities, hop=2, limit=top_k * 2
        )
        graph_doc_ids = [r["doc_id"] for r in graph_results]

        # 融合
        if fusion_method == "rrf":
            fused = reciprocal_rank_fusion(vector_results, graph_doc_ids, k=60)
        elif fusion_method == "weighted":
            fused = weighted_score_fusion(vector_results, graph_results, alpha=alpha)
        elif fusion_method == "scg":
            vec_scores = dict(vector_results)
            graph_scores = {r["doc_id"]: r["score"] for r in graph_results}
            fused_scores = distribution_calibration(vec_scores, graph_scores, alpha)
            fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        else:
            fused = vector_results[:top_k]  # fallback

        doc_ids = [doc_id for doc_id, _ in fused[:top_k]]

        return {
            "method": f"hybrid_{fusion_method}",
            "doc_ids": doc_ids,
            "recall@10": compute_recall_at_k(doc_ids, expected_docs, k=10),
            "recall@20": compute_recall_at_k(doc_ids, expected_docs, k=20),
            "ndcg@10": compute_ndcg_at_k(doc_ids, expected_docs, k=10),
            "mrr": compute_mrr(doc_ids, expected_docs),
        }

    def evaluate_layer5_full_pipeline(
        self,
        query: str,
        expected_docs: Set[str],
        fusion_method: str = "rrf",
        alpha: float = 0.6,
        vector_top_k: int = 50,
        rerank_top_k: int = 10
    ) -> Dict[str, Any]:
        """第5层：完整流程 (向量 + 图 + Rerank)"""
        entities = self.graph_engine._extract_entities_from_query(query)

        # 向量检索
        vector_results = mock_vector_search(query, top_k=vector_top_k)

        # 图检索
        graph_results = self.graph_engine.retrieve_by_entities(
            query, entities, hop=2, limit=vector_top_k
        )
        graph_doc_ids = [r["doc_id"] for r in graph_results]

        # 融合
        if fusion_method == "rrf":
            fused = reciprocal_rank_fusion(vector_results, graph_doc_ids, k=60)
        elif fusion_method == "weighted":
            fused = weighted_score_fusion(vector_results, graph_results, alpha=alpha)
        elif fusion_method == "scg":
            vec_scores = dict(vector_results)
            graph_scores = {r["doc_id"]: r["score"] for r in graph_results}
            fused_scores = distribution_calibration(vec_scores, graph_scores, alpha)
            fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
        else:
            fused = vector_results[:vector_top_k]

        # 取融合后的Top-K进行Rerank
        rerank_candidates = fused[:rerank_top_k * 2]
        rerank_candidates_list = [(doc_id, score) for doc_id, score in rerank_candidates]

        # Rerank
        rerank_results = mock_rerank(query, rerank_candidates_list, top_n=rerank_top_k)
        doc_ids = [r["doc_id"] for r in rerank_results]

        return {
            "method": f"full_{fusion_method}_rerank",
            "doc_ids": doc_ids,
            "recall@10": compute_recall_at_k(doc_ids, expected_docs, k=10),
            "recall@20": compute_recall_at_k(doc_ids, expected_docs, k=20),
            "ndcg@10": compute_ndcg_at_k(doc_ids, expected_docs, k=10),
            "mrr": compute_mrr(doc_ids, expected_docs),
        }

    def evaluate_all_layers(
        self,
        query: str,
        expected_docs: Set[str],
        entities: List[str] = None
    ) -> Dict[str, Any]:
        """评测所有层次"""
        if entities is None:
            entities = self.graph_engine._extract_entities_from_query(query)

        return {
            "layer1_vector_only": self.evaluate_layer1_vector_only(query, expected_docs),
            "layer2_vector_rerank": self.evaluate_layer2_vector_rerank(query, expected_docs),
            "layer3_graph_only": self.evaluate_layer3_graph_only(query, expected_docs, entities),
            "layer4_hybrid_rrf": self.evaluate_layer4_hybrid(query, expected_docs, "rrf"),
            "layer4_hybrid_weighted": self.evaluate_layer4_hybrid(query, expected_docs, "weighted"),
            "layer5_full_rrf": self.evaluate_layer5_full_pipeline(query, expected_docs, "rrf"),
            "layer5_full_weighted": self.evaluate_layer5_full_pipeline(query, expected_docs, "weighted"),
        }


# ============================================================================
# 测试类
# ============================================================================

@pytest.fixture
def evaluator():
    return FullPipelineEvaluator()


class TestLayer1VectorOnly:
    """第1层：纯向量检索测试"""

    def test_all_queries(self, evaluator):
        """测试所有查询"""
        results = []
        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            result = evaluator.evaluate_layer1_vector_only(q["query"], expected)
            results.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                **result
            })

        print("\n" + "="*70)
        print("第1层：纯向量检索")
        print("="*70)
        for r in sorted(results, key=lambda x: x["recall@10"]):
            print(f"Q{r['query_id']:<4} {r['type']:<12} Recall@10={r['recall@10']:.3f} "
                  f"NDCG@10={r['ndcg@10']:.3f} MRR={r['mrr']:.3f}")
        print("="*70)


class TestLayer2VectorRerank:
    """第2层：向量 + Rerank测试"""

    def test_rerank_effect(self, evaluator):
        """测试Rerank效果"""
        improvements = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])

            vector_result = evaluator.evaluate_layer1_vector_only(q["query"], expected)
            rerank_result = evaluator.evaluate_layer2_vector_rerank(q["query"], expected)

            improvements.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "vector_recall": vector_result["recall@10"],
                "rerank_recall": rerank_result["recall@10"],
                "improvement": rerank_result["recall@10"] - vector_result["recall@10"]
            })

        print("\n" + "="*70)
        print("第2层：向量 + Rerank 效果")
        print("="*70)
        for r in sorted(improvements, key=lambda x: x["improvement"], reverse=True):
            print(f"Q{r['query_id']:<4} {r['type']:<12} ΔRecall@10={r['improvement']:+.3f} "
                  f"(V={r['vector_recall']:.3f} -> R={r['rerank_recall']:.3f})")
        print("="*70)


class TestLayer3GraphOnly:
    """第3层：图检索独立测试"""

    def test_graph_only_performance(self, evaluator):
        """测试纯图检索性能"""
        results = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            entities = evaluator.graph_engine._extract_entities_from_query(q["query"])

            result = evaluator.evaluate_layer3_graph_only(q["query"], expected, entities)

            results.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "entities_count": len(entities),
                **result
            })

        print("\n" + "="*70)
        print("第3层：纯图检索")
        print("="*70)
        for r in sorted(results, key=lambda x: x["recall@10"]):
            graph_indicator = "★" if r["requires_graph"] else " "
            print(f"Q{r['query_id']:<4}{graph_indicator} {r['type']:<12} "
                  f"Recall@10={r['recall@10']:.3f} 实体数={r['entities_count']}")
        print("="*70)


class TestLayer4HybridRetrieval:
    """第4层：向量 + 图混合检索测试"""

    def test_hybrid_vs_single(self, evaluator):
        """测试混合检索 vs 单检索"""
        for q in [q for q in EVAL_QUERIES if q["id"] in ["q4", "q5", "q6", "q7"]]:
            expected = set(q["expected_docs"])

            vector_result = evaluator.evaluate_layer1_vector_only(q["query"], expected)
            graph_result = evaluator.evaluate_layer3_graph_only(q["query"], expected)
            hybrid_rrf = evaluator.evaluate_layer4_hybrid(q["query"], expected, "rrf")
            hybrid_weighted = evaluator.evaluate_layer4_hybrid(q["query"], expected, "weighted")

            print(f"\nQ{q['id']} ({q['type']}): {q['query'][:40]}...")
            print(f"  向量检索:  Recall@10={vector_result['recall@10']:.3f}")
            print(f"  图检索:    Recall@10={graph_result['recall@10']:.3f}")
            print(f"  混合(RRF): Recall@10={hybrid_rrf['recall@10']:.3f}")
            print(f"  混合(加权): Recall@10={hybrid_weighted['recall@10']:.3f}")

    def test_all_fusion_methods(self, evaluator):
        """测试所有融合方法"""
        all_results = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])

            rrf = evaluator.evaluate_layer4_hybrid(q["query"], expected, "rrf")
            weighted = evaluator.evaluate_layer4_hybrid(q["query"], expected, "weighted")
            scg = evaluator.evaluate_layer4_hybrid(q["query"], expected, "scg")

            all_results.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "rrf_recall": rrf["recall@10"],
                "weighted_recall": weighted["recall@10"],
                "scg_recall": scg["recall@10"],
            })

        print("\n" + "="*80)
        print("第4层：不同融合方法对比")
        print("="*80)
        for r in all_results:
            best = max(r["rrf_recall"], r["weighted_recall"], r["scg_recall"])
            print(f"Q{r['query_id']:<4} {r['type']:<12} RRF={r['rrf_recall']:.3f} "
                  f"W={r['weighted_recall']:.3f} SCG={r['scg_recall']:.3f} (best={best:.3f})")
        print("="*80)


class TestLayer5FullPipeline:
    """第5层：完整流程测试"""

    def test_full_pipeline_vs_others(self, evaluator):
        """测试完整流程 vs 其他方法"""
        all_layers = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            entities = evaluator.graph_engine._extract_entities_from_query(q["query"])

            all_result = evaluator.evaluate_all_layers(q["query"], expected, entities)

            all_layers.append({
                "query_id": q["id"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "vector": all_result["layer1_vector_only"]["recall@10"],
                "rerank": all_result["layer2_vector_rerank"]["recall@10"],
                "graph": all_result["layer3_graph_only"]["recall@10"],
                "hybrid": all_result["layer4_hybrid_rrf"]["recall@10"],
                "full": all_result["layer5_full_rrf"]["recall@10"],
            })

        print("\n" + "="*100)
        print("第5层：完整流程对比")
        print("="*100)
        print(f"{'ID':<4} {'Type':<12} {'Vector':<8} {'Rerank':<8} {'Graph':<8} {'Hybrid':<8} {'Full':<8}")
        print("-"*100)
        for r in sorted(all_layers, key=lambda x: x["full"], reverse=True):
            print(f"Q{r['query_id']:<4} {r['type']:<12} "
                  f"{r['vector']:<8.3f} {r['rerank']:<8.3f} {r['graph']:<8.3f} "
                  f"{r['hybrid']:<8.3f} {r['full']:<8.3f}")
        print("="*100)

        # 计算各层平均
        avg_vector = sum(r["vector"] for r in all_layers) / len(all_layers)
        avg_full = sum(r["full"] for r in all_layers) / len(all_layers)
        print(f"\n平均 Vector Recall@10: {avg_vector:.3f}")
        print(f"平均 Full Pipeline Recall@10: {avg_full:.3f}")
        print(f"提升: {avg_full - avg_vector:+.3f}")


class TestGraphNecessity:
    """图谱必要性验证测试"""

    def test_graph_essential_queries(self, evaluator):
        """验证图检索对特定查询的必要性"""
        # 需要图检索的查询
        graph_essential = [q for q in EVAL_QUERIES if q.get("requires_graph")]

        print("\n" + "="*80)
        print("图检索必要性验证")
        print("="*80)

        improvements = []

        for q in graph_essential:
            expected = set(q["expected_docs"])
            entities = evaluator.graph_engine._extract_entities_from_query(q["query"])

            vector_result = evaluator.evaluate_layer1_vector_only(q["query"], expected)
            hybrid_result = evaluator.evaluate_layer4_hybrid(q["query"], expected, "rrf")
            full_result = evaluator.evaluate_layer5_full_pipeline(q["query"], expected, "rrf")

            vector_recall = vector_result["recall@10"]
            hybrid_improvement = hybrid_result["recall@10"] - vector_recall
            full_improvement = full_result["recall@10"] - vector_recall

            improvements.append({
                "query_id": q["id"],
                "query": q["query"][:50],
                "difficulty": q["difficulty"],
                "vector_recall": vector_recall,
                "hybrid_improvement": hybrid_improvement,
                "full_improvement": full_improvement,
            })

        # 按提升幅度排序
        for imp in sorted(improvements, key=lambda x: x["full_improvement"], reverse=True):
            indicator = "★★★" if imp["full_improvement"] > 0.2 else ("★★" if imp["full_improvement"] > 0 else "★")
            print(f"Q{imp['query_id']:<4}{indicator} [{imp['difficulty']}]")
            print(f"   Query: {imp['query']}...")
            print(f"   Vector Recall: {imp['vector_recall']:.3f}")
            print(f"   Hybrid Δ: {imp['hybrid_improvement']:+.3f}")
            print(f"   Full Δ: {imp['full_improvement']:+.3f}")
            print()

        print("="*80)
        avg_improvement = sum(imp["full_improvement"] for imp in improvements) / len(improvements)
        print(f"图检索平均提升: {avg_improvement:+.3f}")
        print("图谱必要性: ", "高" if avg_improvement > 0.1 else "中" if avg_improvement > 0 else "低")


class TestRetrievalLatency:
    """延迟测试（模拟）"""

    def test_latency_breakdown(self, evaluator):
        """测试各阶段延迟分解"""
        # 模拟延迟 (ms)
        MOCK_LATENCIES = {
            "embedding": 45,
            "vector_search": 20,
            "graph_traversal": 15,
            "fusion": 2,
            "rerank": 80,
        }

        print("\n" + "="*50)
        print("延迟分解 (模拟)")
        print("="*50)
        print(f"Embedding: {MOCK_LATENCIES['embedding']}ms")
        print(f"向量检索: {MOCK_LATENCIES['vector_search']}ms")
        print(f"图遍历: {MOCK_LATENCIES['graph_traversal']}ms")
        print(f"融合计算: {MOCK_LATENCIES['fusion']}ms")
        print(f"Rerank: {MOCK_LATENCIES['rerank']}ms")
        print("-"*50)

        vector_only = MOCK_LATENCIES["embedding"] + MOCK_LATENCIES["vector_search"]
        print(f"向量单独: {vector_only}ms")

        hybrid = vector_only + MOCK_LATENCIES["graph_traversal"] + MOCK_LATENCIES["fusion"]
        print(f"混合检索: {hybrid}ms")

        full = hybrid + MOCK_LATENCIES["rerank"]
        print(f"完整流程: {full}ms")
        print("="*50)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
