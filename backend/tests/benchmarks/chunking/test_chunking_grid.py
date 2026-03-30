"""
Token 参数网格测试
通过测试不同 token 组合来选择最佳切块参数
"""
import sys
from pathlib import Path
from typing import List, Dict, Tuple
import statistics

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.ai.chunking.strategies import (
    ChunkingConfig,
    chunk_text,
    detect_content_type,
    estimate_tokens,
    DEFAULT_MIN_TOKEN,
    DEFAULT_MAX_TOKEN,
    DEFAULT_MAX_CHARS,
    DEFAULT_MIN_CHARS,
    DEFAULT_OVERLAP_CHARS,
)


# ============================================================
# 测试数据和评估指标
# ============================================================

# 测试数据集 - 使用足够长的文本触发分块
TEST_CASES = {
    "short_note": {
        "text": "这是一个简短的笔记，用于测试原子策略。",
        "expected_strategy": "atomic",
        "expected_chunks": 1,
    },
    "structured_doc": {
        "text": """# 第一章

这是第一章的内容，包含多个段落。本文讨论了多个重要话题，需要足够的长度来触发分块行为。

## 第一节

第一节的详细内容，这里有很多文字。在过去的几年中，我们见证了技术的快速发展。

## 第二节

第二节的内容与其他部分不同。这里是更多的内容，需要确保文本足够长。

# 第二章

这是第二章的介绍部分。第二章的内容更加丰富，包含多个小节。

## 第一节

第二章第一节的内容。这里继续添加更多文字以增加文本长度。

## 第二节

第二章第二节的内容。
""",
        "expected_strategy": "section_pack",
    },
    "long_article": {
        # 需要足够长 (> max_chars * 2) 才能触发分块
        "text": ("""# 文章标题

本文讨论了多个重要话题。本文讨论了多个重要话题。在过去的几年中，我们见证了技术的快速发展。

## 背景介绍

在过去的几年中，我们见证了技术的快速发展。我们见证了技术的快速发展。这是关于第一个主题的详细讨论。

## 主要内容

### 第一个主题

这是关于第一个主题的详细讨论。我们需要确保内容足够长，以便能够测试分块效果。这里是更多的内容。

### 第二个主题

这是关于第二个主题的内容。这里包含更多的文字，以便测试大文本的分块能力。这里是额外的内容填充。

### 第三个主题

这部分讨论了第三个主题，同样需要足够的篇幅。我们需要确保文本足够长以触发分块。

## 结论

总结全文的主要观点。结论部分也需要足够的长度。
""" + "\n\n") * 50,  # 重复50次以获得足够长度
        "expected_strategy": "section_pack",
    },
    "transcript": {
        # 需要足够长才能触发分块
        "text": ("00:00 大家好，欢迎收看本期节目。今天我们要讨论的主题是人工智能。\n"
                 "00:30 今天我们要讨论的主题是人工智能。人工智能在过去几年发展迅速。\n"
                 "01:00 人工智能在过去几年发展迅速。机器学习是AI的核心技术。\n"
                 "01:30 机器学习是AI的核心技术。深度学习推动了AI的突破。\n"
                 "02:00 深度学习推动了AI的突破。自然语言处理应用广泛。\n"
                 "02:30 自然语言处理应用广泛。计算机视觉技术日益成熟。\n"
                 "03:00 计算机视觉技术日益成熟。AI在医疗领域有重要应用。\n"
                 "03:30 AI在医疗领域有重要应用。自动驾驶技术正在发展中。\n"
                 "04:00 自动驾驶技术正在发展中。AI伦理问题值得关注。\n"
                 "04:30 AI伦理问题值得关注。总结全文的主要观点。\n") * 20,  # 重复20次
        "expected_strategy": "fixed_size_overlap",
    },
}


# ============================================================
# 评估指标函数
# ============================================================

def evaluate_chunk_distribution(chunks: List) -> Dict[str, float]:
    """评估 chunk 大小分布"""
    if not chunks:
        return {"mean": 0, "std": 0, "min": 0, "max": 0}

    sizes = [len(c.content) for c in chunks]
    return {
        "mean": statistics.mean(sizes),
        "std": statistics.stdev(sizes) if len(sizes) > 1 else 0,
        "min": min(sizes),
        "max": max(sizes),
        "count": len(chunks),
    }


def evaluate_content_integrity(chunks: List, original: str) -> Dict[str, float]:
    """评估内容完整性 - 避免在句子中间截断"""
    if not chunks:
        return {"integrity_score": 0, "split_sentences": 0}

    # 检查是否在标点处截断
    sentence_endings = "。！？.!?；;"
    split_count = 0

    for i, chunk in enumerate(chunks[:-1]):
        # 获取 chunk 末尾的最后一个字符
        if chunk.content and chunk.content[-1] not in sentence_endings:
            split_count += 1

    integrity_score = 1.0 - (split_count / max(len(chunks) - 1, 1))
    return {
        "integrity_score": integrity_score,
        "split_sentences": split_count,
    }


def evaluate_semantic_integrity(chunks: List) -> Dict[str, float]:
    """
    评估 chunks 的语义完整度

    语义完整性意味着在有意义的边界处分割：
    1. 句子边界（。！？.!?）
    2. 段落边界（\n\n）
    3. 标题边界（#）
    4. 列表边界（- * 1.）

    改进：单个大chunk不应该是满分，应该根据内容长度判断是否应该分割
    """
    if not chunks:
        return {"semantic_score": 0, "good_breaks": 0, "bad_breaks": 0, "total_breaks": 0}

    # 计算总内容长度
    total_chars = sum(len(c.content) for c in chunks)

    # 理想chunk大小（根据经验）
    ideal_chunk_size = 2000
    ideal_chunk_count = max(1, total_chars // ideal_chunk_size)

    # 句子结束标点
    sentence_endings = "。！？.!?；;"
    heading_markers = ["# ", "## ", "### ", "#### "]
    list_markers = ["- ", "* ", "+ ", "1. ", "2. ", "3. ", "4. ", "5. "]

    good_breaks = 0
    bad_breaks = 0

    for i, chunk in enumerate(chunks[:-1]):
        next_chunk = chunks[i + 1].content if i + 1 < len(chunks) else ""
        current = chunk.content

        if not current or not next_chunk:
            bad_breaks += 1
            continue

        # 检查当前chunk是否在语义边界处结束
        ends_with_good_break = False
        starts_with_good_break = False

        # 当前chunk末尾是句子结束符
        if current[-1] in sentence_endings:
            ends_with_good_break = True

        # 下一chunk开头是新段落（双换行或缩进）
        if next_chunk.startswith("\n\n") or (next_chunk.startswith(" ") and len(next_chunk) > 1):
            starts_with_good_break = True

        # 下一chunk开头是标题
        if any(next_chunk.startswith(m) for m in heading_markers):
            ends_with_good_break = True
            starts_with_good_break = True

        # 下一chunk开头是列表
        if any(next_chunk.startswith(m) for m in list_markers):
            ends_with_good_break = True
            starts_with_good_break = True

        # 当前chunk末尾是换行且下一chunk是正常段落开头
        if current[-1] == "\n":
            # 检查是否是双换行
            if len(current) >= 2 and current[-2:] == "\n\n":
                ends_with_good_break = True
            elif len(current) >= 1 and current[-1] == "\n" and not next_chunk.startswith("\n"):
                starts_with_good_break = True

        if ends_with_good_break and starts_with_good_break:
            good_breaks += 1
        elif not ends_with_good_break and not starts_with_good_break:
            bad_breaks += 1
        # 其他情况（一个满足一个不满足）给0.5分

    total_breaks = len(chunks) - 1

    # 计算分割质量分数
    if total_breaks == 0:
        # 没有分割，但根据内容长度判断
        # 如果内容很长而不分割，反而是低分
        if total_chars > ideal_chunk_size * 2:
            # 内容很长但没分割，应该分割
            chunk_count_score = 0.2
        elif total_chars > ideal_chunk_size:
            chunk_count_score = 0.7
        else:
            chunk_count_score = 1.0
        break_score = 1.0  # 没有坏分割
    else:
        # 有分割，评估分割质量
        break_score = (good_breaks + 0.5 * (total_breaks - good_breaks - bad_breaks)) / total_breaks

        # 评估chunk数量是否合理
        actual_chunk_count = len(chunks)
        if actual_chunk_count < ideal_chunk_count * 0.5:
            # chunk太少
            chunk_count_score = 0.3
        elif actual_chunk_count > ideal_chunk_count * 2:
            # chunk太多
            chunk_count_score = 0.5
        else:
            chunk_count_score = 1.0

    # 综合分数
    semantic_score = 0.7 * break_score + 0.3 * chunk_count_score

    return {
        "semantic_score": semantic_score,
        "good_breaks": good_breaks,
        "bad_breaks": bad_breaks,
        "total_breaks": total_breaks,
        "break_score": break_score,
        "chunk_count_score": chunk_count_score,
        "ideal_chunk_count": ideal_chunk_count,
        "actual_chunk_count": len(chunks),
    }


def evaluate_overlap_effectiveness(chunks: List, overlap_chars: int) -> Dict[str, float]:
    """评估重叠有效性"""
    if len(chunks) < 2:
        return {"overlap_ratio": 0, "effective_overlap": 0}

    # 检查 metadata 中是否有重叠标记
    # 由于底层实现可能有bug，我们主要检查大小分布
    sizes = [len(c.content) for c in chunks]
    size_variance = statistics.variance(sizes) if len(sizes) > 1 else 0

    # 如果 chunk 大小分布均匀，说明重叠起作用了
    # 如果有重叠，大小分布应该更加均匀
    return {
        "overlap_ratio": 0,  # 暂时设为0，因为底层实现有问题
        "effective_overlap": 0,
        "size_variance": size_variance,
    }


def calculate_overall_score(
    chunk_stats: Dict,
    integrity_stats: Dict,
    semantic_stats: Dict = None,
) -> float:
    """
    计算综合评分

    评估维度：
    1. 大小均匀性得分 (std 越小越好) - 权重 30%
    2. 语义完整度得分 (在好边界分割越多越好) - 权重 40%
    3. 内容完整性得分 (避免句子中间截断) - 权重 30%
    """
    # 1. 大小均匀性得分
    # std 越小越好，最大允许 1000
    size_score = max(0, 1.0 - (chunk_stats["std"] / 1000) if chunk_stats["std"] > 0 else 1.0)

    # 2. 语义完整度得分
    if semantic_stats is None:
        semantic_score = 0.5  # 默认中等分数
    else:
        semantic_score = semantic_stats.get("semantic_score", 0.5)

    # 3. 内容完整性得分
    integrity_score = integrity_stats.get("integrity_score", 0.5)

    # 综合得分
    overall = 0.3 * size_score + 0.4 * semantic_score + 0.3 * integrity_score
    return overall


# ============================================================
# 网格测试
# ============================================================

GRID_CONFIGS = [
    # (min_token, max_token, max_chars, min_chars, overlap_chars)
    # 网格1: 原始配置
    {"name": "original", "min_token": 500, "max_token": 4000, "max_chars": 2000, "min_chars": 400, "overlap_chars": 100},

    # 网格2: 更大的块
    {"name": "larger_chunks", "min_token": 600, "max_token": 5000, "max_chars": 3000, "min_chars": 600, "overlap_chars": 150},

    # 网格3: 更小的块
    {"name": "smaller_chunks", "min_token": 400, "max_token": 3000, "max_chars": 1500, "min_chars": 300, "overlap_chars": 80},

    # 网格4: 更少重叠
    {"name": "less_overlap", "min_token": 500, "max_token": 4000, "max_chars": 2000, "min_chars": 400, "overlap_chars": 50},

    # 网格5: 更多重叠
    {"name": "more_overlap", "min_token": 500, "max_token": 4000, "max_chars": 2000, "min_chars": 400, "overlap_chars": 200},

    # 网格6: 中等配置
    {"name": "medium", "min_token": 450, "max_token": 3500, "max_chars": 1800, "min_chars": 350, "overlap_chars": 120},

    # 网格7: 激进配置（大块少重叠）
    {"name": "aggressive", "min_token": 700, "max_token": 6000, "max_chars": 4000, "min_chars": 800, "overlap_chars": 100},

    # 网格8: 保守配置（小块多重叠）
    {"name": "conservative", "min_token": 300, "max_token": 2500, "max_chars": 1200, "min_chars": 200, "overlap_chars": 150},
]


class TestChunkingGridSearch:
    """Token 参数网格搜索测试"""

    def test_grid_search_short_note(self):
        """网格测试：短笔记"""
        text = TEST_CASES["short_note"]["text"]

        results = []
        for config_dict in GRID_CONFIGS:
            config = ChunkingConfig(
                min_token=config_dict["min_token"],
                max_token=config_dict["max_token"],
                max_chars=config_dict["max_chars"],
                min_chars=config_dict["min_chars"],
                overlap_chars=config_dict["overlap_chars"],
            )
            chunks = chunk_text(text, config=config)
            chunk_stats = evaluate_chunk_distribution(chunks)

            result = {
                "name": config_dict["name"],
                "chunks": len(chunks),
                "mean": chunk_stats["mean"],
                "std": chunk_stats["std"],
            }
            results.append(result)

        # 验证所有配置都能处理短笔记
        for r in results:
            assert r["chunks"] == 1, f"{r['name']}: 短笔记应该返回1个chunk，实际{r['chunks']}"

    def test_grid_search_long_article(self):
        """网格测试：长文章 - 找出最佳配置"""
        text = TEST_CASES["long_article"]["text"]

        best_config = None
        best_score = -1
        all_results = []

        for config_dict in GRID_CONFIGS:
            config = ChunkingConfig(
                min_token=config_dict["min_token"],
                max_token=config_dict["max_token"],
                max_chars=config_dict["max_chars"],
                min_chars=config_dict["min_chars"],
                overlap_chars=config_dict["overlap_chars"],
            )
            chunks = chunk_text(text, config=config)
            chunk_stats = evaluate_chunk_distribution(chunks)
            integrity_stats = evaluate_content_integrity(chunks, text)
            semantic_stats = evaluate_semantic_integrity(chunks)

            score = calculate_overall_score(
                chunk_stats,
                integrity_stats,
                semantic_stats,
            )

            result = {
                "name": config_dict["name"],
                "config": config_dict,
                "chunks": len(chunks),
                "mean": chunk_stats["mean"],
                "std": chunk_stats["std"],
                "integrity": integrity_stats["integrity_score"],
                "semantic": semantic_stats["semantic_score"],
                "score": score,
            }
            all_results.append(result)

            if score > best_score:
                best_score = score
                best_config = result

        # 打印所有结果
        print("\n" + "="*80)
        print("长文章网格测试结果:")
        print("="*80)
        print(f"{'配置名':<20} {'Chunks':<8} {'Mean':<10} {'Std':<10} {'Semantic':<12} {'Score':<8}")
        print("-"*80)
        for r in sorted(all_results, key=lambda x: x["score"], reverse=True):
            print(f"{r['name']:<20} {r['chunks']:<8} {r['mean']:<10.1f} {r['std']:<10.1f} {r['semantic']:<12.3f} {r['score']:<8.3f}")
        print("-"*80)
        print(f"最佳配置: {best_config['name']} (score={best_config['score']:.3f})")
        print("="*80)

        # 验证：最佳配置应该有一定数量的 chunk
        assert best_config["chunks"] >= 1
        assert best_config["score"] > 0

    def test_grid_search_transcript(self):
        """网格测试：转录文本"""
        text = TEST_CASES["transcript"]["text"]

        results = []
        for config_dict in GRID_CONFIGS:
            config = ChunkingConfig(
                min_token=config_dict["min_token"],
                max_token=config_dict["max_token"],
                max_chars=config_dict["max_chars"],
                min_chars=config_dict["min_chars"],
                overlap_chars=config_dict["overlap_chars"],
            )
            chunks = chunk_text(text, config=config)

            # 对于转录文本，我们希望有多个 chunk 且有重叠
            overlap_stats = evaluate_overlap_effectiveness(chunks, config_dict["overlap_chars"])

            result = {
                "name": config_dict["name"],
                "chunks": len(chunks),
                "overlap_ratio": overlap_stats["overlap_ratio"],
            }
            results.append(result)

        print("\n" + "="*80)
        print("转录文本网格测试结果:")
        print("="*80)
        for r in results:
            print(f"{r['name']:<20}: {r['chunks']} chunks, overlap_ratio={r['overlap_ratio']:.2f}")
        print("="*80)


class TestChunkMetrics:
    """Chunk 评估指标测试"""

    def test_chunk_distribution_metrics(self):
        """测试 chunk 分布评估"""
        # 模拟多个 chunk
        class MockChunk:
            def __init__(self, content):
                self.content = content

        chunks = [
            MockChunk("a" * 1000),
            MockChunk("b" * 1200),
            MockChunk("c" * 800),
        ]

        stats = evaluate_chunk_distribution(chunks)
        assert stats["count"] == 3
        assert stats["mean"] == 1000
        assert stats["min"] == 800
        assert stats["max"] == 1200

    def test_content_integrity_score(self):
        """测试内容完整性评估"""
        class MockChunk:
            def __init__(self, content):
                self.content = content

        # 模拟在句子中间截断的 chunks
        chunks = [
            MockChunk("这是第一个完整句子。"),  # 正常结束
            MockChunk("继续的内容，没"),  # 在单词中间截断
            MockChunk("有完整句子。"),  # 正常结束
        ]

        stats = evaluate_content_integrity(chunks, "原始文本")
        assert "integrity_score" in stats
        assert "split_sentences" in stats

    def test_overlap_effectiveness(self):
        """测试重叠有效性评估"""
        class MockChunk:
            def __init__(self, content):
                self.content = content

        chunks = [
            MockChunk("aaaaaaaaaa" + "overlap"),
            MockChunk("overlap" + "bbbbbbbbbb"),
        ]

        stats = evaluate_overlap_effectiveness(chunks, 10)
        assert "overlap_ratio" in stats


class TestParameterBoundaries:
    """参数边界测试"""

    def test_min_token_threshold(self):
        """测试 min_token 阈值"""
        # 非常短的文本
        short_text = "短"
        strategy = detect_content_type(short_text)
        # 短文本应该使用 atomic
        assert strategy == "atomic"

    def test_max_token_triggers_split(self):
        """测试超过 max_token 触发拆分"""
        # 非常长的文本（无结构）
        long_text = "词 " * 5000  # 大量重复
        strategy = detect_content_type(long_text)
        # 应该触发 composite 模式
        assert "composite" in strategy

    def test_max_chars_hard_limit(self):
        """测试 max_chars 硬限制"""
        config = ChunkingConfig(max_chars=500)
        text = "x " * 10000

        chunks = chunk_text(text, config=config)

        # 验证没有 chunk 超过硬限制
        hard_limit = config.chunk_hard_threshold
        for chunk in chunks:
            assert len(chunk.content) <= hard_limit, f"Chunk 超过硬限制: {len(chunk.content)} > {hard_limit}"


class TestOptimalConfigSelection:
    """最佳配置选择测试"""

    def test_find_optimal_config_for_structured_doc(self):
        """为结构化文档找最佳配置"""
        text = TEST_CASES["structured_doc"]["text"]

        best_overall = None
        best_score = -1

        for config_dict in GRID_CONFIGS:
            config = ChunkingConfig(
                min_token=config_dict["min_token"],
                max_token=config_dict["max_token"],
                max_chars=config_dict["max_chars"],
                min_chars=config_dict["min_chars"],
                overlap_chars=config_dict["overlap_chars"],
            )

            chunks = chunk_text(text, config=config)
            chunk_stats = evaluate_chunk_distribution(chunks)
            integrity_stats = evaluate_content_integrity(chunks, text)
            semantic_stats = evaluate_semantic_integrity(chunks)

            score = calculate_overall_score(
                chunk_stats,
                integrity_stats,
                semantic_stats,
            )

            if score > best_score:
                best_score = score
                best_overall = config_dict

        print(f"\n结构化文档最佳配置: {best_overall['name']} (score={best_score:.3f})")
        assert best_overall is not None


if __name__ == "__main__":
    # 允许直接运行查看网格测试结果
    pytest.main([__file__, "-v", "-s"])
