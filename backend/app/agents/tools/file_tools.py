"""
File Tools - 包装 query_files skill + SpaceFileService
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".pdf", ".docx", ".doc",
    ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
}


class FileSearchInput(BaseModel):
    query: str = Field(description="自然语言查询，如'查找所有markdown文件'")


class FileReadInput(BaseModel):
    file_paths: List[str] = Field(description="要读取的文件路径列表（相对空间根目录）")


class FileManageInput(BaseModel):
    action: str = Field(description="操作类型: list_tree, create_folder, rename_folder")
    space_id: str = Field(description="空间public_id")
    folder_name: Optional[str] = Field(None, description="文件夹名称（创建/重命名时使用）")
    parent_id: Optional[int] = Field(None, description="父文件夹ID")
    folder_public_id: Optional[str] = Field(None, description="目标文件夹public_id（重命名时使用）")


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


def _search_files_fn(space_path: Path, interpreted_path: str, pattern: str) -> list[dict[str, Any]]:
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


def _format_search_results(file_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format search results (metadata only, no content)."""
    formatted = []
    for idx, result in enumerate(file_results, 1):
        formatted.append({
            "index": idx,
            "name": result.get("name", ""),
            "path": result.get("path", ""),
            "size": result.get("size", 0),
            "modified": result.get("modified", 0),
        })
    return formatted


def _read_file_contents(space_path: Path, file_paths: list[str]) -> list[dict[str, Any]]:
    """Read content of specified files (max 20)."""
    results: list[dict[str, Any]] = []
    for file_path_str in file_paths[:20]:
        try:
            if not _is_safe_path(str(space_path), file_path_str):
                results.append({
                    "path": file_path_str,
                    "content": "[Security: Path validation failed]",
                    "error": "Path traversal detected",
                })
                continue

            file_path = space_path / file_path_str
            if not file_path.exists():
                results.append({
                    "path": file_path_str,
                    "content": "",
                    "error": "File not found",
                })
                continue

            suffix = file_path.suffix.lower()
            if suffix == ".md":
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".txt":
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".json":
                content = json.dumps(
                    json.loads(file_path.read_text(encoding="utf-8", errors="ignore")),
                    ensure_ascii=False, indent=2,
                )
            elif suffix in (".yaml", ".yml"):
                import yaml
                content = yaml.dump(
                    yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")),
                    allow_unicode=True,
                )
            else:
                raw = file_path.read_bytes()
                content = (
                    raw[:2000].decode("utf-8", errors="ignore") + "..."
                    if len(raw) > 2000
                    else raw.decode("utf-8", errors="ignore")
                )

            preview = content[:500] + "..." if len(content) > 500 else content
            results.append({
                "path": file_path_str,
                "name": file_path.name,
                "content": content,
                "preview": preview,
                "size": file_path.stat().st_size,
            })
        except Exception as e:
            logger.warning(f"Failed to read {file_path_str}: {e}")
            results.append({
                "path": file_path_str,
                "content": f"[Error reading file: {e}]",
                "error": str(e),
            })
    return results


async def _search_files(query: str, space_path: str) -> dict[str, Any]:
    """Search files by query, return metadata only."""
    if not query or not query.strip():
        return {"success": False, "query": query, "files": [], "error": "Empty query"}

    resolved_space = Path(space_path).resolve() if space_path else None
    if not resolved_space:
        return {"success": False, "query": query, "files": [], "error": "Space path not configured"}

    try:
        interpreted_path, interpreted_pattern = await _parse_query(query.strip())

        if not _is_safe_path(str(resolved_space), interpreted_path):
            return {
                "success": False, "query": query,
                "interpreted_path": interpreted_path, "interpreted_pattern": interpreted_pattern,
                "files": [], "error": "Path traversal detected. Access denied.",
            }

        full_path = resolved_space / interpreted_path
        if not full_path.exists():
            return {
                "success": False, "query": query,
                "interpreted_path": interpreted_path, "interpreted_pattern": interpreted_pattern,
                "files": [], "error": f"Path does not exist: {interpreted_path}",
            }

        file_results = _search_files_fn(resolved_space, interpreted_path, interpreted_pattern)
        formatted = _format_search_results(file_results)

        return {
            "success": True, "query": query,
            "interpreted_path": interpreted_path, "interpreted_pattern": interpreted_pattern,
            "files": formatted, "error": None,
        }
    except Exception as e:
        logger.exception(f"File search failed: {e}")
        return {"success": False, "query": query, "files": [], "error": str(e)}


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user
    space_path = registry.space_path

    async def file_search(query: str) -> Dict[str, Any]:
        """Search for files matching the natural language query. Returns file metadata only (no content)."""
        return await _search_files(query=query, space_path=space_path or "/tmp/uploads")

    async def file_read(file_paths: List[str]) -> Dict[str, Any]:
        """Read contents of specified file paths."""
        resolved_space = Path(space_path or "/tmp/uploads").resolve()
        if not resolved_space:
            return {"success": False, "files": [], "error": "Space path not configured"}

        try:
            results = _read_file_contents(resolved_space, file_paths)
            return {"success": True, "files": results, "error": None}
        except Exception as e:
            logger.exception(f"File read failed: {e}")
            return {"success": False, "files": [], "error": str(e)}

    async def file_manage(
        action: str,
        space_id: str,
        folder_name: Optional[str] = None,
        parent_id: Optional[int] = None,
        folder_public_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.file.file_service import SpaceFileService
        service = SpaceFileService(db)

        try:
            if action == "list_tree":
                result = await service.get_space_tree(space_id, user)
                return {"success": True, "action": action, "tree": result}
            elif action == "create_folder":
                if not folder_name:
                    return {"success": False, "error": "folder_name is required"}
                result = await service.create_folder(space_id, parent_id, folder_name, user)
                return {"success": True, "action": action, "folder": {"id": result.id, "public_id": result.public_id, "name": result.name}}
            elif action == "rename_folder":
                if not folder_public_id or not folder_name:
                    return {"success": False, "error": "folder_public_id and folder_name are required"}
                result = await service.rename_folder(space_id, folder_public_id, folder_name, user)
                return {"success": True, "action": action, "result": result}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception(f"file_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="file_search",
            func=file_search,
            description="根据自然语言查询搜索空间内的文件，返回文件元数据列表（不含内容）。如需读取内容，请调用 file_read。",
            args_schema=FileSearchInput,
            coroutine=file_search,
        ),
        StructuredTool.from_function(
            name="file_read",
            func=file_read,
            description="读取指定文件路径列表的内容，支持 .md/.txt/.json/.yaml/.yml 等格式。",
            args_schema=FileReadInput,
            coroutine=file_read,
        ),
        StructuredTool.from_function(
            name="file_manage",
            func=file_manage,
            description="管理空间文件和文件夹（列出目录树、创建文件夹、重命名文件夹）",
            args_schema=FileManageInput,
            coroutine=file_manage,
        ),
    ]
