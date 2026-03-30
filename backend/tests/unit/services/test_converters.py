"""
转换器基础功能测试
"""
import sys
from pathlib import Path

# Add backend to path
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
from app.ai.converters import (
    _get_pandoc_path,
    _check_pandoc,
    _check_html2text,
    convert_docx_to_markdown,
    convert_rtf_to_markdown,
    convert_odt_to_markdown,
    convert_html_to_markdown,
    convert_pdf_to_markdown,
    needs_llm_conversion,
    looks_like_markdown_basic,
    _looks_like_ocr_or_garbled,
    _is_letter_or_cjk,
)


class TestNormalizeText:
    """normalize_text 函数测试"""

    def test_basic_normalization(self):
        assert normalize_text("hello") == "hello"

    def test_crlf_conversion(self):
        assert normalize_text("hello\r\nworld") == "hello\nworld"

    def test_cr_conversion(self):
        assert normalize_text("hello\rworld") == "hello\nworld"

    def test_null_removal(self):
        assert normalize_text("hello\x00world") == "helloworld"

    def test_bom_removal(self):
        assert normalize_text("\ufeffhello") == "hello"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_whitespace_only(self):
        # normalize_text 只处理 \r\n, \r, \x00 和 BOM，不移除 tab/换行
        result = normalize_text("   \t\n  ")
        assert "\x00" not in result  # 确保 null 字符被移除


class TestNormalizeMarkdown:
    """normalize_markdown 函数测试"""

    def test_basic_normalization(self):
        result = normalize_markdown("hello  \n\n\n\nworld")
        assert result == "hello\n\nworld"

    def test_line_rstrip(self):
        result = normalize_markdown("hello   \nworld   ")
        lines = result.split("\n")
        assert all(line == line.rstrip() for line in lines)

    def test_empty_string(self):
        assert normalize_markdown("") == ""

    def test_only_whitespace(self):
        assert normalize_markdown("   \n\n   ") == ""


class TestLooksLikeMarkdown:
    """looks_like_markdown 函数测试"""

    def test_heading(self):
        assert looks_like_markdown("# Hello World") == True

    def test_unordered_list(self):
        assert looks_like_markdown("- item 1\n- item 2") == True

    def test_ordered_list(self):
        assert looks_like_markdown("1. first\n2. second") == True

    def test_blockquote(self):
        assert looks_like_markdown("> quote text") == True

    def test_code_block(self):
        assert looks_like_markdown("```python\nprint('hi')\n```") == True

    def test_link(self):
        assert looks_like_markdown("[link](http://example.com)") == True

    def test_table(self):
        assert looks_like_markdown("| col1 | col2 |\n|------|------|") == True

    def test_plain_text(self):
        assert looks_like_markdown("This is just plain text without any markdown.") == False

    def test_empty_string(self):
        assert looks_like_markdown("") == False


class TestLooksLikeMarkdownBasic:
    """looks_like_markdown_basic 函数测试"""

    def test_with_heading(self):
        assert looks_like_markdown_basic("# heading") == True

    def test_with_link(self):
        assert looks_like_markdown_basic("[text](url)") == True

    def test_plain_text(self):
        assert looks_like_markdown_basic("plain text only") == False

    def test_empty(self):
        assert looks_like_markdown_basic("") == False


class TestSectionPathFromMetadata:
    """section_path_from_metadata 函数测试"""

    def test_explicit_section_path(self):
        metadata = {"section_path": "Introduction / Overview"}
        assert section_path_from_metadata(metadata) == "Introduction / Overview"

    def test_h1_key(self):
        metadata = {"h1": "Introduction", "h2": "Overview"}
        assert section_path_from_metadata(metadata) == "Introduction / Overview"

    def test_header_numeric_keys(self):
        metadata = {"Header 1": "Chapter 1", "Header 2": "Section A"}
        assert section_path_from_metadata(metadata) == "Chapter 1 / Section A"

    def test_empty_metadata(self):
        assert section_path_from_metadata({}) == None

    def test_none_metadata(self):
        assert section_path_from_metadata(None) == None

    def test_empty_section_path(self):
        metadata = {"section_path": "   "}
        assert section_path_from_metadata(metadata) == None


class TestBuildSectionPath:
    """build_section_path 函数测试"""

    def test_multiple_headings(self):
        result = build_section_path(["Intro", "Overview", "Summary"])
        assert result == "Intro / Overview / Summary"

    def test_single_heading(self):
        result = build_section_path(["Only One"])
        assert result == "Only One"

    def test_empty_list(self):
        assert build_section_path([]) == None

    def test_whitespace_only(self):
        assert build_section_path(["", "  ", "Intro"]) == "Intro"


class TestEstimateTokenCount:
    """estimate_token_count 函数测试"""

    def test_empty_string(self):
        assert estimate_token_count("") == 0

    def test_english_text(self):
        # "hello world" = 2 tokens (words)
        result = estimate_token_count("hello world")
        assert result >= 1

    def test_chinese_text(self):
        # Note: estimate_token_count uses \w+|[^\w\s] with re.UNICODE
        # Chinese chars are matched by [^\w\s] as a single token
        result = estimate_token_count("你好世界")
        assert result == 1

    def test_mixed_text(self):
        result = estimate_token_count("Hello 你好 World 世界")
        # "Hello" + "World" = 2 \w+ matches, Chinese chars = 4 [^\w\s] matches
        assert result >= 4

    def test_with_punctuation(self):
        result = estimate_token_count("Hello, world! 你好，世界！")
        assert result >= 3


class TestSplitMarkdownSections:
    """split_markdown_sections 函数测试"""

    def test_single_section_no_headings(self):
        text = "This is a simple paragraph without any headings."
        sections = split_markdown_sections(text)
        assert len(sections) >= 1
        assert "This is a simple paragraph" in sections[0]["content"]

    def test_with_headings(self):
        text = """# Title

Content under title

## Subtitle

Content under subtitle
"""
        sections = split_markdown_sections(text)
        assert len(sections) >= 2

    def test_empty_text(self):
        assert split_markdown_sections("") == []

    def test_only_whitespace(self):
        assert split_markdown_sections("   \n\n   ") == []


class TestSplitTextWithOverlap:
    """split_text_with_overlap 函数测试"""

    def test_short_text(self):
        text = "Short text"
        chunks = split_text_with_overlap(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1

    def test_long_text_split(self):
        text = "a" * 3000
        chunks = split_text_with_overlap(text, chunk_size=1000, chunk_overlap=100)
        assert len(chunks) >= 3

    def test_empty_text(self):
        assert split_text_with_overlap("") == []

    def test_invalid_chunk_size(self):
        with pytest.raises(ValueError):
            split_text_with_overlap("text", chunk_size=0)

    def test_negative_overlap(self):
        with pytest.raises(ValueError):
            split_text_with_overlap("text", chunk_overlap=-1)


class TestChooseSplitPoint:
    """_choose_split_point 函数测试"""

    def test_at_end(self):
        text = "hello world"
        result = _choose_split_point(text, 0, len(text))
        assert result == len(text)

    def test_finds_double_newline(self):
        text = "para1\n\npara2"
        result = _choose_split_point(text, 0, len(text))
        assert result > 0

    def test_finds_single_newline(self):
        text = "word1 word2\nword3"
        result = _choose_split_point(text, 0, len(text))
        assert result > 0


class TestPandocAvailability:
    """Pandoc 可用性测试"""

    def test_get_pandoc_path(self):
        path = _get_pandoc_path()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_check_pandoc(self):
        # This test just checks the function runs without error
        result = _check_pandoc()
        assert isinstance(result, bool)


class TestHtml2TextAvailability:
    """html2text 可用性测试"""

    def test_check_html2text(self):
        result = _check_html2text()
        assert isinstance(result, bool)


class TestNeedsLLMConversion:
    """needs_llm_conversion 函数测试"""

    def test_markdown_file_not_needed(self):
        # .md file that already looks like markdown
        assert needs_llm_conversion("test.md", "# Hello") == False

    def test_pdf_file_not_needed(self):
        # PDF that looks like markdown doesn't need LLM
        assert needs_llm_conversion("test.pdf", "# Hello") == False

    def test_unknown_format_needs_llm(self):
        # Unknown format without markdown needs LLM
        assert needs_llm_conversion("test.xyz", "plain text") == True

    def test_garbled_text_needs_llm(self):
        # Garbled text in known format needs LLM
        result = needs_llm_conversion("test.pdf", "a" * 100 + "\x00\x01\x02" * 20)
        assert result == True


class TestLooksLikeOcrOrGarbled:
    """_looks_like_ocr_or_garbled 函数测试"""

    def test_normal_text(self):
        assert _looks_like_ocr_or_garbled("This is normal text.") == False

    def test_empty_text(self):
        assert _looks_like_ocr_or_garbled("") == False

    def test_repeated_chars(self):
        # 10+ repeated characters
        assert _looks_like_ocr_or_garbled("aaaaaaaaaaa") == True

    def test_short_lines(self):
        # Many short lines (OCR characteristic)
        text = "\n".join(["a" * 10 for _ in range(20)])
        result = _looks_like_ocr_or_garbled(text)
        assert result == True


class TestIsLetterOrCjk:
    """_is_letter_or_cjk 函数测试"""

    def test_english_letters(self):
        assert _is_letter_or_cjk("a") == True
        assert _is_letter_or_cjk("Z") == True

    def test_chinese_chars(self):
        assert _is_letter_or_cjk("你") == True
        assert _is_letter_or_cjk("中") == True

    def test_japanese_chars(self):
        assert _is_letter_or_cjk("あ") == True

    def test_punctuation(self):
        assert _is_letter_or_cjk("!") == False
        # Chinese comma (U+FF0C) is not in the CJK range checked by _is_letter_or_cjk
        assert _is_letter_or_cjk("，") == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
