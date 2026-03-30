"""
Markdown工具函数测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app.ai.markdown_utils import (
    normalize_text,
    normalize_markdown,
    looks_like_markdown,
    section_path_from_metadata,
    split_markdown_sections,
    split_text_with_overlap,
    estimate_token_count,
    build_section_path,
    _choose_split_point,
)


class TestMarkdownUtils:
    """Markdown工具函数综合测试"""

    def test_normalize_text_preserves_content(self):
        text = "Hello World"
        assert normalize_text(text) == "Hello World"

    def test_normalize_text_converts_line_endings(self):
        assert normalize_text("a\r\nb\r\nc") == "a\nb\nc"
        assert normalize_text("a\rb\rc") == "a\nb\nc"

    def test_normalize_text_removes_null(self):
        assert normalize_text("a\x00b") == "ab"

    def test_normalize_text_removes_bom(self):
        assert normalize_text("\ufeffHello") == "Hello"

    def test_normalize_markdown_compacts_multiple_blank_lines(self):
        result = normalize_markdown("a\n\n\n\nb")
        assert result == "a\n\nb"

    def test_normalize_markdown_rstrips_lines(self):
        result = normalize_markdown("a   \nb   ")
        assert result == "a\nb"

    def test_looks_like_markdown_detects_heading(self):
        assert looks_like_markdown("# Title") == True

    def test_looks_like_markdown_detects_unordered_list(self):
        assert looks_like_markdown("- item") == True

    def test_looks_like_markdown_detects_ordered_list(self):
        assert looks_like_markdown("1. item") == True

    def test_looks_like_markdown_detects_blockquote(self):
        assert looks_like_markdown("> quote") == True

    def test_looks_like_markdown_detects_code_block(self):
        assert looks_like_markdown("```\ncode\n```") == True

    def test_looks_like_markdown_detects_link(self):
        assert looks_like_markdown("[text](url)") == True

    def test_looks_like_markdown_detects_table(self):
        assert looks_like_markdown("| a | b |\n|--|--|") == True

    def test_looks_like_markdown_rejects_plain_text(self):
        assert looks_like_markdown("Just plain text") == False

    def test_section_path_from_metadata_explicit(self):
        meta = {"section_path": "A / B / C"}
        assert section_path_from_metadata(meta) == "A / B / C"

    def test_section_path_from_metadata_h_keys(self):
        meta = {"h1": "A", "h2": "B", "h3": "C"}
        assert section_path_from_metadata(meta) == "A / B / C"

    def test_section_path_from_metadata_empty(self):
        assert section_path_from_metadata({}) == None

    def test_section_path_from_metadata_none(self):
        assert section_path_from_metadata(None) == None

    def test_build_section_path(self):
        assert build_section_path(["A", "B", "C"]) == "A / B / C"

    def test_build_section_path_empty(self):
        assert build_section_path([]) == None

    def test_estimate_token_count_empty(self):
        assert estimate_token_count("") == 0

    def test_estimate_token_count_english(self):
        # "hello world" = 2 words
        result = estimate_token_count("hello world")
        assert result >= 2

    def test_estimate_token_count_chinese(self):
        # Chinese chars are matched by [^\w\s] as a single token
        result = estimate_token_count("你好世界")
        assert result == 1

    def test_split_markdown_sections_simple(self):
        text = "# Title\n\nContent"
        sections = split_markdown_sections(text)
        assert len(sections) >= 1

    def test_split_markdown_sections_empty(self):
        assert split_markdown_sections("") == []

    def test_split_text_with_overlap_short(self):
        text = "short"
        chunks = split_text_with_overlap(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1

    def test_split_text_with_overlap_long(self):
        text = "a" * 3000
        chunks = split_text_with_overlap(text, chunk_size=500, chunk_overlap=50)
        assert len(chunks) >= 5

    def test_split_text_with_overlap_empty(self):
        assert split_text_with_overlap("") == []

    def test_choose_split_point_at_end(self):
        text = "hello world"
        result = _choose_split_point(text, 0, len(text))
        assert result == len(text)


class TestEdgeCases:
    """边界情况测试"""

    def test_unicode_text(self):
        text = "Hello 世界 🌍 🎉"
        result = normalize_text(text)
        assert "Hello" in result
        assert "世界" in result

    def test_mixed_line_endings(self):
        text = "line1\r\nline2\rline3\nline4"
        result = normalize_text(text)
        assert "\r" not in result

    def test_only_control_chars(self):
        # normalize_text only removes \x00, not other control chars
        text = "\x00\x01\x02\x03"
        result = normalize_text(text)
        # \x00 is removed, but \x01-\x03 remain
        assert result == "\x01\x02\x03"

    def test_markdown_with_special_chars(self):
        text = "# 标题\n\n`code` **bold** *italic* [link](url)"
        assert looks_like_markdown(text) == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
