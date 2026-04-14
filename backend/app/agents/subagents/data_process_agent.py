"""Deprecated data ingest subagent.

文件摄入已收敛为外部上传 API 驱动流程。
该类仅在迁移期保留，不再属于 MainAgent 的运行时能力边界。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core import DataProcessState
from app.ai.markdown_utils import MARKDOWN_SUFFIXES
from app.core.config import settings
from app.db.models import Documents
from app.utils.MinIO import minio_service
import uuid

logger = logging.getLogger(__name__)


class DataProcessAgent:
    """Agent for processing documents using the ingest pipeline."""

    def __init__(self, db: AsyncSession):
        """
        Initialize DataProcessAgent.

        Args:
            db: AsyncSession for database operations
        """
        self.db = db
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for data processing."""
        builder = StateGraph(DataProcessState)

        builder.add_node("prepare_source", RunnableLambda(self._prepare_source_node))
        builder.add_node("extract_text", RunnableLambda(self._extract_text_node))
        builder.add_node("convert_markdown", RunnableLambda(self._convert_markdown_node))
        builder.add_node("chunk_document", RunnableLambda(self._chunk_document_node))
        builder.add_node("generate_embeddings", RunnableLambda(self._generate_embeddings_node))
        builder.add_node("build_knowledge_graph", RunnableLambda(self._build_knowledge_graph_node))
        builder.add_node("save_to_database", RunnableLambda(self._save_to_database_node))

        builder.add_edge("prepare_source", "extract_text")
        builder.add_edge("extract_text", "convert_markdown")
        builder.add_edge("convert_markdown", "chunk_document")
        builder.add_edge("chunk_document", "generate_embeddings")
        builder.add_edge("generate_embeddings", "build_knowledge_graph")
        builder.add_edge("build_knowledge_graph", "save_to_database")
        builder.add_edge("save_to_database", END)

        builder.set_entry_point("prepare_source")
        return builder.compile()

    async def _prepare_source_node(self, state: DataProcessState) -> DataProcessState:
        """Prepare the source for processing - download from MinIO or URL."""
        source_type = state.get("source_type", "")
        source_path = state.get("source_path", "")

        try:
            if source_type == "minio":
                # Download from MinIO
                response = minio_service.client.get_object(
                    minio_service.bucket, source_path
                )
                try:
                    file_bytes = response.read()
                    state["source_content"] = file_bytes
                finally:
                    response.close()
                    response.release_conn()

            elif source_type == "url":
                # Download from URL
                import httpx
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(source_path)
                    resp.raise_for_status()
                    state["source_content"] = resp.content

            elif source_type == "text":
                # Direct text content
                state["source_content"] = source_path.encode("utf-8")

            elif source_type == "file":
                # Local file path
                file_path = Path(source_path)
                if file_path.exists():
                    state["source_content"] = file_path.read_bytes()
                else:
                    state["error"] = f"File not found: {source_path}"
                    return state
            else:
                state["error"] = f"Unsupported source type: {source_type}"
                return state

            state["status"] = "source_prepared"
        except Exception as e:
            logger.error(f"Source preparation failed: {e}")
            state["error"] = f"Failed to prepare source: {str(e)}"
            state["status"] = "failed"

        return state

    async def _extract_text_node(self, state: DataProcessState) -> DataProcessState:
        """Extract text from the source content."""
        source_content = state.get("source_content")
        if not source_content:
            state["error"] = "No source content to extract"
            return state

        filename = state.get("source_path", "unknown")
        suffix = Path(filename).suffix.lower()

        try:
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(source_content)
                file_path = Path(f.name)

            # Extract text based on file type
            if suffix in MARKDOWN_SUFFIXES or suffix in {
                ".txt", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"
            }:
                encodings = ("utf-8", "utf-8-sig", "gb18030", "latin-1")
                for encoding in encodings:
                    try:
                        state["extracted_text"] = file_path.read_text(encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    state["extracted_text"] = file_path.read_text(encoding="utf-8", errors="ignore")

            elif suffix == ".pdf":
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(file_path))
                docs = loader.load()
                state["extracted_text"] = "\n\n".join(d.page_content for d in docs)

            elif suffix in {".docx", ".doc"}:
                from langchain_community.document_loaders import Docx2txtLoader
                loader = Docx2txtLoader(str(file_path))
                docs = loader.load()
                state["extracted_text"] = "\n\n".join(d.page_content for d in docs)

            else:
                from langchain_community.document_loaders import TextLoader
                loader = TextLoader(str(file_path), encoding="utf-8", errors="ignore")
                docs = loader.load()
                state["extracted_text"] = "\n\n".join(d.page_content for d in docs)

            # Cleanup temp file
            file_path.unlink(missing_ok=True)
            state["status"] = "text_extracted"

        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            state["error"] = f"Failed to extract text: {str(e)}"
            state["status"] = "failed"

        return state

    async def _convert_markdown_node(self, state: DataProcessState) -> DataProcessState:
        """Convert extracted text to markdown format."""
        extracted_text = state.get("extracted_text")
        if not extracted_text:
            state["error"] = "No extracted text to convert"
            return state

        try:
            from app.ai.markdown_utils import normalize_markdown, looks_like_markdown

            if looks_like_markdown(extracted_text):
                state["markdown_content"] = normalize_markdown(extracted_text)
            else:
                # Use LLM to convert to markdown
                state["markdown_content"] = await self._llm_convert_to_markdown(extracted_text)

            state["status"] = "markdown_converted"
        except Exception as e:
            logger.error(f"Markdown conversion failed: {e}")
            state["error"] = f"Failed to convert to markdown: {str(e)}"
            state["status"] = "failed"

        return state

    async def _llm_convert_to_markdown(self, text: str) -> str:
        """Use LLM to convert text to markdown."""
        from app.services.base import get_llm_client

        llm = get_llm_client(temperature=0.2)

        # Split text into chunks if too long
        max_chars = 3000
        if len(text) <= max_chars:
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are a formatter. Convert the input into clean Markdown, preserving headings, lists, tables, and code blocks when present."),
                ("human", "{content}")
            ])
            chain = prompt | llm | StrOutputParser()
            result = await chain.ainvoke({"content": text})
            return result
        else:
            # Process in chunks
            chunks = [text[i:i+max_chars] for i in range(0, len(text), max_chars)]
            results = []
            for chunk in chunks:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", "You are a formatter. Convert the input into clean Markdown."),
                    ("human", "{content}")
                ])
                chain = prompt | llm | StrOutputParser()
                result = await chain.ainvoke({"content": chunk})
                results.append(result)
            return "\n\n".join(results)

    async def _chunk_document_node(self, state: DataProcessState) -> DataProcessState:
        """Split markdown into chunks."""
        markdown_content = state.get("markdown_content")
        if not markdown_content:
            state["error"] = "No markdown content to chunk"
            return state

        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

            splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=[
                    ("#", "Header 1"),
                    ("##", "Header 2"),
                    ("###", "Header 3"),
                ]
            )

            try:
                header_chunks = splitter.split_text(markdown_content)
            except Exception:
                fallback = RecursiveCharacterTextSplitter(
                    chunk_size=1200,
                    chunk_overlap=120,
                )
                header_chunks = fallback.create_documents([markdown_content])

            # Further split large chunks
            fine_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1200,
                chunk_overlap=120,
            )

            final_chunks = []
            for idx, chunk in enumerate(header_chunks):
                if len(chunk.page_content) > 1200:
                    sub_chunks = fine_splitter.split_documents([chunk])
                    for sub in sub_chunks:
                        sub.metadata["chunk_global_index"] = len(final_chunks)
                        sub.metadata["parent_chunk_index"] = idx
                        final_chunks.append(sub)
                else:
                    chunk.metadata["chunk_global_index"] = len(final_chunks)
                    final_chunks.append(chunk)

            state["chunks"] = [c.page_content for c in final_chunks]
            state["status"] = "document_chunked"

        except Exception as e:
            logger.error(f"Chunking failed: {e}")
            state["error"] = f"Failed to chunk document: {str(e)}"
            state["status"] = "failed"

        return state

    async def _generate_embeddings_node(self, state: DataProcessState) -> DataProcessState:
        """Generate embeddings for document chunks."""
        chunks = state.get("chunks", [])
        if not chunks:
            state["error"] = "No chunks to embed"
            return state

        try:
            from app.ai.embedding_client import embed_documents_with_fallback

            texts = [c for c in chunks if c.strip()]
            if not texts:
                state["error"] = "No valid chunks to embed"
                return state

            # Generate embeddings
            vectors, model_name = await embed_documents_with_fallback(texts)

            # Store embedding IDs (we'll save to DB later in save_to_database)
            state["embedding_ids"] = [f"emb_{i}_{model_name}" for i in range(len(vectors))]
            state["status"] = "embeddings_generated"

        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            state["error"] = f"Failed to generate embeddings: {str(e)}"
            state["status"] = "failed"

        return state

    async def _build_knowledge_graph_node(self, state: DataProcessState) -> DataProcessState:
        """Build knowledge graph from document chunks."""
        chunks = state.get("chunks", [])
        if not chunks:
            state["graph_nodes"] = 0
            return state

        try:
            from app.services.base import get_llm_client
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            import re

            llm = get_llm_client(temperature=0)

            extraction_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个知识图谱提取专家。从给定的文本中提取实体和关系。

提取规则：
1. 实体：提取主要实体（人物、组织、地点、概念、技术等）
2. 关系：提取实体之间的关系

请以JSON格式返回，格式如下：
{
    "entities": [
        {"id": "实体1", "type": "类型", "description": "描述"}
    ],
    "relationships": [
        {"source": "实体1", "target": "实体2", "type": "关系类型"}
    ]
}

只返回JSON，不要其他内容。"""),
                ("human", "{text}")
            ])

            extraction_chain = extraction_prompt | llm | StrOutputParser()

            total_nodes = 0
            chunks_to_process = chunks[:10]  # Limit to first 10 chunks

            neo4j_uri = (settings.NEO4J_URI or "").strip()
            if neo4j_uri:
                from neo4j import GraphDatabase
                driver = GraphDatabase.driver(
                    neo4j_uri, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
                )

                for i, chunk_text in enumerate(chunks_to_process):
                    try:
                        result = await extraction_chain.ainvoke({"text": chunk_text[:2000]})
                        json_str = re.search(r'\{.*\}', result, re.DOTALL)
                        if not json_str:
                            continue

                        data = json.loads(json_str.group())
                        entities = data.get("entities", [])
                        relationships = data.get("relationships", [])

                        graph_id = state.get("doc_id", str(uuid.uuid4()))

                        with driver.session(database=settings.NEO4J_DATABASE) as session:
                            for entity in entities:
                                session.run(
                                    """
                                    MERGE (e:Entity {id: $id, graph_id: $graph_id})
                                    SET e.type = $type, e.description = $desc
                                    """,
                                    id=entity.get("id", ""),
                                    graph_id=graph_id,
                                    type=entity.get("type", "Entity"),
                                    desc=entity.get("description", ""),
                                )

                            for rel in relationships:
                                session.run(
                                    """
                                    MATCH (a:Entity {id: $source, graph_id: $graph_id})
                                    MATCH (b:Entity {id: $target, graph_id: $graph_id})
                                    MERGE (a)-[r:RELATES {type: $type}]->(b)
                                    """,
                                    source=rel.get("source", ""),
                                    target=rel.get("target", ""),
                                    type=rel.get("type", "RELATED_TO"),
                                    graph_id=graph_id,
                                )

                        total_nodes += len(entities)

                    except Exception as e:
                        logger.warning(f"Graph extraction batch {i} failed: {e}")
                        continue

                driver.close()

            state["graph_nodes"] = total_nodes
            state["status"] = "knowledge_graph_built"

        except Exception as e:
            logger.error(f"Knowledge graph build failed: {e}")
            state["error"] = f"Failed to build knowledge graph: {str(e)}"
            state["status"] = "failed"

        return state

    async def _save_to_database_node(self, state: DataProcessState) -> DataProcessState:
        """Save processed document and chunks to database."""
        try:
            markdown_content = state.get("markdown_content", "")
            chunks = state.get("chunks", [])

            if not markdown_content:
                state["error"] = "No content to save"
                return state

            # Create document record
            doc_id = uuid.uuid4()
            graph_id = uuid.uuid4()

            doc = Documents(
                doc_id=doc_id,
                space_id=state.get("space_id", 1),  # Default space
                graph_id=graph_id,
                title=Path(state.get("source_path", "Document")).name[:255],
                markdown_text=markdown_content,
                status="completed",
                created_by=state.get("user_id", 1),
            )

            self.db.add(doc)
            await self.db.flush()

            # Save chunks and embeddings
            from app.db.models import DocChunks, DocChunkEmbeddings
            from app.ai.markdown_utils import estimate_token_count
            from app.ai.embedding_client import embed_documents_with_fallback
            import json

            texts = [c for c in chunks if c.strip()]
            if texts:
                vectors, model_name = await embed_documents_with_fallback(texts)

                for idx, (chunk_text, vector) in enumerate(zip(texts, vectors)):
                    chunk = DocChunks(
                        doc_id=doc_id,
                        chunk_index=idx,
                        content=chunk_text,
                        token_count=estimate_token_count(chunk_text),
                        chunk_metadata={"chunk_global_index": idx}
                    )
                    self.db.add(chunk)
                    await self.db.flush()

                    embedding = DocChunkEmbeddings(
                        chunk_id=chunk.chunk_id,
                        model=model_name,
                        embedding=json.dumps(vector)
                    )
                    self.db.add(embedding)

            await self.db.commit()

            state["doc_id"] = str(doc_id)
            state["status"] = "completed"

        except Exception as e:
            logger.error(f"Database save failed: {e}")
            await self.db.rollback()
            state["error"] = f"Failed to save to database: {str(e)}"
            state["status"] = "failed"

        return state

    async def run(
        self,
        source_type: str,
        source_path: str,
        space_id: int,
        user_id: int
    ) -> dict[str, Any]:
        """
        Run the data processing pipeline.

        Args:
            source_type: Type of source (minio, url, text, file)
            source_path: Path or content based on source_type
            space_id: Database ID of the space
            user_id: Database ID of the user

        Returns:
            Dict containing processing results
        """
        initial_state: DataProcessState = {
            "source_type": source_type,
            "source_path": source_path,
            "source_content": None,
            "extracted_text": None,
            "markdown_content": None,
            "chunks": [],
            "embedding_ids": [],
            "graph_nodes": 0,
            "doc_id": None,
            "status": "init",
            "error": None,
            "space_id": space_id,
            "user_id": user_id
        }

        try:
            result = await self.graph.ainvoke(initial_state)
            return {
                "success": result.get("status") == "completed",
                "doc_id": result.get("doc_id"),
                "chunks_count": len(result.get("chunks", [])),
                "graph_nodes": result.get("graph_nodes", 0),
                "status": result.get("status"),
                "error": result.get("error")
            }
        except Exception as e:
            logger.exception(f"DataProcessAgent error: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": "failed"
            }
