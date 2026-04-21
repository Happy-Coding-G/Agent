"""
File Query Skill

本地文件系统查询，支持自然语言解析为 glob 模式，
具备路径遍历防护与扩展名白名单。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".pdf", ".docx", ".doc",
    ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
}


def _is_safe_path(base_path: str, target_path: str) -> bool:
    """Validate that target_path is within base_path to prevent path traversal."""
    try:
        base = Path(base_path).resolve()
        target = (base / target_path).resolve()
        return target.is_relative_to(base)
    except Exception:
        return False


def _fallback_parse(query: str) -> tuple[str, str]:
    """Fallback query parsing using simple pattern matching."""
    md_pattern = re.compile(r"\*?\.?md|markdown|文档")
    txt_pattern = re.compile(r"\.txt|text|文本")
    glob_pattern = re.compile(r"\*+\.[a-zA-Z0-9]+|\*+")

    path = "./"
    pattern = "*"

    glob_match = glob_pattern.search(query)
    if glob_match:
        pattern = glob_match.group()
        if "**" not in pattern and "." not in pattern:
            pattern = f"*.{pattern.lstrip('*')}"

    if md_pattern.search(query.lower()):
        pattern = "*.md"
    elif txt_pattern.search(query.lower()):
        pattern = "*.txt"

    return path, pattern


async def _parse_query(query: str) -> tuple[str, str]:
    """Parse user query into (path, pattern)."""
    try:
        from app.services.base import get_llm_client

        llm = get_llm_client(temperature=0)
        messages = [
            ("system", """你是一个本地文件查询助手。根据用户的自然语言查询，解析出要查询的路径和文件模式。

输出格式（JSON）：
{{
    "path": "要查询的目录路径，如果用户没有指定则为空",
    "pattern": "文件匹配模式（如 *.md, **/*.txt, report*.json）
}}

只返回JSON，不要其他内容。"""),
            ("human", query),
        ]
        result = await llm.ainvoke(messages)
        content = result.content if hasattr(result, "content") else str(result)

        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            return parsed.get("path", "./"), parsed.get("pattern", "*")
    except Exception as e:
        logger.warning(f"LLM parsing failed, using fallback: {e}")

    return _fallback_parse(query)


def _search_files(space_path: Path, interpreted_path: str, pattern: str) -> list[dict[str, Any]]:
    """Search for files matching the pattern within the validated path."""
    full_path = space_path / interpreted_path
    results: list[dict[str, Any]] = []

    if "**" in pattern:
        for match in full_path.rglob(pattern.replace("** /", "")):
            if match.is_file():
                rel_path = match.relative_to(space_path)
                results.append({
                    "name": match.name,
                    "path": str(rel_path),
                    "size": match.stat().st_size,
                    "modified": match.stat().st_mtime,
                })
    else:
        for match in full_path.glob(pattern):
            if match.is_file():
                rel_path = match.relative_to(space_path)
                results.append({
                    "name": match.name,
                    "path": str(rel_path),
                    "size": match.stat().st_size,
                    "modified": match.stat().st_mtime,
                })

    return [
        r for r in results
        if Path(r["name"]).suffix.lower() in ALLOWED_EXTENSIONS
    ]


def _read_files(space_path: Path, file_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read content of matched files (max 10)."""
    for file_result in file_results[:10]:
        try:
            file_path = space_path / file_result["path"]

            if not _is_safe_path(str(space_path), str(file_result["path"])):
                file_result["content"] = "[Security: Path validation failed]"
                continue

            suffix = file_path.suffix.lower()
            if suffix == ".md":
                file_result["content"] = file_path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".txt":
                file_result["content"] = file_path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".json":
                file_result["content"] = json.dumps(
                    json.loads(file_path.read_text(encoding="utf-8", errors="ignore")),
                    ensure_ascii=False, indent=2,
                )
            elif suffix in (".yaml", ".yml"):
                import yaml
                file_result["content"] = yaml.dump(
                    yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")),
                    allow_unicode=True,
                )
            else:
                content = file_path.read_bytes()
                file_result["content"] = (
                    content[:1000].decode("utf-8", errors="ignore") + "..."
                    if len(content) > 1000
                    else content.decode("utf-8", errors="ignore")
                )

            content = file_result.get("content", "")
            file_result["content_preview"] = (
                content[:500] + "..." if len(content) > 500 else content
            )

        except Exception as e:
            logger.warning(f"Failed to read {file_result.get('path')}: {e}")
            file_result["content"] = f"[Error reading file: {e}]"

    return file_results


def _format_results(file_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format the final results for display."""
    formatted = []
    for idx, result in enumerate(file_results, 1):
        formatted.append({
            "index": idx,
            "name": result.get("name", ""),
            "path": result.get("path", ""),
            "size": result.get("size", 0),
            "modified": result.get("modified", 0),
            "preview": result.get("content_preview", ""),
            "has_content": "content" in result and not result["content"].startswith("["),
        })
    return formatted


async def query_files(query: str, space_path: str) -> dict[str, Any]:
    """
    本地文件查询 Skill。

    Args:
        query: 用户的自然语言查询
        space_path: 空间根目录路径（用于安全校验）

    Returns:
        包含匹配文件列表及其内容预览的结果字典
    """
    if not query or not query.strip():
        return {"success": False, "query": query, "files": [], "error": "Empty query"}

    resolved_space = Path(space_path).resolve() if space_path else None
    if not resolved_space:
        return {"success": False, "query": query, "files": [], "error": "Space path not configured"}

    try:
        # 1. 解析查询
        interpreted_path, interpreted_pattern = await _parse_query(query.strip())

        # 2. 路径安全验证
        if not _is_safe_path(str(resolved_space), interpreted_path):
            return {
                "success": False,
                "query": query,
                "interpreted_path": interpreted_path,
                "interpreted_pattern": interpreted_pattern,
                "files": [],
                "error": "Path traversal detected. Access denied.",
            }

        full_path = resolved_space / interpreted_path
        if not full_path.exists():
            return {
                "success": False,
                "query": query,
                "interpreted_path": interpreted_path,
                "interpreted_pattern": interpreted_pattern,
                "files": [],
                "error": f"Path does not exist: {interpreted_path}",
            }

        # 3. 搜索文件
        file_results = _search_files(resolved_space, interpreted_path, interpreted_pattern)

        # 4. 读取内容
        file_results = _read_files(resolved_space, file_results)

        # 5. 格式化结果
        formatted = _format_results(file_results)

        return {
            "success": True,
            "query": query,
            "interpreted_path": interpreted_path,
            "interpreted_pattern": interpreted_pattern,
            "files": formatted,
            "error": None,
        }

    except Exception as e:
        logger.exception(f"File query failed: {e}")
        return {"success": False, "query": query, "files": [], "error": str(e)}
