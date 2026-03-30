from __future__ import annotations

import re
from typing import TypedDict


MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")


class MarkdownSection(TypedDict):
    section_path: str | None
    content: str
    start_offset: int
    end_offset: int


class TextChunk(TypedDict):
    content: str
    start_offset: int
    end_offset: int


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return normalized.lstrip("\ufeff")


def normalize_markdown(text: str) -> str:
    normalized = normalize_text(text)
    lines = [line.rstrip() for line in normalized.split("\n")]
    compact = "\n".join(lines)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


def looks_like_markdown(text: str) -> bool:
    sample = normalize_text(text)[:4000]
    if not sample.strip():
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
    hit_count = sum(1 for pattern in patterns if re.search(pattern, sample))
    return hit_count >= 1


def section_path_from_metadata(metadata: dict | None) -> str | None:
    if not metadata:
        return None

    if metadata.get("section_path"):
        value = str(metadata["section_path"]).strip()
        return value or None

    ordered_keys = [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "Header 1",
        "Header 2",
        "Header 3",
        "Header 4",
        "Header 5",
        "Header 6",
    ]
    parts: list[str] = []
    for key in ordered_keys:
        value = metadata.get(key)
        if value is None:
            continue
        title = str(value).strip()
        if title:
            parts.append(title)

    if not parts:
        return None
    return " / ".join(parts)


def split_markdown_sections(markdown_text: str) -> list[MarkdownSection]:
    text = normalize_text(markdown_text)
    if not text.strip():
        return []

    lines = text.splitlines(keepends=True)
    sections: list[MarkdownSection] = []
    heading_stack = [""] * 6

    current_path: str | None = None
    current_lines: list[str] = []
    current_start = 0
    offset = 0

    def flush(end_offset: int):
        nonlocal current_lines, current_start
        if not current_lines:
            current_start = end_offset
            return

        raw = "".join(current_lines)
        stripped = raw.strip()
        if not stripped:
            current_lines = []
            current_start = end_offset
            return

        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start_offset = current_start + leading
        section_end = end_offset - trailing

        if section_end > start_offset:
            sections.append(
                {
                    "section_path": current_path,
                    "content": text[start_offset:section_end],
                    "start_offset": start_offset,
                    "end_offset": section_end,
                }
            )

        current_lines = []
        current_start = end_offset

    for line in lines:
        line_start = offset
        line_end = line_start + len(line)
        heading_match = _HEADING_RE.match(line.rstrip("\n"))

        if heading_match:
            flush(line_start)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            heading_stack[level - 1] = title
            for idx in range(level, 6):
                heading_stack[idx] = ""

            current_path = build_section_path(heading_stack)
            current_lines = [line]
            current_start = line_start
        else:
            if not current_lines:
                current_start = line_start
            current_lines.append(line)

        offset = line_end

    flush(offset)

    if sections:
        return sections

    compact = text.strip()
    if not compact:
        return []

    leading = len(text) - len(text.lstrip())
    trailing = len(text) - len(text.rstrip())
    start_offset = leading
    end_offset = len(text) - trailing
    return [
        {
            "section_path": None,
            "content": text[start_offset:end_offset],
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
    ]


def split_text_with_overlap(text: str, chunk_size: int = 1200, chunk_overlap: int = 120) -> list[TextChunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 5)

    normalized = normalize_text(text)
    if not normalized.strip():
        return []

    chunks: list[TextChunk] = []
    total = len(normalized)
    cursor = 0

    while cursor < total:
        upper = min(total, cursor + chunk_size)
        split_end = _choose_split_point(normalized, cursor, upper)
        if split_end <= cursor:
            split_end = upper

        raw = normalized[cursor:split_end]
        if raw.strip():
            leading = len(raw) - len(raw.lstrip())
            trailing = len(raw) - len(raw.rstrip())
            start = cursor + leading
            end = split_end - trailing
            if end > start:
                chunks.append(
                    {
                        "content": normalized[start:end],
                        "start_offset": start,
                        "end_offset": end,
                    }
                )

        if split_end >= total:
            break

        next_cursor = split_end - chunk_overlap
        if next_cursor <= cursor:
            next_cursor = split_end
        cursor = next_cursor

    return chunks


def estimate_token_count(text: str) -> int:
    normalized = normalize_text(text)
    if not normalized.strip():
        return 0
    tokens = re.findall(r"\w+|[^\w\s]", normalized, flags=re.UNICODE)
    return len(tokens)


def build_section_path(headings: list[str]) -> str | None:
    parts = [item.strip() for item in headings if item and item.strip()]
    if not parts:
        return None
    return " / ".join(parts)


def _choose_split_point(text: str, start: int, upper: int) -> int:
    if upper >= len(text):
        return upper

    search_start = start + max(1, int((upper - start) * 0.55))
    for token in ("\n\n", "\n", " "):
        idx = text.rfind(token, search_start, upper)
        if idx >= 0:
            return idx + len(token)
    return upper
