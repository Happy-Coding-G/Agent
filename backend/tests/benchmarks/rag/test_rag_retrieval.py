"""
RAG 检索评测测试

评测层次：
1. 纯向量检索 (Embeddings)
2. 向量检索 + 重排序 (Rerank)
3. 图检索独立评测
4. 向量 + 图混合检索
5. 完整流程 (向量 + 图 + 重排)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import math
import pytest
from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict


# ============================================================================
# 测试数据集
# ============================================================================

# 文档语料库
CORPUS = [
    {
        "id": "doc_001",
        "content": "检索增强生成(Retrieval-Augmented Generation, RAG)是一种结合检索系统和生成模型的技术。RAG可以从外部知识库中检索相关信息，用于增强大语言模型的生成能力。",
        "entities": ["RAG", "LLM", "检索系统", "生成模型"],
        "entity_types": {"RAG": "技术", "LLM": "模型", "检索系统": "系统", "生成模型": "模型"}
    },
    {
        "id": "doc_002",
        "content": "向量检索是RAG系统的核心组件。通过将文本转换为高维向量，可以在向量空间中找到语义相似的文档。常用的向量检索算法包括FAISS、Milvus等。",
        "entities": ["向量检索", "FAISS", "Milvus", "向量空间"],
        "entity_types": {"向量检索": "技术", "FAISS": "工具", "Milvus": "工具", "向量空间": "概念"}
    },
    {
        "id": "doc_003",
        "content": "知识图谱是一种结构化的知识表示形式，由实体和关系组成。实体表示概念，关系表示实体之间的联系。Neo4j是一种流行的图数据库。",
        "entities": ["知识图谱", "Neo4j", "实体", "关系", "图数据库"],
        "entity_types": {"知识图谱": "数据结构", "Neo4j": "工具", "实体": "概念", "关系": "概念", "图数据库": "系统"}
    },
    {
        "id": "doc_004",
        "content": "Embeddings是一种将文本转换为稠密向量的技术。Word2Vec、BERT等模型可以生成词嵌入或句子嵌入。好的Embeddings能够捕捉语义信息。",
        "entities": ["Embeddings", "Word2Vec", "BERT", "词嵌入"],
        "entity_types": {"Embeddings": "技术", "Word2Vec": "模型", "BERT": "模型", "词嵌入": "技术"}
    },
    {
        "id": "doc_005",
        "content": "RAG系统的工作流程包括：索引构建、检索和生成。索引构建阶段将文档分块并向量化。检索阶段根据查询找到相关文档。生成阶段将检索结果注入prompt。",
        "entities": ["RAG", "索引构建", "检索", "生成", "分块"],
        "entity_types": {"RAG": "技术", "索引构建": "阶段", "检索": "阶段", "生成": "阶段", "分块": "技术"}
    },
    {
        "id": "doc_006",
        "content": "多跳推理是指通过多个步骤推导出结论的能力。例如，要回答'谁是用某技术开发某产品的CEO'，需要先找到该产品、该技术、然后找到CEO，涉及多个实体之间的关系。",
        "entities": ["多跳推理", "CEO", "实体关系"],
        "entity_types": {"多跳推理": "能力", "CEO": "人物", "实体关系": "概念"}
    },
    {
        "id": "doc_007",
        "content": "实体链接是将文本中的实体提及与知识图谱中的实体节点进行匹配的过程。例如，将'ChatGPT'链接到知识图谱中的'ChatGPT'节点。",
        "entities": ["实体链接", "ChatGPT", "实体提及", "知识图谱"],
        "entity_types": {"实体链接": "技术", "ChatGPT": "产品", "实体提及": "概念", "知识图谱": "数据结构"}
    },
    {
        "id": "doc_008",
        "content": "图神经网络(GNN)是一种能处理图结构数据的深度学习模型。GNN可以学习节点和边的表示，用于节点分类、链接预测等任务。",
        "entities": ["图神经网络", "GNN", "节点分类", "链接预测", "深度学习"],
        "entity_types": {"图神经网络": "模型", "GNN": "模型", "节点分类": "任务", "链接预测": "任务", "深度学习": "领域"}
    },
    {
        "id": "doc_009",
        "content": "语义搜索超越关键词匹配，通过理解查询意图来检索相关文档。语义搜索使用Embeddings将查询和文档映射到向量空间，通过向量相似度来排序结果。",
        "entities": ["语义搜索", "关键词匹配", "向量空间", "向量相似度"],
        "entity_types": {"语义搜索": "技术", "关键词匹配": "技术", "向量空间": "概念", "向量相似度": "指标"}
    },
    {
        "id": "doc_010",
        "content": "混合检索结合向量检索和关键词检索的优点。关键词检索(如BM25)擅长精确匹配，向量检索擅长语义理解。混合检索通过RRF或加权方式融合两种检索结果。",
        "entities": ["混合检索", "BM25", "RRF", "向量检索", "关键词检索"],
        "entity_types": {"混合检索": "技术", "BM25": "算法", "RRF": "算法", "向量检索": "技术", "关键词检索": "技术"}
    },
    {
        "id": "doc_011",
        "content": "知识图谱与RAG的结合可以增强检索的准确性。通过在知识图谱中建立实体和关系，RAG系统可以执行多跳推理检索，找到通过普通向量检索难以发现的关联文档。",
        "entities": ["知识图谱", "RAG", "多跳推理", "关联文档", "实体", "关系"],
        "entity_types": {"知识图谱": "数据结构", "RAG": "技术", "多跳推理": "能力", "关联文档": "概念", "实体": "概念", "关系": "概念"}
    },
    {
        "id": "doc_012",
        "content": "LangChain是一个用于构建RAG应用的框架。它提供了文档加载、分割、向量存储、检索链等组件，支持多种向量数据库和LLM。",
        "entities": ["LangChain", "RAG", "向量存储", "LLM", "向量数据库"],
        "entity_types": {"LangChain": "框架", "RAG": "技术", "向量存储": "组件", "LLM": "模型", "向量数据库": "系统"}
    },
    # 图结构强相关数据 - 用于突出图谱必要性
    {
        "id": "doc_013",
        "content": "Transformer架构是BERT和GPT等模型的基础。它使用自注意力机制处理序列数据，自注意力允许模型在处理某个词时考虑整个序列的上下文信息。",
        "entities": ["Transformer", "BERT", "GPT", "自注意力", "上下文"],
        "entity_types": {"Transformer": "架构", "BERT": "模型", "GPT": "模型", "自注意力": "机制", "上下文": "概念"}
    },
    {
        "id": "doc_014",
        "content": "BERT基于Transformer的双向编码器表示，它通过掩码语言模型预训练获得上下文相关的词嵌入。BERT在各种NLP任务上取得了突破性成果。",
        "entities": ["BERT", "Transformer", "掩码语言模型", "词嵌入", "NLP"],
        "entity_types": {"BERT": "模型", "Transformer": "架构", "掩码语言模型": "技术", "词嵌入": "技术", "NLP": "领域"}
    },
    {
        "id": "doc_015",
        "content": "GPT系列是基于Transformer的生成式预训练模型。GPT-3有1750亿参数，能够生成非常流畅的自然语言文本。ChatGPT是基于GPT的对话应用。",
        "entities": ["GPT", "GPT-3", "Transformer", "ChatGPT", "参数"],
        "entity_types": {"GPT": "模型", "GPT-3": "模型", "Transformer": "架构", "ChatGPT": "产品", "参数": "概念"}
    },
    {
        "id": "doc_016",
        "content": "词嵌入技术将词汇映射到低维稠密向量空间。Word2Vec使用浅层神经网络学习词嵌入，CBOW和Skip-gram是两种主要训练方法。",
        "entities": ["词嵌入", "Word2Vec", "CBOW", "Skip-gram", "向量空间"],
        "entity_types": {"词嵌入": "技术", "Word2Vec": "模型", "CBOW": "方法", "Skip-gram": "方法", "向量空间": "概念"}
    },
    {
        "id": "doc_017",
        "content": "注意力机制允许模型在生成每个输出时关注输入的不同部分。自注意力是注意力的一个变体，它计算序列内所有位置之间的依赖关系。",
        "entities": ["注意力机制", "自注意力", "输出", "依赖关系"],
        "entity_types": {"注意力机制": "机制", "自注意力": "机制", "输出": "概念", "依赖关系": "概念"}
    },
    {
        "id": "doc_018",
        "content": "链接预测是图数据分析的重要任务，旨在预测图中两个节点之间可能存在的关系。例如，在社交网络中预测用户之间的好友关系。",
        "entities": ["链接预测", "图数据", "节点", "关系", "社交网络"],
        "entity_types": {"链接预测": "任务", "图数据": "数据类型", "节点": "概念", "关系": "概念", "社交网络": "领域"}
    },
    {
        "id": "doc_019",
        "content": "Neo4j使用Cypher查询语言操作图数据。Cypher使用ASCII艺术语法，如CREATE创建节点， MATCH查找模式，RETURN返回结果。",
        "entities": ["Neo4j", "Cypher", "CREATE", "MATCH", "节点"],
        "entity_types": {"Neo4j": "工具", "Cypher": "语言", "CREATE": "操作", "MATCH": "操作", "节点": "概念"}
    },
    {
        "id": "doc_020",
        "content": "RAG系统中，检索结果的排序直接影响生成质量。Top-K检索返回最相关的K个文档。HNSW是一种高效的向量近邻搜索算法。",
        "entities": ["RAG", "Top-K", "HNSW", "向量近邻搜索", "检索结果"],
        "entity_types": {"RAG": "技术", "Top-K": "概念", "HNSW": "算法", "向量近邻搜索": "技术", "检索结果": "概念"}
    },
]

# 图关系数据 - 用于图检索评测
GRAPH_RELATIONS = [
    # RAG相关关系链
    ("doc_001", "是", "doc_005", "RAG包含检索和生成两个组件"),
    ("doc_005", "使用", "doc_002", "RAG使用向量检索技术"),
    ("doc_002", "基于", "doc_004", "向量检索基于Embeddings技术"),
    ("doc_004", "是", "doc_009", "Embeddings支撑语义搜索"),

    # BERT/GPT/Transformer关系链 - 突出图谱必要性
    ("doc_013", "是", "doc_014", "Transformer是BERT的基础架构"),
    ("doc_013", "是", "doc_015", "Transformer也是GPT的基础架构"),
    ("doc_014", "用于", "doc_003", "BERT相关技术可用于知识图谱构建"),
    ("doc_015", "由", "doc_013", "ChatGPT基于Transformer架构"),
    ("doc_013", "使用", "doc_017", "Transformer使用注意力机制"),
    ("doc_017", "是", "doc_013", "自注意力是Transformer的核心"),
    ("doc_014", "基于", "doc_016", "BERT基于词嵌入技术发展而来"),
    ("doc_016", "用于", "doc_002", "Word2Vec词嵌入用于向量检索"),

    # 知识图谱关系
    ("doc_003", "存储于", "doc_019", "知识图谱存储在Neo4j中"),
    ("doc_007", "链接到", "doc_003", "实体链接技术连接文本到知识图谱"),
    ("doc_011", "结合", "doc_003", "RAG可与知识图谱结合"),
    ("doc_011", "支持", "doc_006", "知识图谱RAG支持多跳推理"),

    # 链接预测相关
    ("doc_008", "用于", "doc_018", "图神经网络可用于链接预测"),
    ("doc_003", "支持", "doc_018", "知识图谱支撑链接预测任务"),
    ("doc_018", "应用于", "doc_003", "链接预测应用于知识图谱"),

    # 检索相关
    ("doc_010", "结合", "doc_002", "混合检索结合向量检索"),
    ("doc_010", "使用", "doc_002", "混合检索使用BM25和向量检索"),
    ("doc_020", "使用", "doc_002", "RAG使用HNSW进行向量搜索"),
]

# 测试查询 - 覆盖不同类型
EVAL_QUERIES = [
    # === 向量检索擅长的语义理解 ===
    {
        "id": "q1",
        "query": "什么是RAG技术？",
        "type": "事实型",
        "expected_docs": ["doc_001", "doc_005", "doc_011"],
        "requires_graph": False,  # 主要靠语义理解
        "difficulty": "easy"
    },
    {
        "id": "q2",
        "query": "向量检索和词嵌入有什么关系？",
        "type": "解释型",
        "expected_docs": ["doc_002", "doc_004", "doc_009", "doc_016"],
        "requires_graph": False,
        "difficulty": "medium"
    },
    {
        "id": "q3",
        "query": "语义搜索和关键词匹配的区别是什么？",
        "type": "对比型",
        "expected_docs": ["doc_009", "doc_010"],
        "requires_graph": False,
        "difficulty": "medium"
    },

    # === 图检索擅长的关系推理 ===
    {
        "id": "q4",
        "query": "BERT和GPT有什么关系？它们都基于什么架构？",
        "type": "多跳推理",
        "expected_docs": ["doc_013", "doc_014", "doc_015"],
        "requires_graph": True,  # 需要理解BERT和GPT都基于Transformer的关系
        "difficulty": "hard"
    },
    {
        "id": "q5",
        "query": "哪些技术在知识图谱中有应用？",
        "type": "关系查询",
        "expected_docs": ["doc_003", "doc_007", "doc_008", "doc_011", "doc_018"],
        "requires_graph": True,  # 需要通过关系链路发现
        "difficulty": "hard"
    },
    {
        "id": "q6",
        "query": "Word2Vec和BERT之间有什么技术演进关系？",
        "type": "多跳推理",
        "expected_docs": ["doc_004", "doc_014", "doc_016"],
        "requires_graph": True,  # 需要理解 Word2Vec -> BERT 的演进
        "difficulty": "hard"
    },
    {
        "id": "q7",
        "query": "ChatGPT和BERT在架构上有什么共同点？",
        "type": "关系对比",
        "expected_docs": ["doc_013", "doc_014", "doc_015"],
        "requires_graph": True,
        "difficulty": "hard"
    },
    {
        "id": "q8",
        "query": "RAG系统可以结合哪些技术来增强性能？",
        "type": "聚合查询",
        "expected_docs": ["doc_002", "doc_003", "doc_010", "doc_011", "doc_020"],
        "requires_graph": True,  # 需要通过关系发现多种技术
        "difficulty": "medium"
    },

    # === 混合检索场景 ===
    {
        "id": "q9",
        "query": "如何构建一个完整的RAG系统？",
        "type": "流程型",
        "expected_docs": ["doc_001", "doc_005", "doc_012"],
        "requires_graph": False,
        "difficulty": "medium"
    },
    {
        "id": "q10",
        "query": "链接预测在知识图谱中有什么应用？",
        "type": "应用型",
        "expected_docs": ["doc_003", "doc_008", "doc_018"],
        "requires_graph": True,
        "difficulty": "medium"
    },
]


# ============================================================================
# 评测指标计算函数
# ============================================================================

def compute_recall_at_k(
    retrieved_ids: List[str],
    relevant_ids: Set[str],
    k: int
) -> float:
    """计算 Recall@K

    Recall@K = |relevant_in_retrieved| / |relevant|
    """
    if not relevant_ids:
        return 0.0

    retrieved_k = set(retrieved_ids[:k])
    relevant_in_retrieved = retrieved_k & relevant_ids

    return len(relevant_in_retrieved) / len(relevant_ids)


def compute_ndcg_at_k(
    retrieved_ids: List[str],
    relevant_ids: Set[str],
    k: int,
    relevance_scores: Dict[str, float] = None
) -> float:
    """计算 NDCG@K (Normalized Discounted Cumulative Gain)

    NDCG = DCG / IDCG
    DCG = sum(relevance[i] / log2(i+1))
    """
    if not relevant_ids:
        return 0.0

    # Default: all relevant docs have relevance = 1
    if relevance_scores is None:
        relevance_scores = {doc_id: 1.0 for doc_id in relevant_ids}

    # DCG
    dcg = 0.0
    for i, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in relevant_ids:
            relevance = relevance_scores.get(doc_id, 1.0)
            dcg += relevance / math.log2(i + 2)  # i+2 because i is 0-indexed

    # IDCG (ideal DCG)
    sorted_relevance = sorted(relevance_scores.values(), reverse=True)
    idcg = 0.0
    for i, rel in enumerate(sorted_relevance[:k]):
        idcg += rel / math.log2(i + 2)

    if idcg == 0:
        return 0.0

    return dcg / idcg


def compute_mrr(retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
    """计算 MRR (Mean Reciprocal Rank)

    MRR = 1 / rank_of_first_relevant_doc
    """
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def compute_map(
    retrieved_ids: List[str],
    relevant_ids: Set[str]
) -> float:
    """计算 MAP (Mean Average Precision)

    MAP = average of precision@k for each relevant doc
    """
    if not relevant_ids:
        return 0.0

    precisions = []
    relevant_found = 0

    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            relevant_found += 1
            precision_at_i = relevant_found / (i + 1)
            precisions.append(precision_at_i)

    if not precisions:
        return 0.0

    return sum(precisions) / len(relevant_ids)


def compute_hit_rate_at_k(
    retrieved_ids: List[str],
    relevant_ids: Set[str],
    k: int
) -> float:
    """计算 Hit Rate@K (也叫 Recall@K with binary relevance)

    1 if any relevant doc is in top-k, else 0
    """
    retrieved_k = set(retrieved_ids[:k])
    return 1.0 if retrieved_k & relevant_ids else 0.0


# ============================================================================
# 图检索指标
# ============================================================================

def compute_graph_retrieval_metrics(
    graph_retrieved_ids: List[str],
    relevant_ids: Set[str],
    hop_counts: Dict[str, int] = None
) -> Dict[str, float]:
    """计算图检索专属指标

    Args:
        graph_retrieved_ids: 图检索返回的文档ID列表
        relevant_ids: 正确答案的文档ID集合
        hop_counts: 每个文档的跳数 (可选)

    Returns:
        图检索指标字典
    """
    retrieved_set = set(graph_retrieved_ids)

    metrics = {
        # 基础召回
        "graph_recall": len(retrieved_set & relevant_ids) / len(relevant_ids) if relevant_ids else 0,

        # 命中率
        "graph_hit_rate": 1.0 if retrieved_set & relevant_ids else 0.0,

        # MRR
        "graph_mrr": compute_mrr(graph_retrieved_ids, relevant_ids),

        # 关系路径覆盖 (如果有)
        "path_coverage": 0.0,
    }

    # 如果有跳数信息，计算平均跳数
    if hop_counts:
        retrieved_hops = [hop_counts.get(doc_id, 0) for doc_id in graph_retrieved_ids if doc_id in relevant_ids]
        if retrieved_hops:
            metrics["avg_hop_count"] = sum(retrieved_hops) / len(retrieved_hops)
            metrics["min_hop_count"] = min(retrieved_hops)

    return metrics


def compute_hybrid_metrics(
    vector_retrieved: List[str],
    graph_retrieved: List[str],
    relevant_ids: Set[str],
    fusion_method: str = "rrf"
) -> Dict[str, float]:
    """计算混合检索指标

    Args:
        vector_retrieved: 向量检索结果
        graph_retrieved: 图检索结果
        relevant_ids: 正确答案
        fusion_method: 融合方法 ("rrf", "weighted", "union")

    Returns:
        混合检索指标
    """
    metrics = {}

    # 向量检索单独召回
    vector_recall = compute_recall_at_k(vector_retrieved, relevant_ids, k=10)
    metrics["vector_recall@10"] = vector_recall

    # 图检索单独召回
    graph_recall = compute_recall_at_k(graph_retrieved, relevant_ids, k=10)
    metrics["graph_recall@10"] = graph_recall

    # 各自命中情况
    vector_hit = 1.0 if set(vector_retrieved[:10]) & relevant_ids else 0.0
    graph_hit = 1.0 if set(graph_retrieved[:10]) & relevant_ids else 0.0
    metrics["vector_hit@10"] = vector_hit
    metrics["graph_hit@10"] = graph_hit

    # 互补覆盖率
    vector_set = set(vector_retrieved[:10])
    graph_set = set(graph_retrieved[:10])

    if fusion_method == "union":
        hybrid_set = vector_set | graph_set
    elif fusion_method == "rrf" or fusion_method == "weighted":
        # RRF: 取并集但保持相对顺序
        all_docs = list(dict.fromkeys(vector_retrieved + graph_retrieved))
        hybrid_set = set(all_docs[:10])
    else:
        hybrid_set = vector_set | graph_set

    hybrid_recall = len(hybrid_set & relevant_ids) / len(relevant_ids) if relevant_ids else 0
    metrics["hybrid_recall@10"] = hybrid_recall

    # 各自贡献度
    vector_only = vector_set - graph_set
    graph_only = graph_set - vector_set
    common = vector_set & graph_set

    metrics["vector_only_count"] = len(vector_only)
    metrics["graph_only_count"] = len(graph_only)
    metrics["common_count"] = len(common)

    # 互补率
    if hybrid_recall > 0:
        vector_contribution = len((vector_set & relevant_ids)) / (len(hybrid_set & relevant_ids) if hybrid_set & relevant_ids else 1)
        graph_contribution = len((graph_set & relevant_ids)) / (len(hybrid_set & relevant_ids) if hybrid_set & relevant_ids else 1)
        metrics["vector_contribution"] = vector_contribution
        metrics["graph_contribution"] = graph_contribution

    return metrics


# ============================================================================
# 测试类
# ============================================================================

class TestRetrievalMetrics:
    """检索评测指标测试"""

    def test_recall_at_k_basic(self):
        """测试 Recall@K 基本计算"""
        retrieved = ["doc_a", "doc_b", "doc_c", "doc_d", "doc_e"]
        relevant = {"doc_a", "doc_c"}

        # Recall@3: 1/2 = 0.5 (doc_a在top-3中，doc_c不在)
        # 但实际doc_a在位置0，所以 recall@3 = 1/2 = 0.5
        # 让我重新看: top-3 = doc_a, doc_b, doc_c
        # relevant = {doc_a, doc_c}，所以2个在top-3中
        recall_3 = compute_recall_at_k(retrieved, relevant, k=3)
        assert recall_3 == 1.0  # 修正：doc_a, doc_b, doc_c都在，2个relevant都在

        # Recall@5: 2/2 = 1.0
        recall_5 = compute_recall_at_k(retrieved, relevant, k=5)
        assert recall_5 == 1.0

        # Recall@1: 1/2 = 0.5 (doc_a在top-1中)
        recall_1 = compute_recall_at_k(retrieved, relevant, k=1)
        assert recall_1 == 0.5

    def test_ndcg_at_k(self):
        """测试 NDCG@K 计算"""
        retrieved = ["doc_a", "doc_b", "doc_c"]
        relevant = {"doc_a", "doc_c"}
        relevance = {"doc_a": 1.0, "doc_c": 0.8}

        ndcg = compute_ndcg_at_k(retrieved, relevant, k=3, relevance_scores=relevance)
        assert 0 < ndcg <= 1.0

    def test_mrr(self):
        """测试 MRR 计算"""
        retrieved = ["doc_x", "doc_a", "doc_b", "doc_c"]
        relevant = {"doc_a", "doc_d"}

        # 首个相关文档在位置2
        mrr = compute_mrr(retrieved, relevant)
        assert abs(mrr - 0.5) < 0.01

    def test_map(self):
        """测试 MAP 计算"""
        # doc_a在位置0, doc_c在位置2
        retrieved = ["doc_a", "doc_b", "doc_c", "doc_d"]
        relevant = {"doc_a", "doc_c"}

        map_score = compute_map(retrieved, relevant)
        # AP for doc_a: 1/1 = 1.0 (found at position 0)
        # AP for doc_c: 2/3 = 0.667 (found at position 2)
        # MAP = (1.0 + 0.667) / 2 = 0.833
        expected = (1.0 + 2/3) / 2
        assert abs(map_score - expected) < 0.01

    def test_hit_rate(self):
        """测试 Hit Rate 计算"""
        retrieved = ["doc_x", "doc_y", "doc_z"]
        relevant = {"doc_a", "doc_b"}

        # 没有命中
        hit_1 = compute_hit_rate_at_k(retrieved, relevant, k=5)
        assert hit_1 == 0.0

        # 有命中
        retrieved_with_hit = ["doc_x", "doc_a", "doc_z"]
        hit_2 = compute_hit_rate_at_k(retrieved_with_hit, relevant, k=5)
        assert hit_2 == 1.0


class TestGraphRetrievalMetrics:
    """图检索评测测试"""

    def test_graph_recall(self):
        """测试图检索召回率"""
        retrieved = ["doc_001", "doc_002", "doc_003", "doc_004"]
        relevant = {"doc_001", "doc_003"}

        metrics = compute_graph_retrieval_metrics(retrieved, relevant)
        assert metrics["graph_recall"] == 1.0

    def test_graph_mrr(self):
        """测试图检索 MRR"""
        retrieved = ["doc_002", "doc_001", "doc_003"]
        relevant = {"doc_001", "doc_004"}

        metrics = compute_graph_retrieval_metrics(retrieved, relevant)
        assert abs(metrics["graph_mrr"] - 0.5) < 0.01

    def test_graph_with_hops(self):
        """测试带跳数信息的图检索"""
        retrieved = ["doc_001", "doc_002", "doc_003"]
        relevant = {"doc_001", "doc_003"}
        hop_counts = {"doc_001": 1, "doc_002": 2, "doc_003": 2}

        metrics = compute_graph_retrieval_metrics(retrieved, relevant, hop_counts)
        assert "avg_hop_count" in metrics
        assert metrics["avg_hop_count"] == 1.5


class TestHybridRetrievalMetrics:
    """混合检索评测测试"""

    def test_hybrid_recall(self):
        """测试混合检索召回率"""
        vector_retrieved = ["doc_001", "doc_002", "doc_003", "doc_004", "doc_005"]
        graph_retrieved = ["doc_003", "doc_006", "doc_007", "doc_008"]
        relevant = {"doc_003", "doc_006", "doc_009"}

        metrics = compute_hybrid_metrics(vector_retrieved, graph_retrieved, relevant, "union")

        # 向量召回: doc_003在top-5中，doc_006不在，relevant={003,006,009}，所以 1/3
        assert abs(metrics["vector_recall@10"] - 1/3) < 0.01
        # 图召回: doc_003和doc_006都在top-4中，relevant={003,006,009}，所以 2/3
        assert abs(metrics["graph_recall@10"] - 2/3) < 0.01
        # 混合召回: union后 {001,002,003,004,005,006,007,008}中relevant={003,006} = 2/3
        assert abs(metrics["hybrid_recall@10"] - 2/3) < 0.01

    def test_contribution_split(self):
        """测试贡献度分割"""
        vector_retrieved = ["doc_001", "doc_002", "doc_003"]
        graph_retrieved = ["doc_003", "doc_004", "doc_005"]
        relevant = {"doc_003", "doc_004"}

        metrics = compute_hybrid_metrics(vector_retrieved, graph_retrieved, relevant)

        # vector_set = {001, 002, 003}, graph_set = {003, 004, 005}
        # relevant = {003, 004}
        # vector_only = {001, 002, 003} - {003, 004, 005} = {001, 002}
        # graph_only = {003, 004, 005} - {001, 002, 003} = {004, 005}
        # common = {003}
        assert metrics["vector_only_count"] == 2  # doc_001, doc_002
        assert metrics["graph_only_count"] == 2  # doc_004, doc_005
        assert metrics["common_count"] == 1  # doc_003


class TestRetrievalDataset:
    """检索评测数据集测试"""

    def test_corpus_structure(self):
        """测试语料库结构"""
        assert len(CORPUS) > 0
        for doc in CORPUS:
            assert "id" in doc
            assert "content" in doc
            assert "entities" in doc

    def test_queries_structure(self):
        """测试查询结构"""
        assert len(EVAL_QUERIES) > 0
        for q in EVAL_QUERIES:
            assert "id" in q
            assert "query" in q
            assert "type" in q
            assert "expected_docs" in q
            assert "requires_graph" in q

    def test_graph_relation_coverage(self):
        """测试图关系覆盖"""
        # 验证图关系数据涵盖关键实体
        related_entities = set()
        for source, rel, target, desc in GRAPH_RELATIONS:
            related_entities.add(source)
            related_entities.add(target)

        # 确保多个文档在关系图中
        assert len(related_entities) >= 10

    def test_graph_dependent_queries(self):
        """测试需要图检索的查询"""
        graph_queries = [q for q in EVAL_QUERIES if q.get("requires_graph")]
        assert len(graph_queries) >= 3

        # 这些查询应该涉及多跳或关系推理
        for q in graph_queries:
            assert q["difficulty"] in ["hard", "medium"]


class TestEndToEndScenarios:
    """端到端场景测试"""

    def test_fact_query_scenario(self):
        """事实型查询场景"""
        # q1: "什么是RAG技术？"
        q1 = next(q for q in EVAL_QUERIES if q["id"] == "q1")
        relevant = set(q1["expected_docs"])

        # 模拟向量检索结果
        retrieved = ["doc_001", "doc_005", "doc_002", "doc_003", "doc_004"]

        recall = compute_recall_at_k(retrieved, relevant, k=5)
        ndcg = compute_ndcg_at_k(retrieved, relevant, k=5)
        mrr = compute_mrr(retrieved, relevant)

        assert recall > 0.5, "事实型查询应该获得较高召回"
        assert mrr > 0, "MRR应该大于0"

    def test_multihop_query_scenario(self):
        """多跳推理查询场景"""
        # q4: "BERT和GPT有什么关系？它们都基于什么架构？"
        q4 = next(q for q in EVAL_QUERIES if q["id"] == "q4")
        relevant = set(q4["expected_docs"])

        # 模拟向量检索结果（单一语义匹配）
        vector_only_retrieved = ["doc_014", "doc_013", "doc_001", "doc_002", "doc_003"]

        # 模拟图检索结果（关系路径）
        graph_retrieved = ["doc_013", "doc_014", "doc_015", "doc_017", "doc_016"]

        # 模拟混合检索结果
        hybrid_retrieved = ["doc_013", "doc_014", "doc_015", "doc_017", "doc_016",
                           "doc_001", "doc_002", "doc_003", "doc_004", "doc_005"]

        vector_recall = compute_recall_at_k(vector_only_retrieved, relevant, k=10)
        graph_recall = compute_recall_at_k(graph_retrieved, relevant, k=10)
        hybrid_recall = compute_recall_at_k(hybrid_retrieved, relevant, k=10)

        # 图检索或混合检索应该比纯向量检索更好
        assert graph_recall >= vector_recall, "图检索在多跳场景应优于纯向量检索"
        assert hybrid_recall >= vector_recall, "混合检索应该优于或等于纯向量检索"

    def test_comparison_query_scenario(self):
        """对比型查询场景"""
        # q3: "语义搜索和关键词匹配的区别是什么？"
        q3 = next(q for q in EVAL_QUERIES if q["id"] == "q3")
        relevant = set(q3["expected_docs"])

        retrieved = ["doc_009", "doc_010", "doc_002", "doc_004", "doc_001"]

        recall = compute_recall_at_k(retrieved, relevant, k=5)
        assert recall >= 0.5, "对比型查询应该能召回相关文档"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
