"""
LCEL 声明式 Ingest Pipeline
完全使用 LangChain Expression Language 重构
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    RunnableLambda,
    RunnableParallel,
    RunnableBranch,
    chain as runnable_chain,
)
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.embedding_client import embed_documents_with_fallback
from app.ai.markdown_utils import (
    MARKDOWN_SUFFIXES,
    estimate_token_count,
    looks_like_markdown,
    normalize_markdown,
    normalize_text,
)
from app.ai.converters import (
    convert_docx_to_markdown,
    convert_pdf_to_markdown,
    convert_html_to_markdown,
    convert_rtf_to_markdown,
    needs_llm_conversion,
)
from app.ai.chunking import chunk_text
from app.core.config import settings
from app.db.models import DocChunkEmbeddings, DocChunks, Documents, IngestJobs
from app.utils.MinIO import minio_service

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 类型定义 - LCEL 状态传递
# ============================================================================


@dataclass
class IngestContext:
    """Pipeline 状态传递对象"""

    ingest_id: str
    db: AsyncSession
    job: Optional[IngestJobs] = None
    doc: Optional[Documents] = None
    file_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    file_path: Optional[Path] = None
    raw_text: Optional[str] = None
    markdown_text: Optional[str] = None
    documents: List[Document] = field(default_factory=list)
    chunks: List[Document] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    # 扩展字段
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None
    char_count: Optional[int] = None
    token_count: Optional[int] = None
    stage: str = "init"


# ============================================================================
# 2. 数据库操作 Mixin
# ============================================================================


class DatabaseMixin:
    """数据库操作工具类"""

    @staticmethod
    async def get_job(ctx: IngestContext) -> IngestContext:
        """获取 Job 和 Document"""
        result = await ctx.db.execute(
            select(IngestJobs)
            .options(selectinload(IngestJobs.document))
            .where(IngestJobs.ingest_id == ctx.ingest_id)
        )
        ctx.job = result.scalars().first()
        if ctx.job:
            ctx.doc = ctx.job.document
        return ctx

    @staticmethod
    async def update_job_status(
        ctx: IngestContext, status: str, error: Optional[str] = None
    ) -> IngestContext:
        """更新 Job 状态"""
        if ctx.job:
            ctx.job.status = status
            if status == "running":
                ctx.job.started_at = datetime.datetime.now(datetime.timezone.utc)
            elif status in ["succeeded", "failed"]:
                ctx.job.finished_at = datetime.datetime.now(datetime.timezone.utc)
            if error:
                ctx.job.error = error

        if ctx.doc:
            if status == "running":
                ctx.doc.status = "processing"
            elif status == "succeeded":
                ctx.doc.status = "completed"
            elif status == "failed":
                ctx.doc.status = "failed"

        await ctx.db.commit()
        return ctx


# ============================================================================
# 3. 文件处理 Runnables
# ============================================================================


async def download_file_runnable(ctx: IngestContext) -> IngestContext:
    """下载文件 Runnable"""
    if not ctx.doc:
        logger.error("[Download] Document not loaded")
        raise ValueError("Document not loaded")

    logger.info(f"[Download] ========== DOWNLOAD STAGE ==========")
    logger.info(f"[Download] Starting for doc: {ctx.doc.doc_id}")

    try:
        if ctx.doc.source_url:
            logger.info(f"[Download] Downloading from URL: {ctx.doc.source_url}")
            import httpx

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(ctx.doc.source_url)
                resp.raise_for_status()
                ctx.file_bytes = resp.content
                logger.info(f"[Download] Downloaded {len(ctx.file_bytes)} bytes from URL")

                content_disp = resp.headers.get("content-disposition", "")
                if "filename=" in content_disp:
                    ctx.filename = content_disp.split("filename=", 1)[1].strip('" ')
                else:
                    ctx.filename = (
                        Path(ctx.doc.object_key).name if ctx.doc.object_key else "download"
                    )
                logger.info(f"[Download] Filename from URL: {ctx.filename}")

        elif ctx.doc.object_key:
            logger.info(f"[Download] Downloading from MinIO: bucket={minio_service.bucket}, key={ctx.doc.object_key}")
            response = minio_service.client.get_object(
                minio_service.bucket, ctx.doc.object_key
            )
            try:
                ctx.file_bytes = response.read()
                ctx.filename = Path(ctx.doc.object_key).name
                logger.info(f"[Download] Downloaded {len(ctx.file_bytes)} bytes from MinIO, filename={ctx.filename}")
            finally:
                response.close()
                response.release_conn()
        else:
            logger.error("[Download] Neither source_url nor object_key available")
            raise ValueError("Neither source_url nor object_key available")

        logger.info(f"[Download] Completed: {ctx.filename}, size={len(ctx.file_bytes)} bytes")
        logger.info(f"[Download] ========== DOWNLOAD STAGE DONE ==========")
    except Exception as e:
        logger.exception(f"[Download] Failed: {e}")
        raise

    return ctx


async def extract_text_runnable(ctx: IngestContext) -> IngestContext:
    """
    提取文本 Runnable - 分层转换策略

    策略:
    1. 优先使用专用工具 (Pandoc/html2text) 转换 Markdown
    2. 次选专业库 (pdfminer) 提取文本
    3. 降级到 LangChain Loaders
    4. 最后手段才用 LLM (仅 OCR/乱码)
    """
    if not ctx.file_bytes or not ctx.filename:
        logger.error("[Extract] File not downloaded")
        raise ValueError("File not downloaded")

    logger.info(f"[Extract] ========== EXTRACT STAGE ==========")
    logger.info(f"[Extract] Processing file: {ctx.filename}")
    logger.info(f"[Extract] File size: {len(ctx.file_bytes)} bytes")

    ctx.file_size = len(ctx.file_bytes)
    ctx.mime_type = _guess_mime_type(ctx.filename, ctx.file_bytes)
    logger.info(f"[Extract] Detected MIME type: {ctx.mime_type}")

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=Path(ctx.filename).suffix
    ) as f:
        f.write(ctx.file_bytes)
        ctx.file_path = Path(f.name)
        logger.info(f"[Extract] Temp file created: {ctx.file_path}")

    suffix = ctx.file_path.suffix.lower()
    conversion_method = "direct"  # 标记转换方式

    # ================================================================
    # 格式专用转换器 (优先级最高)
    # ================================================================

    # DOCX/DOC -> 使用 Pandoc (直接输出 Markdown)
    if suffix in {".docx", ".doc"}:
        logger.info(f"[Extract] Processing as DOCX/DOC, suffix={suffix}")
        result = convert_docx_to_markdown(ctx.file_path)
        if result:
            ctx.raw_text = result
            conversion_method = "pandoc"
            logger.info(f"[Extract] Pandoc conversion successful")
        else:
            # Pandoc 不可用，降级到 Docx2txtLoader
            logger.info(f"[Extract] Pandoc failed, falling back to Docx2txtLoader")
            from langchain_community.document_loaders import Docx2txtLoader
            loader = Docx2txtLoader(str(ctx.file_path))
            docs = loader.load()
            ctx.raw_text = "\n\n".join(d.page_content for d in docs)
            conversion_method = "docx2txt"
            logger.info(f"[Extract] Docx2txtLoader conversion successful")

    # HTML -> 使用 html2text (直接输出 Markdown)
    elif suffix in {".html", ".htm"}:
        logger.info(f"[Extract] Processing as HTML, suffix={suffix}")
        result = convert_html_to_markdown(ctx.file_path)
        if result:
            ctx.raw_text = result
            conversion_method = "html2text"
            logger.info(f"[Extract] html2text conversion successful")
        else:
            # html2text 不可用，降级到直接读取
            logger.info(f"[Extract] html2text failed, falling back to raw read")
            ctx.raw_text = await _read_text_file(ctx.file_path)
            conversion_method = "raw"

    # RTF -> 使用 Pandoc
    elif suffix == ".rtf":
        logger.info(f"[Extract] Processing as RTF")
        result = convert_rtf_to_markdown(ctx.file_path)
        if result:
            ctx.raw_text = result
            conversion_method = "pandoc"
            logger.info(f"[Extract] Pandoc RTF conversion successful")
        else:
            logger.info(f"[Extract] Pandoc RTF failed, falling back to TextLoader")
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(str(ctx.file_path), encoding="utf-8", errors="ignore")
            docs = loader.load()
            ctx.raw_text = "\n\n".join(d.page_content for d in docs)
            conversion_method = "textloader"

    # ODT -> 使用 Pandoc
    elif suffix == ".odt":
        logger.info(f"[Extract] Processing as ODT")
        result = convert_odt_to_markdown(ctx.file_path)
        if result:
            ctx.raw_text = result
            conversion_method = "pandoc"
            logger.info(f"[Extract] Pandoc ODT conversion successful")
        else:
            logger.info(f"[Extract] Pandoc ODT failed, falling back to TextLoader")
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(str(ctx.file_path), encoding="utf-8", errors="ignore")
            docs = loader.load()
            ctx.raw_text = "\n\n".join(d.page_content for d in docs)
            conversion_method = "textloader"

    # PDF -> 使用 pdfminer (保留文本结构)
    elif suffix == ".pdf":
        logger.info(f"[Extract] Processing as PDF")
        result = convert_pdf_to_markdown(ctx.file_path)
        if result:
            ctx.raw_text = result
            conversion_method = "pdfminer"
            logger.info(f"[Extract] pdfminer conversion successful")
        else:
            # 降级到 PyPDFLoader
            logger.info(f"[Extract] pdfminer failed, falling back to PyPDFLoader")
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(str(ctx.file_path))
            docs = loader.load()
            ctx.raw_text = "\n\n".join(d.page_content for d in docs)
            conversion_method = "pypdf"
            logger.info(f"[Extract] PyPDFLoader conversion successful")

    # Markdown 直接读取
    elif suffix in MARKDOWN_SUFFIXES:
        logger.info(f"[Extract] Processing as Markdown, suffix={suffix}")
        ctx.raw_text = await _read_text_file(ctx.file_path)
        conversion_method = "direct"
        logger.info(f"[Extract] Markdown direct read successful")

    # 纯文本/配置文件直接读取
    elif suffix in {".txt", ".csv", ".json", ".yaml", ".yml", ".xml"}:
        logger.info(f"[Extract] Processing as text/config, suffix={suffix}")
        ctx.raw_text = await _read_text_file(ctx.file_path)
        conversion_method = "direct"
        logger.info(f"[Extract] Text file read successful")

    # 其他格式降级到 TextLoader
    else:
        logger.info(f"[Extract] Processing as unknown format, suffix={suffix}, using TextLoader")
        from langchain_community.document_loaders import TextLoader
        loader = TextLoader(str(ctx.file_path), encoding="utf-8", errors="ignore")
        docs = loader.load()
        ctx.raw_text = "\n\n".join(d.page_content for d in docs)
        conversion_method = "textloader"

    ctx.documents = [
        Document(
            page_content=ctx.raw_text,
            metadata={"source": ctx.filename, "conversion_method": conversion_method}
        )
    ]
    logger.info(f"[Extract] Text extracted: {len(ctx.raw_text)} chars, method: {conversion_method}")
    logger.info(f"[Extract] First 200 chars: {ctx.raw_text[:200] if ctx.raw_text else '(empty)'}")
    logger.info(f"[Extract] ========== EXTRACT STAGE DONE ==========")
    return ctx


async def _read_text_file(file_path: Path) -> str:
    """读取文本文件，支持多种编码"""
    encodings = ("utf-8", "utf-8-sig", "gb18030", "latin-1")
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _guess_mime_type(filename: str, file_bytes: Optional[bytes] = None) -> str:
    """根据文件扩展名和内容猜测 MIME 类型"""
    import mimetypes

    suffix = Path(filename).suffix.lower()
    mime_type, _ = mimetypes.guess_type(filename)

    if mime_type:
        return mime_type

    if file_bytes:
        if file_bytes.startswith(b"%PDF"):
            return "application/pdf"
        if file_bytes.startswith(b"PK\x03\x04"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
            return "application/msword"

    return "application/octet-stream"


def _cleanup_temp_file(ctx: IngestContext) -> None:
    """清理临时文件"""
    if ctx.file_path and ctx.file_path.exists():
        try:
            ctx.file_path.unlink()
            logger.info(f"[Cleanup] Removed temp file: {ctx.file_path}")
        except Exception as e:
            logger.warning(f"[Cleanup] Failed to remove temp file: {e}")


# ============================================================================
# 4. Markdown 转换 Chain (LCEL)
# ============================================================================


def check_needs_conversion(ctx: IngestContext) -> bool:
    """
    检查是否需要 LLM Markdown 转换

    分层策略:
    1. 如果文本已经是 Markdown -> 不需要 LLM 转换
    2. 如果是 PDF (结构化文档) -> 可能需要 LLM 优化格式
    3. 如果是 OCR 或乱码文本 -> 需要 LLM 转换
    4. 其他情况 -> 专用工具已处理，不需要 LLM
    """
    if not ctx.raw_text:
        return False

    # 如果文本已经是 Markdown，不需要转换
    if looks_like_markdown(ctx.raw_text):
        return False

    # 只有 OCR、乱码、扫描文档才需要 LLM
    return needs_llm_conversion(ctx.filename or "", ctx.raw_text)


def split_for_llm(ctx: IngestContext) -> List[str]:
    """分段以适应 LLM 上下文"""
    text = normalize_text(ctx.raw_text or "")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,
        chunk_overlap=200,
    )
    return splitter.split_text(text)


async def convert_segment(text: str) -> str:
    """单段 Markdown 转换"""
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    llm = ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        temperature=0.2,
        api_key=SecretStr(settings.DEEPSEEK_API_KEY)
        if settings.DEEPSEEK_API_KEY
        else None,
        base_url=settings.DEEPSEEK_BASE_URL,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a formatter. Convert the input into clean Markdown, "
                "preserving headings, lists, tables, and code blocks when present.",
            ),
            ("human", "{content}"),
        ]
    )

    chain = prompt | llm | StrOutputParser()

    try:
        return await chain.ainvoke({"content": text})
    except Exception as e:
        logger.warning(f"Conversion failed: {e}, returning original")
        return text


async def convert_all_segments(ctx: IngestContext) -> IngestContext:
    """转换所有段落"""
    segments = split_for_llm(ctx)
    if not segments:
        ctx.markdown_text = normalize_markdown(ctx.raw_text or "")
        return ctx

    tasks = [convert_segment(seg) for seg in segments]
    converted = await asyncio.gather(*tasks)

    ctx.markdown_text = normalize_markdown("\n\n".join(converted))
    ctx.documents = [
        Document(page_content=ctx.markdown_text, metadata={"converted": True})
    ]
    return ctx


def pass_through_markdown(ctx: IngestContext) -> IngestContext:
    """直接通过（已是 Markdown）"""
    ctx.markdown_text = normalize_markdown(ctx.raw_text or "")
    ctx.documents = [
        Document(page_content=ctx.markdown_text, metadata={"converted": False})
    ]
    return ctx


def create_markdown_conversion_chain():
    """创建 Markdown 转换的 LCEL Chain"""
    return RunnableBranch(
        (check_needs_conversion, RunnableLambda(convert_all_segments)),
        RunnableLambda(pass_through_markdown),
    )


# ============================================================================
# 5. 存储和切块 Runnables
# ============================================================================


async def save_markdown_runnable(ctx: IngestContext) -> IngestContext:
    """保存 Markdown Runnable"""
    if not ctx.doc or not ctx.markdown_text:
        logger.error("[Save] Missing doc or markdown")
        raise ValueError("Missing doc or markdown")

    logger.info(f"[Save] ========== SAVE MARKDOWN STAGE ==========")
    logger.info(f"[Save] Doc: {ctx.doc.doc_id}")

    markdown_key = (
        ctx.doc.object_key + ".md"
        if ctx.doc.object_key
        else f"documents/{ctx.doc.doc_id}.md"
    )
    logger.info(f"[Save] Uploading to MinIO: {markdown_key}")

    try:
        minio_service.upload_text(markdown_key, ctx.markdown_text)
        logger.info(f"[Save] MinIO upload successful")
    except Exception as e:
        logger.exception(f"[Save] MinIO upload failed: {e}")
        raise

    ctx.doc.markdown_object_key = markdown_key
    ctx.doc.markdown_text = ctx.markdown_text
    ctx.doc.title = ctx.doc.title or _extract_title(ctx.markdown_text)
    ctx.doc.content_hash = hashlib.sha256(ctx.markdown_text.encode()).hexdigest()
    ctx.doc.source_mime = ctx.mime_type

    ctx.char_count = len(ctx.markdown_text)
    ctx.token_count = estimate_token_count(ctx.markdown_text)

    logger.info(f"[Save] Doc title: {ctx.doc.title}")
    logger.info(f"[Save] Content hash: {ctx.doc.content_hash}")
    logger.info(f"[Save] Char count: {ctx.char_count}, Token count: {ctx.token_count}")

    _cleanup_temp_file(ctx)

    await ctx.db.commit()
    logger.info(f"[Save] Database commit successful")
    logger.info(f"[Save] Markdown saved: {markdown_key}")
    logger.info(f"[Save] ========== SAVE MARKDOWN STAGE DONE ==========")
    return ctx


def _extract_title(text: str) -> Optional[str]:
    for line in normalize_text(text).split("\n"):
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:255] or None
        elif line:
            return line[:255]
    return None


async def chunk_document_runnable(ctx: IngestContext) -> IngestContext:
    """
    文档切块 Runnable - 使用 strategies.py 的智能切块策略

    策略说明:
    - atomic: 短文本不分割
    - section_pack: 结构化文档按标题/段落切分
    - fixed_size_overlap: 字幕/OCR 文本滑动窗口切分
    """
    if not ctx.markdown_text:
        logger.error("[Chunk] No markdown text to chunk")
        raise ValueError("No markdown text to chunk")

    logger.info(f"[Chunk] ========== CHUNK STAGE ==========")
    logger.info(f"[Chunk] Markdown text length: {len(ctx.markdown_text)} chars")

    # 使用 strategies.py 的智能切块策略
    # source="markdown" 会被 detect_content_type 识别为 section_pack
    logger.info(f"[Chunk] Calling chunk_text()...")
    chunks = chunk_text(
        text=ctx.markdown_text,
        source="markdown",
    )
    logger.info(f"[Chunk] chunk_text() returned {len(chunks)} chunks")

    # 将 Chunk 对象转换为 LangChain Document 对象（兼容后续处理）
    final_chunks = []
    for ch in chunks:
        doc = Document(
            page_content=ch.content,
            metadata={
                "chunk_global_index": ch.index,
                "start_offset": ch.start_char,
                "end_offset": ch.end_char,
                "source_type": ch.source_type,
                **ch.metadata,
            }
        )
        final_chunks.append(doc)

    ctx.chunks = final_chunks

    if chunks:
        logger.info(f"[Chunk] First chunk: {len(chunks[0].content)} chars, type: {chunks[0].source_type}")
        logger.info(f"[Chunk] Chunk sizes: {[len(c.content) for c in chunks[:5]]}")

    logger.info(f"[Chunk] Created {len(final_chunks)} chunks, strategy: {chunks[0].source_type if chunks else 'none'}")
    logger.info(f"[Chunk] ========== CHUNK STAGE DONE ==========")
    return ctx


async def store_embeddings_runnable(ctx: IngestContext) -> IngestContext:
    """存储 Embeddings Runnable"""
    if not ctx.doc or not ctx.chunks:
        logger.warning("[Embeddings] No doc or chunks, skipping embeddings")
        return ctx

    logger.info(f"[Embeddings] ========== EMBEDDINGS STAGE ==========")
    logger.info(f"[Embeddings] Doc: {ctx.doc.doc_id}, Chunks: {len(ctx.chunks)}")

    texts = [c.page_content for c in ctx.chunks if c.page_content.strip()]
    if not texts:
        logger.warning("[Embeddings] No valid texts to embed")
        return ctx

    logger.info(f"[Embeddings] Processing {len(texts)} texts for embedding")

    batch_size = 32
    chunk_index = 0
    model_name = "unknown"

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(texts) + batch_size - 1) // batch_size

        logger.info(f"[Embeddings] Processing batch {batch_num}/{total_batches}, size={len(batch)}")

        try:
            vectors, model_name = await embed_documents_with_fallback(batch)
            logger.info(f"[Embeddings] Batch {batch_num}: got {len(vectors)} vectors, model={model_name}")
        except Exception as e:
            logger.exception(f"[Embeddings] Batch {batch_num} embedding failed: {e}")
            raise

        for j, (chunk_doc, vector) in enumerate(zip(ctx.chunks[i : i + batch_size], vectors)):
            try:
                chunk = DocChunks(
                    doc_id=ctx.doc.doc_id,
                    chunk_index=chunk_index,
                    content=chunk_doc.page_content,
                    token_count=estimate_token_count(chunk_doc.page_content),
                    start_offset=chunk_doc.metadata.get("start_offset"),
                    end_offset=chunk_doc.metadata.get("end_offset"),
                    section_path=chunk_doc.metadata.get("section_path"),
                    chunk_metadata=chunk_doc.metadata,
                )
                ctx.db.add(chunk)
                await ctx.db.flush()

                embedding = DocChunkEmbeddings(
                    chunk_id=chunk.chunk_id,
                    model=model_name,
                    embedding=vector,  # 直接存储向量列表，不要 json.dumps
                )
                ctx.db.add(embedding)
                chunk_index += 1
            except Exception as e:
                logger.error(f"[Embeddings] Failed to store chunk {chunk_index}: {e}")
                raise

    await ctx.db.commit()
    logger.info(f"[Embeddings] Database commit successful")
    logger.info(f"[Embeddings] Stored {chunk_index} chunks with embeddings, model={model_name}")
    logger.info(f"[Embeddings] ========== EMBEDDINGS STAGE DONE ==========")
    return ctx


async def build_graph_runnable(ctx: IngestContext) -> IngestContext:
    """
    构建知识图谱 Runnable - 使用多步抽取策略

    多步抽取流程：
    1. 实体抽取 (CNER)
    2. 实体属性补全
    3. 关系抽取 (RE)
    4. 关系属性补全
    5. 反思迭代 (默认2轮)
    """
    logger.info(
        f"[Graph] Starting build_graph_runnable (multi-step extraction), "
        f"chunks: {len(ctx.chunks) if ctx.chunks else 0}, doc: {ctx.doc is not None}"
    )

    neo4j_uri = (settings.NEO4J_URI or "").strip()
    if not neo4j_uri:
        logger.warning("[Graph] No Neo4j URI configured, skipping")
        return ctx
    if not ctx.chunks:
        logger.warning("[Graph] No chunks to process, skipping")
        return ctx
    if not ctx.doc:
        logger.warning("[Graph] No document, skipping")
        return ctx

    try:
        from neo4j import GraphDatabase
    except Exception as e:
        logger.warning(
            f"[Graph] Failed to import neo4j driver: {e}, skipping graph build"
        )
        return ctx

    try:
        driver = GraphDatabase.driver(
            neo4j_uri, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )

        with driver.session(database=settings.NEO4J_DATABASE) as session:
            test_result = session.run("RETURN 1")
            test_result.consume()

        # 导入多步抽取器
        from app.ai.graph_extractor import extract_graph_from_text

        # 只处理前10个chunk
        chunks_to_process = ctx.chunks[:10]

        logger.info(f"[Graph] Starting multi-step graph extraction for doc: {ctx.doc.doc_id}")

        doc_id_str = str(ctx.doc.doc_id)
        graph_id_str = str(ctx.doc.graph_id)
        source_file = ctx.doc.title or "unknown"

        total_nodes = 0
        total_rels = 0

        for i, chunk in enumerate(chunks_to_process):
            try:
                text = chunk.page_content[:3000]  # 稍微增加文本长度限制
                chunk_index = chunk.metadata.get("chunk_global_index", i)

                # 生成 episode_ref
                episode_ref = f"{doc_id_str}:chunk_{chunk_index}"

                # 执行多步抽取
                result = await extract_graph_from_text(
                    text=text,
                    episode_ref=episode_ref,
                    reflection_iters=2,
                )

                entities = result.entities
                relations = result.relations

                logger.info(
                    f"[Graph] Chunk {i + 1}: {len(entities)} entities, {len(relations)} relations"
                )

                if not entities and not relations:
                    continue

                with driver.session(database=settings.NEO4J_DATABASE) as session:
                    # 存储实体
                    for entity in entities:
                        labels = ":".join(entity.labels) if entity.labels else "Entity"

                        session.run(
                            f"""
                            MERGE (e:{labels} {{name: $name, graph_id: $graph_id}})
                            SET e.description = $desc,
                                e.attributes = $attrs,
                                e.doc_id = $doc_id,
                                e.source_file = $source_file
                            """,
                            name=entity.name,
                            graph_id=graph_id_str,
                            desc=entity.description or "",
                            attrs=json.dumps(entity.attributes),
                            doc_id=doc_id_str,
                            source_file=source_file,
                        )

                    # 存储关系
                    for rel in relations:
                        # 关系类型规范化
                        rel_type = rel.name if rel.name else "RELATED_TO"

                        session.run(
                            """
                            MATCH (a {name: $source, graph_id: $graph_id})
                            MATCH (b {name: $target, graph_id: $graph_id})
                            MERGE (a)-[r:RELATES {type: $type, doc_id: $doc_id}]->(b)
                            SET r.fact = $fact,
                                r.confidence = $confidence,
                                r.polarity = $polarity,
                                r.qualifiers = $qualifiers,
                                r.attributes = $attrs,
                                r.episode_ref = $episode_ref
                            """,
                            source=rel.source,
                            target=rel.target,
                            type=rel_type,
                            fact=rel.fact,
                            confidence=rel.confidence if rel.confidence is not None else 1.0,
                            polarity=rel.polarity if rel.polarity is not None else 1,
                            qualifiers=json.dumps(rel.qualifiers),
                            attrs=json.dumps(rel.attributes),
                            graph_id=graph_id_str,
                            doc_id=doc_id_str,
                            episode_ref=episode_ref,
                        )

                total_nodes += len(entities)
                total_rels += len(relations)

            except Exception as batch_e:
                logger.error(f"[Graph] Chunk {i + 1} processing failed: {batch_e}")
                continue

        driver.close()

        logger.info(
            f"[Graph] Successfully built graph for doc: {ctx.doc.doc_id}, "
            f"nodes: {total_nodes}, rels: {total_rels}"
        )

    except Exception as e:
        logger.exception(f"[Graph] Critical failure during graph build: {e}")
        pass

    return ctx


# ============================================================================
# 6. 主 Pipeline Chain 组装
# ============================================================================


@runnable_chain
async def initialize(ctx: IngestContext) -> IngestContext:
    """初始化：获取 job 和 doc，更新状态"""
    logger.info(f"[Pipeline] ========== INGEST PIPELINE START ==========")
    logger.info(f"[Pipeline] ingest_id: {ctx.ingest_id}")

    ctx = await DatabaseMixin.get_job(ctx)
    if not ctx.job:
        logger.error(f"[Pipeline] Job not found: {ctx.ingest_id}")
        raise ValueError(f"Job not found: {ctx.ingest_id}")
    if not ctx.doc:
        logger.error(f"[Pipeline] Document not found for job: {ctx.ingest_id}")
        raise ValueError(f"Document not found for job: {ctx.ingest_id}")

    logger.info(f"[Pipeline] Job found: {ctx.job.ingest_id}, status: {ctx.job.status}")
    logger.info(f"[Pipeline] Doc found: doc_id={ctx.doc.doc_id}, title={ctx.doc.title}")
    logger.info(f"[Pipeline] Doc source_url={ctx.doc.source_url}, object_key={ctx.doc.object_key}")
    logger.info(f"[Pipeline] Doc space_id={ctx.doc.space_id}, graph_id={ctx.doc.graph_id}")

    await DatabaseMixin.update_job_status(ctx, "running")
    logger.info(f"[Pipeline] Status updated to 'running'")
    return ctx


@runnable_chain
async def finalize(ctx: IngestContext) -> IngestContext:
    """完成处理"""
    logger.info(f"[Finalize] ========== FINALIZE STAGE ==========")

    _cleanup_temp_file(ctx)
    await DatabaseMixin.update_job_status(ctx, "succeeded")
    ctx.success = True
    doc_id = ctx.doc.doc_id if ctx.doc else "unknown"
    logger.info(
        f"[Pipeline] ========== INGEST PIPELINE COMPLETED SUCCESSFULLY =========="
    )
    logger.info(
        f"[Pipeline] Doc: {doc_id}, "
        f"chars: {ctx.char_count}, tokens: {ctx.token_count}, chunks: {len(ctx.chunks) if ctx.chunks else 0}"
    )
    logger.info(f"[Pipeline] ========== INGEST PIPELINE COMPLETED ==========")
    logger.info(f"[Finalize] ========== FINALIZE STAGE DONE ==========")
    return ctx


def create_ingest_pipeline():
    """创建完整的 Ingest Pipeline (LCEL)"""

    file_processing = RunnableLambda(download_file_runnable) | RunnableLambda(
        extract_text_runnable
    )
    markdown_chain = create_markdown_conversion_chain()
    save_step = RunnableLambda(save_markdown_runnable)
    chunk_step = RunnableLambda(chunk_document_runnable)

    parallel_processing = RunnableParallel(
        {
            "embeddings": RunnableLambda(store_embeddings_runnable),
            "graph": RunnableLambda(build_graph_runnable),
        }
    ) | RunnableLambda(lambda results: results["embeddings"])

    pipeline = (
        initialize
        | file_processing
        | markdown_chain
        | save_step
        | chunk_step
        | parallel_processing
        | finalize
    )

    return pipeline


# ============================================================================
# 7. 主类（向后兼容）
# ============================================================================


class LangChainIngestPipeline:
    """LCEL 实现的 Ingest Pipeline（向后兼容）"""

    LLM_CHUNK_SIZE = 3000
    LLM_CHUNK_OVERLAP = 200
    MARKDOWN_CHUNK_SIZE = 1200
    MARKDOWN_CHUNK_OVERLAP = 120
    EMBEDDING_BATCH_SIZE = 32

    def __init__(self, db: AsyncSession):
        self.db = db
        self.pipeline = create_ingest_pipeline()

    async def run(self, ingest_id: str) -> None:
        """执行 Ingest（保持与原接口兼容）"""
        logger.info(f"[Pipeline.run] Starting pipeline for ingest_id: {ingest_id}")

        ctx = IngestContext(ingest_id=ingest_id, db=self.db)

        try:
            logger.info(f"[Pipeline.run] Invoking pipeline...")
            result = await self.pipeline.ainvoke(ctx)
            if not result.success:
                logger.error(f"[Pipeline.run] Pipeline returned success=False")
                raise RuntimeError("Pipeline failed")
            logger.info(f"[Pipeline.run] Pipeline completed successfully")
        except Exception as e:
            logger.exception(f"[Pipeline.run] Pipeline failed: {e}")
            ctx.error = str(e)
            _cleanup_temp_file(ctx)
            if ctx.job:
                logger.info(f"[Pipeline.run] Updating job status to failed")
                await DatabaseMixin.update_job_status(ctx, "failed", error=str(e))
            raise
