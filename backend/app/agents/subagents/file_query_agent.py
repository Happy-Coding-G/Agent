"""
FileQueryAgent - LangGraph-based file query agent with path security validation.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from app.agents.core import FileQueryState
from app.core.config import settings
from app.core.errors import ServiceError

logger = logging.getLogger(__name__)

# Allowed file extensions for security
ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".doc", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"}


def _is_safe_path(base_path: str, target_path: str) -> bool:
    """Validate that target_path is within base_path to prevent path traversal."""
    try:
        base = Path(base_path).resolve()
        target = (base / target_path).resolve()
        return target.is_relative_to(base)
    except Exception:
        return False


def _parse_glob_pattern(pattern: str) -> tuple[str, str]:
    """Parse glob pattern into directory and file pattern."""
    pattern = pattern.strip()
    if "**/" in pattern:
        parts = pattern.split("**/", 1)
        return parts[0] if parts[0] else "./", "**/" + parts[1]
    elif "/" in pattern:
        parts = pattern.rsplit("/", 1)
        return parts[0], parts[1]
    else:
        return "./", pattern


class FileQueryAgent:
    """Agent for querying files within user space with security validation."""

    def __init__(self, space_path: str):
        """
        Initialize FileQueryAgent.

        Args:
            space_path: The root path for the user's space (used for security validation)
        """
        self.space_path = Path(space_path).resolve() if space_path else None
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for file query."""
        builder = StateGraph(FileQueryState)

        builder.add_node("parse_query", RunnableLambda(self._parse_query_node))
        builder.add_node("validate_path", RunnableLambda(self._validate_path_node))
        builder.add_node("search_files", RunnableLambda(self._search_files_node))
        builder.add_node("read_content", RunnableLambda(self._read_content_node))
        builder.add_node("format_results", RunnableLambda(self._format_results_node))

        builder.add_edge("parse_query", "validate_path")
        builder.add_edge("validate_path", "search_files")
        builder.add_edge("search_files", "read_content")
        builder.add_edge("read_content", "format_results")
        builder.add_edge("format_results", END)

        builder.set_entry_point("parse_query")
        return builder.compile()

    async def _parse_query_node(self, state: FileQueryState) -> FileQueryState:
        """Parse the user query to extract path and file pattern."""
        query = state.get("query", "").strip()
        if not query:
            state["error"] = "Empty query"
            return state

        # Use LLM to parse the query
        try:
            from app.services.base import get_llm_client

            llm = get_llm_client(temperature=0)
            prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个本地文件查询助手。根据用户的自然语言查询，解析出要查询的路径和文件模式。

输出格式（JSON）：
{{
    "path": "要查询的目录路径，如果用户没有指定则为空",
    "pattern": "文件匹配模式（如 *.md, **/*.txt, report*.json）
}}

只返回JSON，不要其他内容。"""),
                ("human", "{query}")
            ])
            chain = prompt | llm

            result = await chain.ainvoke({"query": query})
            content = result.content if hasattr(result, "content") else str(result)

            # Extract JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if json_match:
                import json
                parsed = json.loads(json_match.group())
                state["interpreted_path"] = parsed.get("path", "./")
                state["interpreted_pattern"] = parsed.get("pattern", "*")
            else:
                state["interpreted_path"] = "./"
                state["interpreted_pattern"] = "*"

        except Exception as e:
            logger.warning(f"LLM parsing failed, using fallback: {e}")
            # Fallback: try to extract path and pattern manually
            state["interpreted_path"], state["interpreted_pattern"] = self._fallback_parse(query)

        return state

    def _fallback_parse(self, query: str) -> tuple[str, str]:
        """Fallback query parsing using simple pattern matching."""
        # Common patterns
        md_pattern = re.compile(r'\*?\.?md|markdown|文档')
        txt_pattern = re.compile(r'\.txt|text|文本')
        glob_pattern = re.compile(r'\*+\.[a-zA-Z0-9]+|\*+')

        path = "./"
        pattern = "*"

        # Check for glob patterns
        glob_match = glob_pattern.search(query)
        if glob_match:
            pattern = glob_match.group()
            if "**" not in pattern and "." not in pattern:
                pattern = f"*.{pattern.lstrip('*')}"

        # Check for file extensions
        if md_pattern.search(query.lower()):
            pattern = "*.md"
        elif txt_pattern.search(query.lower()):
            pattern = "*.txt"

        return path, pattern

    async def _validate_path_node(self, state: FileQueryState) -> FileQueryState:
        """Validate that the interpreted path is safe and within space boundaries."""
        if not self.space_path:
            state["error"] = "Space path not configured"
            return state

        interpreted_path = state.get("interpreted_path", "./")

        # Security check: prevent path traversal
        if not _is_safe_path(str(self.space_path), interpreted_path):
            state["error"] = "Path traversal detected. Access denied."
            return state

        # Validate path exists
        full_path = self.space_path / interpreted_path
        if not full_path.exists():
            state["error"] = f"Path does not exist: {interpreted_path}"
            return state

        return state

    async def _search_files_node(self, state: FileQueryState) -> FileQueryState:
        """Search for files matching the pattern within the validated path."""
        if state.get("error"):
            return state

        interpreted_path = state.get("interpreted_path", "./")
        pattern = state.get("interpreted_pattern", "*")

        full_path = self.space_path / interpreted_path
        results: list[dict[str, Any]] = []

        try:
            if "**" in pattern:
                # Recursive glob
                for match in full_path.rglob(pattern.replace("**/", "")):
                    if match.is_file():
                        rel_path = match.relative_to(self.space_path)
                        results.append({
                            "name": match.name,
                            "path": str(rel_path),
                            "size": match.stat().st_size,
                            "modified": match.stat().st_mtime
                        })
            else:
                # Simple glob
                for match in full_path.glob(pattern):
                    if match.is_file():
                        rel_path = match.relative_to(self.space_path)
                        results.append({
                            "name": match.name,
                            "path": str(rel_path),
                            "size": match.stat().st_size,
                            "modified": match.stat().st_mtime
                        })

            # Filter by allowed extensions
            results = [
                r for r in results
                if Path(r["name"]).suffix.lower() in ALLOWED_EXTENSIONS
            ]

        except Exception as e:
            logger.error(f"Search error: {e}")
            state["error"] = f"Search failed: {str(e)}"
            return state

        state["file_results"] = results
        return state

    async def _read_content_node(self, state: FileQueryState) -> FileQueryState:
        """Read the content of matched files."""
        if state.get("error"):
            return state

        file_results = state.get("file_results", [])

        for file_result in file_results[:10]:  # Limit to 10 files
            try:
                file_path = self.space_path / file_result["path"]

                if not _is_safe_path(str(self.space_path), str(file_result["path"])):
                    file_result["content"] = "[Security: Path validation failed]"
                    continue

                suffix = file_path.suffix.lower()
                if suffix == ".md":
                    file_result["content"] = file_path.read_text(encoding="utf-8", errors="ignore")
                elif suffix == ".txt":
                    file_result["content"] = file_path.read_text(encoding="utf-8", errors="ignore")
                elif suffix == ".json":
                    import json
                    file_result["content"] = json.dumps(json.loads(file_path.read_text(encoding="utf-8", errors="ignore")), ensure_ascii=False, indent=2)
                elif suffix == ".yaml" or suffix == ".yml":
                    import yaml
                    file_result["content"] = yaml.dump(yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")), allow_unicode=True)
                else:
                    # For other files, just show a preview
                    content = file_path.read_bytes()
                    file_result["content"] = content[:1000].decode("utf-8", errors="ignore") + "..." if len(content) > 1000 else content.decode("utf-8", errors="ignore")

                file_result["content_preview"] = file_result["content"][:500] + "..." if len(file_result.get("content", "")) > 500 else file_result.get("content", "")

            except Exception as e:
                logger.warning(f"Failed to read {file_result.get('path')}: {e}")
                file_result["content"] = f"[Error reading file: {str(e)}]"

        return state

    async def _format_results_node(self, state: FileQueryState) -> FileQueryState:
        """Format the final results for display."""
        file_results = state.get("file_results", [])

        if not file_results:
            state["file_results"] = []
            return state

        # Format each result
        formatted = []
        for idx, result in enumerate(file_results, 1):
            formatted.append({
                "index": idx,
                "name": result.get("name", ""),
                "path": result.get("path", ""),
                "size": result.get("size", 0),
                "modified": result.get("modified", 0),
                "preview": result.get("content_preview", ""),
                "has_content": "content" in result and not result["content"].startswith("[")
            })

        state["file_results"] = formatted
        return state

    async def run(self, query: str) -> dict[str, Any]:
        """
        Run the file query agent.

        Args:
            query: User's natural language query

        Returns:
            Dict containing query results
        """
        initial_state: FileQueryState = {
            "query": query,
            "interpreted_path": None,
            "interpreted_pattern": None,
            "file_results": [],
            "error": None
        }

        try:
            result = await self.graph.ainvoke(initial_state)
            return {
                "success": result.get("error") is None,
                "query": query,
                "interpreted_path": result.get("interpreted_path"),
                "interpreted_pattern": result.get("interpreted_pattern"),
                "files": result.get("file_results", []),
                "error": result.get("error")
            }
        except Exception as e:
            logger.exception(f"FileQueryAgent error: {e}")
            return {
                "success": False,
                "query": query,
                "files": [],
                "error": str(e)
            }
