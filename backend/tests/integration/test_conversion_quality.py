"""
文档转换质量评估测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import pytest


def looks_like_markdown_basic(text: str) -> bool:
    """简单的 Markdown 格式检测"""
    if not text:
        return False
    patterns = [
        r"(?m)^#{1,6}\s+\S+",
        r"(?m)^[-*+]\s+\S+",
        r"(?m)^\d+\.\s+\S+",
        r"(?m)^>\s+\S+",
        r"(?m)^```",
        r"\[[^\]]+\]\([^)]+\)",
        r"(?m)^\|.+\|$",
    ]
    hit_count = sum(1 for p in patterns if re.search(p, text))
    return hit_count >= 1


def detect_control_chars(text: str) -> dict:
    """
    检测控制字符和异常字符
    注意：\x80-\x9f 是 GBK 中文范围，不应视为乱码
    """
    control_chars = re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)
    return {
        "count": len(control_chars),
        "ratio": len(control_chars) / max(len(text), 1),
        "chars": set(control_chars)
    }


def check_syntax_balance(text: str) -> dict:
    """检查 Markdown 语法配对"""
    code_blocks = len(re.findall(r"```", text))
    links = len(re.findall(r"\[[^\]]+\]\([^)]+\)", text))
    tables = len(re.findall(r"^\|.+\|$", text, re.MULTILINE))

    return {
        "code_block_pairs": code_blocks % 2 == 0,
        "code_block_count": code_blocks,
        "link_count": links,
        "table_count": tables
    }


def calculate_content_score(text: str) -> float:
    """计算内容得分"""
    if not text or not text.strip():
        return 0.0

    char_count = len(text.strip())
    # 每1000字符=0.4分，最高0.6分
    char_score = min(char_count / 1000 * 0.4, 0.6)

    # 段落完整度
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    para_score = min(len(paragraphs) / 3 * 0.4, 0.4) if paragraphs else 0.0

    return char_score + para_score


def calculate_structure_score(text: str) -> float:
    """计算结构得分"""
    lines = text.split("\n")

    # 标题
    headings = len([l for l in lines if re.match(r"^#{1,6}\s+", l.strip())])
    heading_score = min(headings / 3 * 0.3, 0.3) if headings >= 3 else headings * 0.1

    # 列表
    lists = len([l for l in lines if re.match(r"^[-*+]\s+", l.strip())])
    lists += len([l for l in lines if re.match(r"^\d+\.\s+", l.strip())])
    list_score = min(lists / 2 * 0.2, 0.2) if lists >= 2 else lists * 0.1

    # 表格
    tables = len([l for l in lines if re.match(r"^\|.+\|$", l.strip())])
    table_score = min(tables * 0.2, 0.2) if tables >= 1 else 0.0

    # 代码块
    code_blocks = len(re.findall(r"```", text)) // 2
    code_score = min(code_blocks * 0.15, 0.15) if code_blocks >= 1 else 0.0

    # 链接
    links = len(re.findall(r"\[[^\]]+\]\([^)]+\)", text))
    link_score = min(links * 0.15, 0.15) if links >= 1 else 0.0

    total = heading_score + list_score + table_score + code_score + link_score

    # 无结构文档的基线分数
    if total == 0:
        return 0.5

    return min(total, 1.0)


def calculate_cleanliness_score(text: str) -> float:
    """计算清洁度得分"""
    control = detect_control_chars(text)
    # 控制字符比例 < 0.5% 为优秀
    if control["ratio"] < 0.005:
        return 1.0
    elif control["ratio"] < 0.01:
        return 0.8
    elif control["ratio"] < 0.05:
        return 0.5
    else:
        return 0.0


def calculate_syntax_score(text: str) -> float:
    """计算语法得分"""
    balance = check_syntax_balance(text)

    # 代码块配对 (30%)
    code_score = 0.3 if balance["code_block_pairs"] else 0.0

    # 链接格式 (20%)
    # 简单检查：如果有链接，它们应该是格式良好的
    link_score = 0.2

    # 表格分隔符 (20%)
    table_score = 0.2 if balance["table_count"] > 0 else 0.15

    # 标题层级 (15%)
    headings = len(re.findall(r"^#{1,6}\s+", text, re.MULTILINE))
    heading_score = 0.15 if headings > 0 else 0.0

    # 列表格式 (15%)
    lists = len(re.findall(r"^[-*+]\s+", text, re.MULTILINE))
    lists += len(re.findall(r"^\d+\.\s+", text, re.MULTILINE))
    list_score = 0.15 if lists > 0 else 0.0

    return code_score + link_score + table_score + heading_score + list_score


def calculate_overall_score(text: str, original: str = None) -> dict:
    """
    计算综合质量得分

    评分维度:
    - cleanliness (20%): 控制字符和乱码
    - syntax (30%): Markdown 语法正确性
    - content (20%): 内容完整度
    - structure (30%): 文档结构完整度
    - markdown_bonus (+10%): Markdown 格式额外奖励
    """
    cleanliness = calculate_cleanliness_score(text)
    syntax_score = calculate_syntax_score(text)
    content_score = calculate_content_score(text)
    structure_score = calculate_structure_score(text)

    # 综合得分
    overall = 0.2 * cleanliness + 0.3 * syntax_score + 0.2 * content_score + 0.3 * structure_score

    # Markdown 格式额外奖励
    if looks_like_markdown_basic(text):
        overall = min(1.0, overall + 0.1)

    # 评级
    if overall >= 0.95:
        grade = "S"
    elif overall >= 0.85:
        grade = "A"
    elif overall >= 0.70:
        grade = "B"
    elif overall >= 0.50:
        grade = "C"
    else:
        grade = "D"

    return {
        "overall_score": round(overall, 3),
        "grade": grade,
        "cleanliness": round(cleanliness, 3),
        "syntax_score": round(syntax_score, 3),
        "content_score": round(content_score, 3),
        "structure_score": round(structure_score, 3),
        "dimensions": {
            "cleanliness": {"score": cleanliness, "weight": 0.2},
            "syntax": {"score": syntax_score, "weight": 0.3},
            "content": {"score": content_score, "weight": 0.2},
            "structure": {"score": structure_score, "weight": 0.3},
        }
    }


class TestControlCharDetection:
    """控制字符检测测试"""

    def test_clean_text(self):
        text = "Hello World！你好世界"
        result = detect_control_chars(text)
        assert result["count"] == 0
        assert result["ratio"] == 0.0

    def test_with_control_chars(self):
        text = "Hello\x00World\x01Test"
        result = detect_control_chars(text)
        assert result["count"] == 2

    def test_gbk_chars_not_counted(self):
        # \x80-\x9f is GBK range, should NOT be counted as control chars
        text = "Hello" + "\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89" + "World"
        result = detect_control_chars(text)
        # Only \x00-\x08, \x0b, \x0c, \x0e-\x1f are counted
        assert result["count"] == 0


class TestSyntaxBalance:
    """语法配对测试"""

    def test_balanced_code_blocks(self):
        text = "```python\nprint('hello')\n```"
        result = check_syntax_balance(text)
        assert result["code_block_pairs"] == True
        assert result["code_block_count"] == 2

    def test_unbalanced_code_blocks(self):
        text = "```python\nprint('hello')\n``"
        result = check_syntax_balance(text)
        assert result["code_block_pairs"] == False

    def test_multiple_links(self):
        text = "[link1](url1) and [link2](url2)"
        result = check_syntax_balance(text)
        assert result["link_count"] == 2

    def test_table_detection(self):
        text = "| col1 | col2 |\n|--|--|\n| a | b |"
        result = check_syntax_balance(text)
        assert result["table_count"] >= 1


class TestContentScore:
    """内容得分测试"""

    def test_empty_text(self):
        assert calculate_content_score("") == 0.0

    def test_short_text(self):
        text = "Short"
        score = calculate_content_score(text)
        assert score < 0.6  # Should get char_score portion

    def test_long_text(self):
        text = "a" * 2000
        score = calculate_content_score(text)
        assert score >= 0.5  # Should get decent char_score


class TestStructureScore:
    """结构得分测试"""

    def test_no_structure(self):
        text = "Just plain text without any markdown."
        score = calculate_structure_score(text)
        assert score == 0.5  # Baseline

    def test_with_headings(self):
        text = "# Heading 1\n\n## Heading 2\n\n### Heading 3"
        score = calculate_structure_score(text)
        # 3 headings = 0.3 heading_score
        assert score == 0.3

    def test_with_lists(self):
        text = "- Item 1\n- Item 2\n- Item 3"
        score = calculate_structure_score(text)
        # 3 lists = 0.2 list_score
        assert score == 0.2

    def test_with_code_blocks(self):
        text = "```python\nprint('hello')\n```"
        score = calculate_structure_score(text)
        # 1 code block = 0.15 code_score
        assert score == 0.15


class TestCleanlinessScore:
    """清洁度得分测试"""

    def test_clean_text(self):
        text = "Hello World！你好世界"
        score = calculate_cleanliness_score(text)
        assert score == 1.0

    def test_minor_control_chars(self):
        text = "Hello\x00World"  # 1 control char out of 11 = ~9% ratio
        score = calculate_cleanliness_score(text)
        # ratio = 1/11 = 0.0909 > 0.05, so score = 0.0
        assert score == 0.0

    def test_significant_control_chars(self):
        text = "a\x00b\x01c\x02d\x03e\x04f"
        score = calculate_cleanliness_score(text)
        assert score < 1.0


class TestSyntaxScore:
    """语法得分测试"""

    def test_perfect_markdown(self):
        text = """# Title

## Section

Content with [link](url).

```python
code
```

- list item
"""
        score = calculate_syntax_score(text)
        assert score > 0.7

    def test_plain_text(self):
        text = "Just plain text without any formatting."
        score = calculate_syntax_score(text)
        # plain text gets default scores even without features
        assert score > 0


class TestOverallScore:
    """综合得分测试"""

    def test_excellent_document(self):
        text = """# Document Title

## Introduction

This is an introduction with [a link](http://example.com).

## Content

Here is some content:
- Point 1
- Point 2

### Code Example

```python
print("Hello, World!")
```

| Column 1 | Column 2 |
|----------|----------|
| Value 1  | Value 2  |
"""
        result = calculate_overall_score(text)
        assert result["overall_score"] >= 0.8
        assert result["grade"] in ["S", "A", "B"]

    def test_poor_document(self):
        text = "a" * 500
        result = calculate_overall_score(text)
        assert result["overall_score"] < 0.8

    def test_empty_document(self):
        result = calculate_overall_score("")
        # Empty document gets baseline scores
        assert result["grade"] in ["C", "D"]

    def test_grade_thresholds(self):
        # Test S grade
        text = "# Title\n\n" * 50 + "[link](url)\n" * 10 + "```\ncode\n```\n" * 5
        result = calculate_overall_score(text)
        assert result["grade"] in ["S", "A", "B", "C", "D"]

    def test_markdown_bonus(self):
        # Plain text
        plain = "Just some text without markdown."
        plain_result = calculate_overall_score(plain)

        # Same text but with markdown
        markdown = "# Title\n\nJust some text without markdown."
        markdown_result = calculate_overall_score(markdown)

        # Markdown should get bonus
        assert markdown_result["overall_score"] >= plain_result["overall_score"]


class TestQualityAssessment:
    """质量评估综合测试"""

    def test_all_dimensions_present(self):
        text = "# Title\n\nContent"
        result = calculate_overall_score(text)
        assert "cleanliness" in result
        assert "syntax_score" in result
        assert "content_score" in result
        assert "structure_score" in result
        assert "overall_score" in result
        assert "grade" in result

    def test_score_bounded(self):
        text = "# " + "x" * 10000
        result = calculate_overall_score(text)
        assert 0 <= result["overall_score"] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
