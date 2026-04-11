from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.ai.markdown_utils import normalize_markdown

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """A lightweight table representation for Markdown rendering."""

    caption: str = ""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)

    def to_markdown(self) -> str:
        if not self.headers and not self.rows:
            return ""

        column_count = max(
            len(self.headers),
            max((len(row) for row in self.rows), default=0),
        )
        if column_count == 0:
            return ""

        headers = self.headers or [f"Col{i + 1}" for i in range(column_count)]
        lines = []
        if self.caption:
            lines.append(f"**{self.caption}**")
            lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in self.rows:
            padded = row + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(padded) + " |")
        return "\n".join(lines)


@dataclass
class ProcessedPdfDocument:
    """Processed PDF result for the ingestion pipeline."""

    raw_markdown: str
    cleaned_markdown: str
    title: Optional[str] = None
    removed_noise_lines: int = 0
    fixed_hyphenations: int = 0
    tables_extracted: int = 0


class PdfTableExtractor:
    """Table extraction with pdfplumber-first and text fallback."""

    _caption_pattern = re.compile(r"^(Table|TABLE)\s*(\d+)[\.:\s]*(.+)?$", re.IGNORECASE)

    def extract(self, pdf_path: Path, markdown_text: str) -> List[ExtractedTable]:
        tables = self._extract_with_pdfplumber(pdf_path)
        if tables:
            return tables
        return self._extract_from_text(markdown_text)

    def _extract_with_pdfplumber(self, pdf_path: Path) -> List[ExtractedTable]:
        try:
            import pdfplumber
        except ImportError:
            return []

        extracted: List[ExtractedTable] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_tables = page.extract_tables() or []
                    if not page_tables:
                        continue

                    page_text = page.extract_text() or ""
                    captions = self._find_captions(page_text.splitlines())

                    for index, table_data in enumerate(page_tables):
                        if not table_data:
                            continue

                        header_row = table_data[0] if table_data else []
                        headers = [str(cell or "").strip() for cell in header_row]
                        rows = [
                            [str(cell or "").strip() for cell in row]
                            for row in table_data[1:]
                        ]

                        if not any(headers) and rows:
                            headers = []
                            rows = [
                                [str(cell or "").strip() for cell in row]
                                for row in table_data
                            ]

                        caption = captions[index] if index < len(captions) else ""
                        extracted.append(
                            ExtractedTable(caption=caption, headers=headers, rows=rows)
                        )
        except Exception as exc:
            logger.warning("pdfplumber table extraction failed for %s: %s", pdf_path.name, exc)
            return []

        return [table for table in extracted if table.to_markdown()]

    def _extract_from_text(self, markdown_text: str) -> List[ExtractedTable]:
        lines = markdown_text.splitlines()
        tables: List[ExtractedTable] = []
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            caption_match = self._caption_pattern.match(line)
            if not caption_match:
                index += 1
                continue

            caption_num = caption_match.group(2)
            caption_body = (caption_match.group(3) or "").strip()
            caption = f"Table {caption_num}: {caption_body}" if caption_body else f"Table {caption_num}"

            candidate_rows: List[List[str]] = []
            index += 1
            while index < len(lines):
                current = lines[index].rstrip()
                stripped = current.strip()
                if not stripped:
                    break
                if re.match(r"^(Figure|FIGURE|Algorithm|#|\d+(\.\d+)*\s+)", stripped):
                    break
                parts = [part.strip() for part in re.split(r"\s{2,}", current) if part.strip()]
                if len(parts) >= 2:
                    candidate_rows.append(parts)
                elif candidate_rows:
                    break
                index += 1

            if candidate_rows:
                headers = candidate_rows[0]
                rows = candidate_rows[1:] if len(candidate_rows) > 1 else []
                tables.append(ExtractedTable(caption=caption, headers=headers, rows=rows))
            index += 1

        return tables

    def _find_captions(self, lines: List[str]) -> List[str]:
        captions: List[str] = []
        for line in lines:
            match = self._caption_pattern.match(line.strip())
            if match:
                body = (match.group(3) or "").strip()
                captions.append(f"Table {match.group(2)}: {body}" if body else f"Table {match.group(2)}")
        return captions


class UnifiedPdfProcessor:
    """Single PDF processing pipeline for ingestion and offline tools."""

    _section_heading_pattern = re.compile(
        r"^(ABSTRACT|INTRODUCTION|CONCLUSION|RELATED WORK|EXPERIMENTS|RESULTS|REFERENCES|ACKNOWLEDGMENTS?)$",
        re.IGNORECASE,
    )

    def __init__(self, enable_tables: bool = True) -> None:
        self.enable_tables = enable_tables
        self.table_extractor = PdfTableExtractor() if enable_tables else None
        self.common_words = {
            "embedding",
            "knowledge",
            "graph",
            "entity",
            "relation",
            "representation",
            "learning",
            "information",
            "communication",
            "computation",
            "optimization",
            "regularization",
            "classification",
            "generalization",
            "reasoning",
            "inference",
            "evaluation",
        }

    def process(self, markdown_text: str, pdf_path: Path) -> ProcessedPdfDocument:
        cleaned_text, removed_noise_lines = self._clean_headers_footers(markdown_text)
        cleaned_text, fixed_hyphenations = self._fix_hyphenation(cleaned_text)

        tables = []
        if self.table_extractor is not None:
            tables = self.table_extractor.extract(pdf_path, cleaned_text)

        cleaned_text = self._inject_tables(cleaned_text, tables)
        title, cleaned_text = self._rewrite_structure(cleaned_text)
        cleaned_text = normalize_markdown(cleaned_text)

        return ProcessedPdfDocument(
            raw_markdown=markdown_text,
            cleaned_markdown=cleaned_text,
            title=title,
            removed_noise_lines=removed_noise_lines,
            fixed_hyphenations=fixed_hyphenations,
            tables_extracted=len(tables),
        )

    def _clean_headers_footers(self, text: str) -> tuple[str, int]:
        lines = text.splitlines()
        cleaned_lines: List[str] = []
        removed = 0
        garbage_patterns = [
            re.compile(r"^\d+$"),
            re.compile(r"^ar[Xx]iv:\d"),
            re.compile(r"^(ICLR|ICML|NeurIPS|ACL|EMNLP|AAAI|IJCAI)"),
            re.compile(r"^Published as", re.IGNORECASE),
            re.compile(r"^Page \d+", re.IGNORECASE),
            re.compile(r"^\d+\s+of\s+\d+$", re.IGNORECASE),
            re.compile(r"^[\[(]?\d+[\])]?$"),
            re.compile(r"^[a-zA-Z]$"),
        ]

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue

            is_noise = any(pattern.match(stripped) for pattern in garbage_patterns)
            if not is_noise and len(stripped) <= 3 and (index < 10 or index > len(lines) - 10):
                is_noise = True

            if is_noise:
                removed += 1
            else:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines), removed

    def _fix_hyphenation(self, text: str) -> tuple[str, int]:
        fixed = 0
        hyphen_pattern = re.compile(r"(\w+)-\n(\w+)")

        def merge(match: re.Match[str]) -> str:
            nonlocal fixed
            left, right = match.group(1), match.group(2)
            merged = left + right
            if merged.lower() in self.common_words or (4 < len(merged) < 24 and merged.isalpha()):
                fixed += 1
                return merged + "\n"
            return match.group(0)

        text = hyphen_pattern.sub(merge, text)
        return text, fixed

    def _inject_tables(self, text: str, tables: List[ExtractedTable]) -> str:
        if not tables:
            return text

        lines = text.splitlines()
        rendered: List[str] = []
        table_index = 0
        index = 0

        while index < len(lines):
            stripped = lines[index].strip()
            if table_index < len(tables) and re.match(r"^(Table|TABLE)\s*\d+", stripped):
                rendered.append(lines[index])
                rendered.append("")
                rendered.append(tables[table_index].to_markdown())
                rendered.append("")
                table_index += 1
                index += 1
                while index < len(lines):
                    next_line = lines[index].strip()
                    if not next_line:
                        break
                    if re.match(r"^(Table|TABLE|Figure|FIGURE|Algorithm|#|\d+(\.\d+)*\s+)", next_line):
                        break
                    index += 1
                continue

            rendered.append(lines[index])
            index += 1

        return "\n".join(rendered)

    def _rewrite_structure(self, text: str) -> tuple[Optional[str], str]:
        lines = text.splitlines()
        title_index, title = self._find_title(lines)
        rewritten: List[str] = []

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                rewritten.append("")
                continue

            if title_index is not None and index == title_index:
                rewritten.append(f"# {title}")
                rewritten.append("")
                continue

            heading = self._as_markdown_heading(stripped)
            if heading:
                rewritten.append(heading)
                rewritten.append("")
            else:
                rewritten.append(line)

        return title, "\n".join(rewritten)

    def _find_title(self, lines: List[str]) -> tuple[Optional[int], Optional[str]]:
        for index, line in enumerate(lines[:20]):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if self._as_markdown_heading(stripped):
                continue
            if re.match(r"^(Table|TABLE|Figure|FIGURE|Algorithm)", stripped):
                continue
            if 20 < len(stripped) < 180 and stripped[0].isupper() and not stripped.isupper():
                return index, stripped
        return None, None

    def _as_markdown_heading(self, line: str) -> Optional[str]:
        if line.startswith("#"):
            return line
        if self._section_heading_pattern.match(line):
            return f"## {line.title()}"

        section_match = re.match(r"^(\d+)\.\s+(.+)$", line)
        if section_match:
            return f"## {section_match.group(2).strip()}"

        subsection_match = re.match(r"^(\d+\.\d+)\s+(.+)$", line)
        if subsection_match:
            return f"### {subsection_match.group(2).strip()}"

        subsubsection_match = re.match(r"^(\d+\.\d+\.\d+)\s+(.+)$", line)
        if subsubsection_match:
            return f"#### {subsubsection_match.group(2).strip()}"

        return None


def convert_pdf_to_markdown(file_path: Path, enable_tables: bool = True) -> Optional[str]:
    """Unified PDF to Markdown conversion used by the ingestion pipeline."""

    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.warning("markitdown not installed, PDF conversion unavailable")
        return None

    try:
        converter = MarkItDown()
        result = converter.convert(str(file_path))
        markdown_text = (result.text_content or "").strip() if result else ""
        if not markdown_text:
            return None

        processor = UnifiedPdfProcessor(enable_tables=enable_tables)
        processed = processor.process(markdown_text, file_path)
        logger.info(
            "Unified PDF pipeline completed for %s: removed_noise=%s, fixed_hyphenations=%s, tables=%s",
            file_path.name,
            processed.removed_noise_lines,
            processed.fixed_hyphenations,
            processed.tables_extracted,
        )
        return processed.cleaned_markdown
    except Exception as exc:
        logger.warning("Unified PDF pipeline failed for %s: %s", file_path.name, exc)
        return None