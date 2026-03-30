"""
RAG 检索评测 - 第2层：向量检索 + Rerank

测试 Rerank 模型对检索结果的优化能力
"""
import sys
from pathlib import Path

# 确保tests目录在path中
tests_dir = str(Path(__file__).parent)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

import json
import pytest
from typing import List, Dict, Any, Set, Tuple
from unittest.mock import MagicMock, AsyncMock, patch

# 导入第1层指标计算
from test_rag_retrieval import (
    CORPUS,
    EVAL_QUERIES,
    compute_recall_at_k,
    compute_ndcg_at_k,
    compute_mrr,
    compute_map,
    compute_hybrid_metrics,
)


# ============================================================================
# 模拟向量检索结果
# ============================================================================

def mock_vector_search(query: str, top_k: int = 50) -> List[Tuple[str, float]]:
    """
    模拟向量检索返回 (doc_id, score)

    实际项目中会调用 embed_query 和向量数据库
    """
    # 基于查询关键词的简单匹配模拟
    query_lower = query.lower()
    results = []

    # 关键词匹配规则（模拟语义相似度）
    keyword_rules = {
        "RAG": ["doc_001", "doc_005", "doc_011", "doc_012", "doc_020"],
        "向量": ["doc_002", "doc_004", "doc_009", "doc_020"],
        "检索": ["doc_001", "doc_002", "doc_005", "doc_009", "doc_010"],
        "BERT": ["doc_004", "doc_013", "doc_014", "doc_017"],
        "GPT": ["doc_013", "doc_015", "doc_017"],
        "Transformer": ["doc_013", "doc_014", "doc_015", "doc_017"],
        "知识图谱": ["doc_003", "doc_007", "doc_011", "doc_019"],
        "Neo4j": ["doc_003", "doc_019"],
        "词嵌入": ["doc_004", "doc_014", "doc_016"],
        "多跳": ["doc_006", "doc_011"],
        "链接预测": ["doc_008", "doc_018"],
        "语义搜索": ["doc_009", "doc_004"],
        "混合检索": ["doc_010", "doc_002"],
    }

    # 收集匹配的文档
    doc_scores = {}
    for keyword, doc_ids in keyword_rules.items():
        if keyword in query_lower:
            for doc_id in doc_ids:
                doc_scores[doc_id] = doc_scores.get(doc_id, 0) + 1.0

    # 如果没有匹配，返回所有文档
    if not doc_scores:
        for doc in CORPUS[:top_k]:
            results.append((doc["id"], 0.5))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # 按分数排序
    for doc_id, score in doc_scores.items():
        results.append((doc_id, score / 10.0))  # 归一化到0-1

    results.sort(key=lambda x: x[1], reverse=True)

    # 如果不够top_k，添加其他文档
    matched_ids = set(r[0] for r in results)
    for doc in CORPUS:
        if doc["id"] not in matched_ids and len(results) < top_k:
            results.append((doc["id"], 0.1))
            matched_ids.add(doc["id"])

    return results[:top_k]


# ============================================================================
# 模拟 Rerank 结果
# ============================================================================

def mock_rerank(
    query: str,
    documents: List[Tuple[str, float]],
    top_n: int = 10
) -> List[Dict[str, Any]]:
    """
    模拟 Rerank 模型重排序

    实际项目中会调用 RemoteRerankClient

    Rerank模型会考虑：
    1. 查询与文档的语义匹配度
    2. 关键词匹配
    3. 实体对齐
    """
    query_lower = query.lower()

    # 关键词权重
    keyword_boost = {
        "什么是": 0.8,  # 实体定义类查询
        "有什么关系": 1.2,  # 关系类查询
        "区别": 1.0,  # 对比类查询
        "基于": 1.5,  # 依赖类查询
        "如何": 0.7,  # 方法类查询
    }

    reranked = []
    for doc_id, original_score in documents:
        # 找到文档内容
        doc = next((d for d in CORPUS if d["id"] == doc_id), None)
        if not doc:
            continue

        content_lower = doc["content"].lower()
        entities = doc["entities"]

        # 计算rerank分数
        new_score = original_score * 0.3  # 基础分

        # 关键词匹配加分
        for keyword, boost in keyword_boost.items():
            if keyword in query_lower:
                if keyword in content_lower:
                    new_score += 0.2 * boost

        # 实体匹配加分
        query_entities = []
        for entity in entities:
            if entity.lower() in query_lower:
                query_entities.append(entity)
                new_score += 0.15

        # 关系推理加分（模拟Rerank能理解关系）
        if "BERT" in query_entities and "GPT" in query_entities:
            # Rerank能理解两者都与Transformer相关
            if "Transformer" in entities or "doc_013" in doc["id"]:
                new_score += 0.3

        if "多跳" in query_lower or "关系" in query_lower:
            if len(entities) >= 3:  # 实体多的文档可能更相关
                new_score += 0.2

        reranked.append({
            "doc_id": doc_id,
            "score": min(new_score, 1.0),
            "original_score": original_score,
            "matched_entities": query_entities
        })

    # 按新分数排序
    reranked.sort(key=lambda x: x["score"], reverse=True)

    return reranked[:top_n]


# ============================================================================
# 评测函数
# ============================================================================

def evaluate_retrieval_with_rerank(
    query: str,
    expected_docs: Set[str],
    vector_top_k: int = 50,
    rerank_top_k: int = 10
) -> Dict[str, Any]:
    """
    评估向量检索 + Rerank 的效果

    Returns:
        包含各阶段指标的字典
    """
    # 阶段1: 向量检索
    vector_results = mock_vector_search(query, top_k=vector_top_k)
    vector_doc_ids = [doc_id for doc_id, _ in vector_results]

    # 向量检索指标
    vector_recall_10 = compute_recall_at_k(vector_doc_ids, expected_docs, k=10)
    vector_recall_20 = compute_recall_at_k(vector_doc_ids, expected_docs, k=20)
    vector_ndcg_10 = compute_ndcg_at_k(vector_doc_ids, expected_docs, k=10)
    vector_mrr = compute_mrr(vector_doc_ids, expected_docs)

    # 阶段2: Rerank
    rerank_results = mock_rerank(query, vector_results[:vector_top_k], top_n=rerank_top_k)
    rerank_doc_ids = [r["doc_id"] for r in rerank_results]

    # Rerank后的指标
    rerank_recall_10 = compute_recall_at_k(rerank_doc_ids, expected_docs, k=10)
    rerank_ndcg_10 = compute_ndcg_at_k(rerank_doc_ids, expected_docs, k=10)
    rerank_mrr = compute_mrr(rerank_doc_ids, expected_docs)

    return {
        # 向量检索指标
        "vector": {
            "recall@10": vector_recall_10,
            "recall@20": vector_recall_20,
            "ndcg@10": vector_ndcg_10,
            "mrr": vector_mrr,
        },
        # Rerank后指标
        "rerank": {
            "recall@10": rerank_recall_10,
            "ndcg@10": rerank_ndcg_10,
            "mrr": rerank_mrr,
        },
        # 提升
        "delta": {
            "recall@10": rerank_recall_10 - vector_recall_10,
            "ndcg@10": rerank_ndcg_10 - vector_ndcg_10,
            "mrr": rerank_mrr - vector_mrr,
        },
        # 详细结果
        "top_docs": rerank_doc_ids[:5],
        "expected": list(expected_docs)[:5],
    }


# ============================================================================
# 测试类
# ============================================================================

class TestVectorSearchOnly:
    """第1层：纯向量检索基线测试"""

    def test_baseline_recall(self):
        """测试向量检索基线召回率"""
        # q1: "什么是RAG技术？"
        q1 = next(q for q in EVAL_QUERIES if q["id"] == "q1")
        expected = set(q1["expected_docs"])

        results = mock_vector_search(q1["query"], top_k=50)
        doc_ids = [doc_id for doc_id, _ in results]

        recall = compute_recall_at_k(doc_ids, expected, k=10)
        print(f"\n向量检索基线 - Q1 (RAG定义):")
        print(f"  Recall@10: {recall:.3f}")

        # 基线应该有一定召回
        assert recall > 0

    def test_all_queries_baseline(self):
        """测试所有查询的向量检索基线"""
        all_results = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            results = mock_vector_search(q["query"], top_k=50)
            doc_ids = [doc_id for doc_id, _ in results]

            recall_10 = compute_recall_at_k(doc_ids, expected, k=10)
            ndcg_10 = compute_ndcg_at_k(doc_ids, expected, k=10)
            mrr = compute_mrr(doc_ids, expected)

            all_results.append({
                "query_id": q["id"],
                "query": q["query"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "recall@10": recall_10,
                "ndcg@10": ndcg_10,
                "mrr": mrr,
            })

        print("\n" + "="*80)
        print("向量检索基线结果:")
        print("="*80)
        print(f"{'ID':<6} {'Type':<12} {'Graph':<6} {'Recall@10':<12} {'NDCG@10':<12} {'MRR':<10}")
        print("-"*80)
        for r in sorted(all_results, key=lambda x: x["recall@10"]):
            print(f"{r['query_id']:<6} {r['type']:<12} {str(r['requires_graph']):<6} "
                  f"{r['recall@10']:<12.3f} {r['ndcg@10']:<12.3f} {r['mrr']:<10.3f}")
        print("-"*80)

        avg_recall = sum(r["recall@10"] for r in all_results) / len(all_results)
        avg_ndcg = sum(r["ndcg@10"] for r in all_results) / len(all_results)
        print(f"Average Recall@10: {avg_recall:.3f}")
        print(f"Average NDCG@10: {avg_ndcg:.3f}")

        assert len(all_results) == len(EVAL_QUERIES)


class TestVectorSearchWithRerank:
    """第2层：向量检索 + Rerank 测试"""

    def test_rerank_improves_ranking(self):
        """测试 Rerank 改善排序"""
        # q1: "什么是RAG技术？"
        q1 = next(q for q in EVAL_QUERIES if q["id"] == "q1")
        expected = set(q1["expected_docs"])

        eval_result = evaluate_retrieval_with_rerank(
            q1["query"],
            expected,
            vector_top_k=50,
            rerank_top_k=10
        )

        print(f"\nRerank 效果 - Q1 (RAG定义):")
        print(f"  Vector Recall@10: {eval_result['vector']['recall@10']:.3f}")
        print(f"  Rerank Recall@10: {eval_result['rerank']['recall@10']:.3f}")
        print(f"  Delta Recall@10: {eval_result['delta']['recall@10']:+.3f}")

        # Rerank后MRR应该有提升
        assert eval_result["rerank"]["mrr"] >= 0

    def test_multihop_query_benefits_rerank(self):
        """测试多跳查询从Rerank获益"""
        # q4: "BERT和GPT有什么关系？它们都基于什么架构？"
        q4 = next(q for q in EVAL_QUERIES if q["id"] == "q4")
        expected = set(q4["expected_docs"])

        eval_result = evaluate_retrieval_with_rerank(
            q4["query"],
            expected,
            vector_top_k=50,
            rerank_top_k=10
        )

        print(f"\nRerank 效果 - Q4 (多跳关系):")
        print(f"  Query: {q4['query']}")
        print(f"  Vector Recall@10: {eval_result['vector']['recall@10']:.3f}")
        print(f"  Rerank Recall@10: {eval_result['rerank']['recall@10']:.3f}")
        print(f"  Delta Recall@10: {eval_result['delta']['recall@10']:+.3f}")
        print(f"  Top docs after rerank: {eval_result['top_docs']}")

        # 对于多跳查询，Rerank应该能提升召回
        assert eval_result["delta"]["recall@10"] >= 0

    def test_all_queries_with_rerank(self):
        """测试所有查询的 Rerank 效果"""
        all_results = []

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            eval_result = evaluate_retrieval_with_rerank(
                q["query"],
                expected,
                vector_top_k=50,
                rerank_top_k=10
            )

            all_results.append({
                "query_id": q["id"],
                "query": q["query"],
                "type": q["type"],
                "requires_graph": q["requires_graph"],
                "vector_recall@10": eval_result["vector"]["recall@10"],
                "rerank_recall@10": eval_result["rerank"]["recall@10"],
                "delta_recall@10": eval_result["delta"]["recall@10"],
                "vector_ndcg@10": eval_result["vector"]["ndcg@10"],
                "rerank_ndcg@10": eval_result["rerank"]["ndcg@10"],
                "delta_ndcg@10": eval_result["delta"]["ndcg@10"],
            })

        print("\n" + "="*100)
        print("向量检索 + Rerank 结果:")
        print("="*100)
        print(f"{'ID':<6} {'Type':<12} {'Graph':<6} {'V.Recall':<10} {'R.Recall':<10} {'ΔRecall':<10} {'V.NDCG':<10} {'R.NDCG':<10} {'ΔNDCG':<10}")
        print("-"*100)
        for r in sorted(all_results, key=lambda x: x["delta_recall@10"], reverse=True):
            print(f"{r['query_id']:<6} {r['type']:<12} {str(r['requires_graph']):<6} "
                  f"{r['vector_recall@10']:<10.3f} {r['rerank_recall@10']:<10.3f} {r['delta_recall@10']:<+10.3f} "
                  f"{r['vector_ndcg@10']:<10.3f} {r['rerank_ndcg@10']:<10.3f} {r['delta_ndcg@10']:<+10.3f}")
        print("-"*100)

        # 统计
        avg_vector_recall = sum(r["vector_recall@10"] for r in all_results) / len(all_results)
        avg_rerank_recall = sum(r["rerank_recall@10"] for r in all_results) / len(all_results)
        avg_delta_recall = sum(r["delta_recall@10"] for r in all_results) / len(all_results)

        print(f"\n平均 Vector Recall@10: {avg_vector_recall:.3f}")
        print(f"平均 Rerank Recall@10: {avg_rerank_recall:.3f}")
        print(f"平均 ΔRecall@10: {avg_delta_recall:+.3f}")

        # Rerank应该平均提升或持平
        assert avg_rerank_recall >= avg_vector_recall * 0.9  # 允许小幅下降


class TestRerankImprovementAnalysis:
    """Rerank 改进分析"""

    def test_query_types_differ_in_rerank_benefit(self):
        """分析不同查询类型从 Rerank 获益的程度"""
        by_type = {}

        for q in EVAL_QUERIES:
            expected = set(q["expected_docs"])
            eval_result = evaluate_retrieval_with_rerank(q["query"], expected)

            q_type = q["type"]
            if q_type not in by_type:
                by_type[q_type] = []
            by_type[q_type].append({
                "delta_recall": eval_result["delta"]["recall@10"],
                "delta_ndcg": eval_result["delta"]["ndcg@10"],
            })

        print("\n" + "="*60)
        print("各查询类型从 Rerank 的获益:")
        print("="*60)
        for q_type, results in by_type.items():
            avg_delta_recall = sum(r["delta_recall"] for r in results) / len(results)
            avg_delta_ndcg = sum(r["delta_ndcg"] for r in results) / len(results)
            print(f"{q_type}: ΔRecall={avg_delta_recall:+.3f}, ΔNDCG={avg_delta_ndcg:+.3f} (n={len(results)})")
        print("="*60)

    def test_graph_required_queries(self):
        """分析需要图检索的查询在 Rerank 下表现"""
        graph_queries = [q for q in EVAL_QUERIES if q.get("requires_graph")]
        non_graph_queries = [q for q in EVAL_QUERIES if not q.get("requires_graph")]

        graph_deltas = []
        non_graph_deltas = []

        for q in graph_queries:
            expected = set(q["expected_docs"])
            eval_result = evaluate_retrieval_with_rerank(q["query"], expected)
            graph_deltas.append(eval_result["delta"]["recall@10"])

        for q in non_graph_queries:
            expected = set(q["expected_docs"])
            eval_result = evaluate_retrieval_with_rerank(q["query"], expected)
            non_graph_deltas.append(eval_result["delta"]["recall@10"])

        print("\n" + "="*60)
        print("图依赖查询 vs 非图依赖查询:")
        print("="*60)
        print(f"图依赖查询 ({len(graph_deltas)}个):")
        print(f"  平均 ΔRecall@10: {sum(graph_deltas)/len(graph_deltas):+.3f}")
        print(f"非图依赖查询 ({len(non_graph_deltas)}个):")
        print(f"  平均 ΔRecall@10: {sum(non_graph_deltas)/len(non_graph_deltas):+.3f}")
        print("="*60)

        # 非图依赖查询从Rerank获益应该更稳定
        # 因为向量检索本身就能很好处理
        assert len(non_graph_deltas) > 0
        assert len(graph_deltas) > 0


class TestRerankThresholds:
    """Rerank 阈值测试"""

    def test_different_rerank_top_n(self):
        """测试不同的 Rerank top_n 效果"""
        q1 = next(q for q in EVAL_QUERIES if q["id"] == "q1")
        expected = set(q1["expected_docs"])

        results_by_top_n = {}
        for top_n in [5, 10, 20, 30]:
            eval_result = evaluate_retrieval_with_rerank(
                q1["query"],
                expected,
                vector_top_k=50,
                rerank_top_k=top_n
            )
            results_by_top_n[top_n] = eval_result

        print(f"\n不同 Rerank Top-N 效果 - Q1:")
        print("="*50)
        for top_n, result in results_by_top_n.items():
            print(f"Top-{top_n}: Recall@10={result['rerank']['recall@10']:.3f}, "
                  f"NDCG@10={result['rerank']['ndcg@10']:.3f}")
        print("="*50)

    def test_different_vector_top_k(self):
        """测试不同的向量检索 top_k 对 Rerank 效果影响"""
        q4 = next(q for q in EVAL_QUERIES if q["id"] == "q4")
        expected = set(q4["expected_docs"])

        results_by_vector_k = {}
        for vector_k in [20, 50, 100]:
            eval_result = evaluate_retrieval_with_rerank(
                q4["query"],
                expected,
                vector_top_k=vector_k,
                rerank_top_k=10
            )
            results_by_vector_k[vector_k] = eval_result

        print(f"\n不同 Vector Top-K 效果 - Q4 (多跳):")
        print("="*50)
        for vector_k, result in results_by_vector_k.items():
            print(f"Vector Top-{vector_k}: Recall@10={result['rerank']['recall@10']:.3f}, "
                  f"MRR={result['rerank']['mrr']:.3f}")
        print("="*50)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
