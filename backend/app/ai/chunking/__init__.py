"""
Document Chunking Strategies

Three strategies adapted from production experience:
1. atomic: For short notes / single fact texts
2. section_pack: For structured documents (Markdown, web content)
3. fixed_size_overlap: For transcripts / OCR fragment texts

Key parameters:
- min_token: 500 - threshold for atomic mode
- max_token: 4000 - threshold for composite mode
- max_chars: 2000 - target chunk size
- min_chars: 400 - minimum chunk size
- overlap_chars: 100 - overlap between chunks
"""
from app.ai.chunking.strategies import (
    ChunkingStrategy,
    AtomicStrategy,
    SectionPackStrategy,
    FixedSizeOverlapStrategy,
    detect_content_type,
    estimate_tokens,
    chunk_text,
)

__all__ = [
    "ChunkingStrategy",
    "AtomicStrategy",
    "SectionPackStrategy",
    "FixedSizeOverlapStrategy",
    "detect_content_type",
    "estimate_tokens",
    "chunk_text",
]
