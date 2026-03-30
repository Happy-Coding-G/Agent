"""
Document Chunking Strategies Implementation

Three strategies:
1. atomic: Short notes / single fact - no splitting
2. section_pack: Structured docs - pack by headings and paragraphs
3. fixed_size_overlap: Transcripts / OCR - window-based with overlap
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


# Default parameters (from production experience)
DEFAULT_MIN_TOKEN = 500
DEFAULT_MAX_TOKEN = 4000
DEFAULT_MAX_CHARS = 2000
DEFAULT_MIN_CHARS = 400
DEFAULT_OVERLAP_CHARS = 100


@dataclass
class Chunk:
    """Represents a text chunk with metadata."""
    content: str
    index: int
    start_char: int
    end_char: int
    source_type: str  # "atomic", "section_pack", "fixed_size_overlap"
    metadata: dict


@dataclass
class ChunkingConfig:
    """Configuration for chunking strategies."""
    min_token: int = DEFAULT_MIN_TOKEN
    max_token: int = DEFAULT_MAX_TOKEN
    max_chars: int = DEFAULT_MAX_CHARS
    min_chars: int = DEFAULT_MIN_CHARS
    overlap_chars: int = DEFAULT_OVERLAP_CHARS

    # Section pack specific
    heading_block_max_chars: int = None  # 1.5 * max_chars
    heading_block_soft_step: int = None  # 0.8 * max_chars
    chunk_hard_threshold: int = None  # 1.3 * max_chars

    def __post_init__(self):
        if self.heading_block_max_chars is None:
            self.heading_block_max_chars = int(1.5 * self.max_chars)
        if self.heading_block_soft_step is None:
            self.heading_block_soft_step = int(0.8 * self.max_chars)
        if self.chunk_hard_threshold is None:
            self.chunk_hard_threshold = int(1.3 * self.max_chars)


class ChunkingStrategy(ABC):
    """Base class for chunking strategies."""

    def __init__(self, config: Optional[ChunkingConfig] = None):
        self.config = config or ChunkingConfig()

    @abstractmethod
    def chunk(self, text: str, source: str = "unknown") -> List[Chunk]:
        """Split text into chunks."""
        pass


class AtomicStrategy(ChunkingStrategy):
    """
    For short notes / single fact texts.

    Policy: Don't split, treat the whole text as one chunk.

    Use when:
    - User short messages
    - Single paragraph memos
    - Very short web summaries
    """

    def chunk(self, text: str, source: str = "unknown") -> List[Chunk]:
        if not text or not text.strip():
            return []

        return [Chunk(
            content=text.strip(),
            index=0,
            start_char=0,
            end_char=len(text),
            source_type="atomic",
            metadata={"strategy": "atomic"}
        )]


class SectionPackStrategy(ChunkingStrategy):
    """
    For structured documents (Markdown, web content, PDF reports).

    Policy:
    1. Split by headings and paragraphs into natural blocks
    2. Pack consecutive blocks into chunks
    3. Split oversized chunks; merge undersized ones
    4. Add overlap between adjacent chunks
    """

    def chunk(self, text: str, source: str = "unknown") -> List[Chunk]:
        if not text or not text.strip():
            return []

        text = text.strip()

        # Split into blocks (headings, paragraphs)
        blocks = self._split_into_blocks(text)

        if not blocks:
            return [Chunk(
                content=text,
                index=0,
                start_char=0,
                end_char=len(text),
                source_type="section_pack",
                metadata={"strategy": "section_pack", "block_count": 1}
            )]

        # Pack blocks into chunks
        chunks = self._pack_blocks(blocks, text)

        return chunks

    def _split_into_blocks(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Split text into natural blocks (headings, paragraphs).
        Returns list of (block_text, start_char, end_char).
        """
        blocks = []
        lines = text.split("\n")

        current_block_lines = []
        current_block_start = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Check if this is a heading (Markdown syntax)
            is_heading = bool(re.match(r"^#{1,6}\s+", stripped))

            if is_heading:
                # Save current block
                if current_block_lines:
                    block_text = "\n".join(current_block_lines)
                    if block_text.strip():
                        blocks.append((block_text.strip(), current_block_start, 0))  # end will be calculated
                # Start new block for heading
                current_block_lines = [line]
                current_block_start = text.index(line)

        return blocks

    def _pack_blocks(self, blocks: List[Tuple[str, int, int]], original_text: str) -> List[Chunk]:
        """Pack blocks into chunks respecting size constraints."""
        chunks = []
        current_chunk_parts = []
        current_chunk_chars = 0
        chunk_index = 0
        chunk_start_char = 0

        def finish_chunk(parts: List[str], start: int) -> Optional[Chunk]:
            if not parts:
                return None
            content = "\n".join(parts)
            return Chunk(
                content=content,
                index=chunk_index,
                start_char=start,
                end_char=start + len(content),
                source_type="section_pack",
                metadata={"strategy": "section_pack", "part_count": len(parts)}
            )

        for block_text, block_start, _ in blocks:
            block_chars = len(block_text)

            # If single block exceeds max, pre-split it
            if block_chars > self.config.heading_block_max_chars:
                # Save current chunk first
                if current_chunk_parts:
                    chunk = finish_chunk(current_chunk_parts, chunk_start_char)
                    if chunk:
                        chunks.append(chunk)
                    chunk_index += 1
                    current_chunk_parts = []
                    current_chunk_chars = 0

                # Pre-split the large block
                sub_chunks = self._split_large_block(block_text)
                for sub_chunk in sub_chunks:
                    chunks.append(Chunk(
                        content=sub_chunk,
                        index=chunk_index,
                        start_char=0,  # Simplified
                        end_char=len(sub_chunk),
                        source_type="section_pack",
                        metadata={"strategy": "section_pack", "split": True}
                    ))
                    chunk_index += 1
                continue

            # Check if adding this block would exceed max_chars
            if current_chunk_chars + block_chars > self.config.max_chars and current_chunk_parts:
                # Finish current chunk
                chunk = finish_chunk(current_chunk_parts, chunk_start_char)
                if chunk:
                    chunks.append(chunk)
                chunk_index += 1

                # Start new chunk with overlap
                overlap_text = "\n".join(current_chunk_parts[-1:]) if len(current_chunk_parts) > 0 else ""
                if len(overlap_text) > self.config.overlap_chars:
                    overlap_text = overlap_text[-self.config.overlap_chars:]

                current_chunk_parts = [overlap_text, block_text] if overlap_text else [block_text]
                current_chunk_chars = len(overlap_text) + block_chars if overlap_text else block_chars
                chunk_start_char = block_start - len(overlap_text)
            else:
                # Add to current chunk
                if not current_chunk_parts:
                    chunk_start_char = block_start
                current_chunk_parts.append(block_text)
                current_chunk_chars += block_chars

        # Handle remaining content
        if current_chunk_parts:
            chunk = finish_chunk(current_chunk_parts, chunk_start_char)
            if chunk:
                chunks.append(chunk)

        # Merge undersized chunks
        chunks = self._merge_undersized_chunks(chunks)

        # Re-index
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _split_large_block(self, text: str) -> List[str]:
        """Split a large block into smaller pieces."""
        # Soft step splitting
        step = self.config.heading_block_soft_step
        pieces = []

        for i in range(0, len(text), step):
            piece = text[i:i + step]
            # Try to split at sentence boundary
            if len(piece) == step and i + step < len(text):
                # Find last sentence end
                last_period = piece.rfind("。")
                last_newline = piece.rfind("\n")
                split_point = max(last_period, last_newline)
                if split_point > step // 2:
                    pieces.append(piece[:split_point + 1])
                    pieces.append(piece[split_point + 1:])
                else:
                    pieces.append(piece)
            else:
                pieces.append(piece)

        return pieces

    def _merge_undersized_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """Merge chunks that are too small."""
        if not chunks:
            return []

        merged = [chunks[0]]

        for chunk in chunks[1:]:
            if len(merged[-1].content) < self.config.min_chars:
                # Merge with previous
                merged[-1] = Chunk(
                    content=merged[-1].content + "\n" + chunk.content,
                    index=merged[-1].index,
                    start_char=merged[-1].start_char,
                    end_char=chunk.end_char,
                    source_type=merged[-1].source_type,
                    metadata={**merged[-1].metadata, "merged": True}
                )
            else:
                merged.append(chunk)

        return merged


class FixedSizeOverlapStrategy(ChunkingStrategy):
    """
    For transcripts / OCR fragment texts.

    Policy:
    1. Split by non-empty lines into units
    2. Window-based packing in order
    3. Split oversized lines; merge undersized
    4. Add overlap between chunks
    """

    def chunk(self, text: str, source: str = "unknown") -> List[Chunk]:
        if not text or not text.strip():
            return []

        text = text.strip()

        # Split into units by non-empty lines
        units = self._split_into_units(text)

        if not units:
            return []

        # Window-based packing
        chunks = self._pack_with_window(units)

        # Re-index
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _split_into_units(self, text: str) -> List[Tuple[str, int]]:
        """Split text into units by non-empty lines."""
        units = []
        lines = text.split("\n")
        current_unit_lines = []
        current_pos = 0

        for line in lines:
            stripped = line.strip()
            if stripped:
                current_unit_lines.append(line)
            else:
                # Empty line - save current unit if any
                if current_unit_lines:
                    unit_text = "\n".join(current_unit_lines)
                    start = text.index(current_unit_lines[0])
                    units.append((unit_text, start))
                    current_unit_lines = []

        # Handle remaining
        if current_unit_lines:
            unit_text = "\n".join(current_unit_lines)
            start = text.index(current_unit_lines[0])
            units.append((unit_text, start))

        return units

    def _pack_with_window(self, units: List[Tuple[str, int]]) -> List[Chunk]:
        """Pack units into chunks using sliding window."""
        chunks = []
        i = 0
        chunk_index = 0

        while i < len(units):
            unit_text, unit_start = units[i]
            unit_len = len(unit_text)

            # Handle oversized single unit
            if unit_len > self.config.max_chars:
                # Split the unit
                sub_chunks = self._split_oversized_line(unit_text)
                for sub_chunk_text in sub_chunks:
                    chunks.append(Chunk(
                        content=sub_chunk_text,
                        index=chunk_index,
                        start_char=unit_start,
                        end_char=unit_start + len(sub_chunk_text),
                        source_type="fixed_size_overlap",
                        metadata={"strategy": "fixed_size_overlap", "unit_split": True}
                    ))
                    chunk_index += 1
                    unit_start += len(sub_chunk_text)
                i += 1
                continue

            # Build chunk with subsequent units
            chunk_texts = [unit_text]
            chunk_start = unit_start
            chunk_len = unit_len
            j = i + 1

            while j < len(units):
                next_text, next_start = units[j]
                next_len = len(next_text)

                if chunk_len + next_len + 1 <= self.config.max_chars:
                    chunk_texts.append(next_text)
                    chunk_len += next_len + 1  # +1 for newline
                    j += 1
                else:
                    break

            # Create chunk
            content = "\n".join(chunk_texts)

            # Add overlap if not at end
            overlap_text = ""
            if j < len(units):
                # Take last unit as overlap
                overlap_text = units[j - 1][0][-self.config.overlap_chars:] if j > i else ""

            chunk = Chunk(
                content=content + overlap_text if overlap_text else content,
                index=chunk_index,
                start_char=chunk_start,
                end_char=chunk_start + len(content),
                source_type="fixed_size_overlap",
                metadata={"strategy": "fixed_size_overlap", "unit_count": len(chunk_texts)}
            )
            chunks.append(chunk)
            chunk_index += 1

            # Move window forward with overlap consideration
            i = j - 1 if overlap_text else j

            # Merge undersized chunks
            if len(chunks) > 1 and len(chunks[-1].content) < self.config.min_chars:
                prev = chunks[-2]
                curr = chunks[-1]
                chunks = chunks[:-2]
                merged = Chunk(
                    content=prev.content + "\n" + curr.content,
                    index=prev.index,
                    start_char=prev.start_char,
                    end_char=curr.end_char,
                    source_type="fixed_size_overlap",
                    metadata={**prev.metadata, "merged": True, "from_undersized": True}
                )
                chunks.append(merged)

        return chunks

    def _split_oversized_line(self, text: str) -> List[str]:
        """Split an oversized line at sentence boundaries."""
        pieces = []
        for i in range(0, len(text), self.config.max_chars):
            piece = text[i:i + self.config.max_chars]
            # Try to split at sentence
            if i + self.config.max_chars < len(text):
                last_period = piece.rfind("。")
                last_comma = piece.rfind("，")
                split_point = max(last_period, last_comma)
                if split_point > self.config.max_chars // 2:
                    pieces.append(piece[:split_point + 1])
                    pieces.append(piece[split_point + 1:])
                else:
                    pieces.append(piece)
            else:
                pieces.append(piece)
        return pieces


def estimate_tokens(text: str) -> int:
    """
    Rough token estimation.
    For Chinese, ~1.5 chars per token; for English, ~4 chars per token.
    """
    if not text:
        return 0

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    other_chars = len(text) - chinese_chars - english_chars

    # Rough estimation: Chinese ~1.5 chars/token, English ~4 chars/token
    return int(chinese_chars / 1.5 + english_chars / 4 + other_chars / 2)


def detect_content_type(text: str, source_hint: str = "") -> str:
    """
    Detect content type for routing to appropriate chunking strategy.

    Returns:
    - "atomic": Short text, single fact
    - "composite + section_pack": Structured document
    - "composite + fixed_size_overlap": Transcript / fragment text
    """
    if not text:
        return "atomic"

    text_lower = text.lower()

    # Check source hint first
    source_hints = {
        "video": "fixed_size_overlap",
        "transcript": "fixed_size_overlap",
        "ocr": "fixed_size_overlap",
        "web": "section_pack",
        "file": "section_pack",
        "markdown": "section_pack",
    }

    for hint, strategy in source_hints.items():
        if hint in source_hint.lower():
            return f"composite + {strategy}"

    # Estimate tokens
    tokens = estimate_tokens(text)

    # Short text threshold
    if tokens < DEFAULT_MIN_TOKEN:
        return "atomic"

    # Count structural features
    lines = text.split("\n")
    nonempty_lines = [l for l in lines if l.strip()]
    heading_count = len([l for l in lines if re.match(r"^#{1,6}\s+", l.strip())])
    paragraph_count = len([l for l in lines if l.strip() and not re.match(r"^#", l.strip())])
    bullet_count = len([l for l in lines if re.match(r"^[\-\*\+]\s+|^\d+\.\s+", l.strip())])
    timestamp_count = len([l for l in lines if re.match(r"^\d{1,2}:\d{2}(:\d{2})?", l.strip())])

    # Detect transcript / OCR / fragment text
    if len(nonempty_lines) >= 6 and timestamp_count >= 2:
        return "composite + fixed_size_overlap"

    if len(nonempty_lines) >= 6 and bullet_count >= 6:
        return "composite + fixed_size_overlap"

    # Detect structured document
    if heading_count >= 2 or paragraph_count >= 4:
        return "composite + section_pack"

    # Long text without clear structure - default to fixed_size_overlap
    if tokens > DEFAULT_MAX_TOKEN:
        return "composite + fixed_size_overlap"

    return "atomic"


def chunk_text(
    text: str,
    source: str = "unknown",
    config: Optional[ChunkingConfig] = None,
    strategy_override: Optional[str] = None
) -> List[Chunk]:
    """
    Main entry point for chunking.

    Args:
        text: Input text
        source: Source identifier (e.g., "file", "web", "video")
        config: Chunking configuration
        strategy_override: Force a specific strategy

    Returns:
        List of Chunks
    """
    if not text or not text.strip():
        return []

    # Auto-detect or use override
    if strategy_override:
        content_type = strategy_override
    else:
        content_type = detect_content_type(text, source)

    # Route to appropriate strategy
    if content_type == "atomic":
        strategy = AtomicStrategy(config)
    elif "section_pack" in content_type:
        strategy = SectionPackStrategy(config)
    elif "fixed_size_overlap" in content_type:
        strategy = FixedSizeOverlapStrategy(config)
    else:
        # Default fallback
        strategy = AtomicStrategy(config)

    chunks = strategy.chunk(text, source)

    # Final pass: split oversized chunks
    if config is None:
        config = ChunkingConfig()

    final_chunks = []
    for chunk in chunks:
        if len(chunk.content) > config.chunk_hard_threshold:
            # Hard split
            pieces = []
            for i in range(0, len(chunk.content), config.max_chars):
                pieces.append(chunk.content[i:i + config.max_chars])
            for i, piece in enumerate(pieces):
                final_chunks.append(Chunk(
                    content=piece,
                    index=len(final_chunks),
                    start_char=chunk.start_char + i * config.max_chars,
                    end_char=chunk.start_char + (i + 1) * config.max_chars,
                    source_type=chunk.source_type,
                    metadata={**chunk.metadata, "hard_split": True}
                ))
        else:
            final_chunks.append(chunk)

    return final_chunks
