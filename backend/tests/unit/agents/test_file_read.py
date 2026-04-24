"""Tests for file_search and file_read tool split."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.tools.file_tools import (
    _search_files_fn,
    _format_search_results,
    _read_file_contents,
    _is_safe_path,
)


class TestFileSearchHelpers:
    """Test file_search internal helpers."""

    def test_search_files_fn_basic(self, tmp_path: Path):
        (tmp_path / "test.md").write_text("hello")
        (tmp_path / "test.txt").write_text("world")
        results = _search_files_fn(tmp_path, "./", "*.md")
        assert len(results) == 1
        assert results[0]["name"] == "test.md"

    def test_format_search_results_no_content(self):
        file_results = [
            {"name": "a.md", "path": "a.md", "size": 100, "modified": 1234567890},
        ]
        formatted = _format_search_results(file_results)
        assert len(formatted) == 1
        assert "index" in formatted[0]
        assert "name" in formatted[0]
        assert "preview" not in formatted[0]
        assert "has_content" not in formatted[0]

    def test_is_safe_path_valid(self, tmp_path: Path):
        assert _is_safe_path(str(tmp_path), "sub/file.md") is True

    def test_is_safe_path_traversal(self, tmp_path: Path):
        assert _is_safe_path(str(tmp_path), "../outside.md") is False


class TestFileReadHelpers:
    """Test file_read internal helpers."""

    def test_read_file_contents_md(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("# Hello\n\nWorld", encoding="utf-8")
        results = _read_file_contents(tmp_path, ["doc.md"])
        assert len(results) == 1
        assert results[0]["path"] == "doc.md"
        assert "# Hello" in results[0]["content"]
        assert results[0]["preview"] == "# Hello\n\nWorld"

    def test_read_file_contents_json(self, tmp_path: Path):
        (tmp_path / "data.json").write_text('{"key": "value"}', encoding="utf-8")
        results = _read_file_contents(tmp_path, ["data.json"])
        assert results[0]["content"] == '{\n  "key": "value"\n}'

    def test_read_file_contents_security_block(self, tmp_path: Path):
        results = _read_file_contents(tmp_path, ["../outside.txt"])
        assert results[0]["content"] == "[Security: Path validation failed]"

    def test_read_file_contents_not_found(self, tmp_path: Path):
        results = _read_file_contents(tmp_path, ["missing.txt"])
        assert results[0]["error"] == "File not found"

    def test_read_file_contents_respects_max_20(self, tmp_path: Path):
        for i in range(25):
            (tmp_path / f"f{i}.txt").write_text("x")
        paths = [f"f{i}.txt" for i in range(25)]
        results = _read_file_contents(tmp_path, paths)
        assert len(results) == 20


class TestFileTools:
    """Test file_search and file_read tools via build_tools."""

    @pytest.fixture
    def mock_registry(self):
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        registry.space_path = None
        return registry

    @pytest.mark.asyncio
    async def test_file_search_returns_metadata_only(self, mock_registry, tmp_path: Path):
        from app.agents.tools.file_tools import build_tools

        (tmp_path / "test.md").write_text("content here")
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        registry.space_path = str(tmp_path)

        tools = build_tools(registry)
        file_search = next(t for t in tools if t.name == "file_search")

        with patch("app.agents.tools.file_tools._parse_query") as mock_parse:
            mock_parse.return_value = ("./", "*.md")
            result = await file_search.ainvoke("find markdown")

        assert result["success"] is True
        assert len(result["files"]) == 1
        assert "preview" not in result["files"][0]
        assert "has_content" not in result["files"][0]

    @pytest.mark.asyncio
    async def test_file_read_returns_content(self, tmp_path: Path):
        from app.agents.tools.file_tools import build_tools

        (tmp_path / "doc.md").write_text("# Title\n\nBody", encoding="utf-8")
        registry = MagicMock()
        registry.db = MagicMock()
        registry.user = MagicMock()
        registry.space_path = str(tmp_path)

        tools = build_tools(registry)
        file_read = next(t for t in tools if t.name == "file_read")

        result = await file_read.ainvoke({"file_paths": ["doc.md"]})

        assert result["success"] is True
        assert len(result["files"]) == 1
        assert "# Title" in result["files"][0]["content"]
        assert "preview" in result["files"][0]
