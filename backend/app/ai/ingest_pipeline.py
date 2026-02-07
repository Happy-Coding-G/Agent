import asyncio
import datetime
import tempfile
from pathlib import Path
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Documents, IngestJobs, DocChunks, DocChunkEmbeddings
from app.utils.MinIO import minio_service


class LangChainIngestPipeline:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self, ingest_id):
        job = await self._get_job(ingest_id)
        if not job:
            return
        doc = job.document

        try:
            await self._mark_job_running(job, doc)

            # 从 MinIO 下载文件到临时目录
            source_url = doc.source_url
            file_bytes, filename = await self._download_file(source_url, doc.object_key)

            # 提取原始内容
            with tempfile.TemporaryDirectory() as temdir:
                file_path = Path(temdir)/filename
                file_path.write_bytes(file_bytes)
                raw_text = await asyncio.to_thread(self._extract_text, file_path)

            # 使用 LLM 将文本转化为干净的 Markdown 文档
            markdown_text = await self._convert_to_markdown(raw_text)
            markdown_key = doc.markdown_object_key or f"{doc.object_key}.md"
            minio_service.upload_text(markdown_key, markdown_text)

            # 更新文档元数据
            doc.markdown_object_key = markdown_key
            doc.markdown_text = markdown_text
            doc.status = "processing"
            await self.db.commit()

            # 语义切分
            chunk_docs = await self._semamtic_chunk(markdown_text)

            # 生成向量并存入 PGVector (或对应向量库)
            await self._store_chunks_and_embeddings(doc, chunk_docs)

            # 提取实体和关系构建 Neo4j 知识图谱
            await self._build_graph(doc, chunk_docs)

            doc.status = "completed"
            job.status = "succeeded"
            job.finished_at = datetime.datetime.now(datetime.timezone.utc)
            await self.db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.datetime.now(datetime.timezone.utc)
            if doc:
                doc.status = "failed"
            await self.db.commit()


    async def _get_job(self, ingest_id):
        # 从数据库获取摄取任务对象，并预加载关联的 Document 对象
        res = await self.db.execute(
            select(IngestJobs)
            .options(selectinload(IngestJobs.document))
            .where(IngestJobs.ingest_id == ingest_id)
        )

        return res.scalars().first()


    async def _mark_job_running(self, job: IngestJobs, doc: Documents):
        # 更新任务和文档的状态为 '正在运行/处理中'。
        job.status = "running"
        job.started_at = datetime.datetime.now(datetime.timezone.utc)
        doc.status = "processing"
        await self.db.commit()


    async def _download_file(self, source_url: str, object_key: str | None):
        # 使用 httpx 异步下载文件内容
        try:
            import httpx
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("httpx is required to download files") from exc

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            content_disposition = resp.headers.get("content-disposition", "")
            filename = self._filename_from_headers(content_disposition, object_key)
            return resp.content, filename


    def _filename_from_headers(self, content_disposition: str, object_key: str | None):
        # 辅助函数：尝试从 HTTP 头或对象 Key 中解析出文件名。
        if "filename=" in content_disposition:
            return content_disposition.split("filename=", 1)[1].strip('" ')
        if object_key:
            return Path(object_key).name
        return "uploaded_file"


    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()

        if suffix == '.pdf':
            try:
                from langchain_community.document_loaders import PyPDFLoader
            except Exception as exc:
                raise RuntimeError("PyPDFLoader requires langchain_community and pypdf") from exc
            loader = PyPDFLoader(str(file_path))
        elif suffix in {'.docx', '.doc'}:
            try:
                from langchain_community.document_loaders import Docx2txtLoader
            except Exception as exc:
                raise RuntimeError("Docx2txtLoader requires langchain_community and docx2txt") from exc
            loader = Docx2txtLoader(str(file_path))
        else:
            try:
                from langchain_community.document_loaders import TextLoader
            except Exception as exc:
                raise RuntimeError("TextLoader requires langchain_community") from exc
            loader = TextLoader(str(file_path), encoding="utf-8")

        docs = loader.load()
        return "\n\n".join(d.page_content for d in docs)


    async def _convert_to_markdown(self, raw_text: str) -> str:
        # 调用 LLM 将杂乱的 raw_text 整理为结构清晰的 Markdown 格式
        llm = self._get_llm()

        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except Exception as e:
            raise

        splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=200)
        parts = splitter.split_text(raw_text)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a formatter. Convert the input into clean Markdown, "
                    "preserving headings, lists, tables, and code blocks when present.",
                ),
                ("human", "{content}")
            ]
        )

        chain = prompt | llm | StrOutputParser()

        rendered: List[str] = []
        for part in parts:
            rendered.append(await chain.ainvoke({"content": part}))
        return "\n\n".join(rendered).strip()


    async def _semamtic_chunk(self, markdown_text: str):
        """
        使用 LangChain Experimental 的 SemanticChunker 对 Markdown 进行语义切分。
        相比固定字符数切分，这能更好地保持上下文完整性。
        """
        embeddings = self._get_embeddings()
        try:
            from langchain_experimental.text_splitter import SemanticChunker
            from langchain_core.documents import Document as LCDocument
        except Exception as exc:
            raise RuntimeError("langchain_experimental is required for semantic chunking") from exc

        splitter = SemanticChunker(embeddings)
        docs = await asyncio.to_thread(splitter.create_documents, [markdown_text])
        return [LCDocument(page_content=d.page_content, metadata=d.metadata) for d in docs]


    async def _store_chunks_and_embeddings(self, doc: Documents, chunk_docs):
        """
        1. 计算切片文本的向量 (Embeddings)。
        2. 将切片内容 (Chunk) 和向量 (Vector) 存入数据库。
        """
        embeddings = self._get_embeddings()
        texts = [d.page_content for d in chunk_docs]
        vectors = await embeddings.aembed_documents(texts)

        for idx, (chunk_doc, vector) in enumerate(zip(chunk_docs, vectors, strict=True)):
            # 存储 Chunk 文本信息
            chunk = DocChunks(
                doc_id=doc.doc_id,
                chunk_index=idx,
                content=chunk_doc.page_content,
                section_path=chunk_doc.metadata.get("section_path") if chunk_doc.metadata else None,
                chunk_metadata=chunk_doc.metadata or None,
            )
            self.db.add(chunk)
            await self.db.flush()  # 刷新以获取生成的 ID

            # 存储向量数据
            embedding = DocChunkEmbeddings(
                chunk_id=chunk.chunk_id,
                model=settings.OPENAI_EMBEDDING_MODEL,
                embedding=vector,
            )
            self.db.add(embedding)

        await self.db.commit()


    async def _build_graph(self, doc: Documents, chunk_docs):
        """
        (GraphRAG) 使用 LLM 从切片中抽取实体和关系，构建 Neo4j 知识图谱。
        """
        if not settings.NEO4J_URI:
            return

        try:
            from langchain_community.graphs import Neo4jGraph
            from langchain_experimental.graph_transformers import LLMGraphTransformer
        except Exception as exc:
            raise RuntimeError(
                "langchain_community and langchain_experimental are required for graph building") from exc

        llm = self._get_llm()
        graph = Neo4jGraph(
            url=settings.NEO4J_URI,
            username=settings.NEO4J_USER,
            password=None,
            database=settings.NEO4J_DATABASE,
        )
        transformer = LLMGraphTransformer(llm=llm)

        # 转换文档为图结构（节点+关系）
        graph_docs = await asyncio.to_thread(transformer.convert_to_graph_documents, chunk_docs)
        for graph_doc in graph_docs:
            self._tag_graph_document(graph_doc, doc)  # 为节点打上文档来源标签
        graph.add_graph_documents(graph_docs)


    def _tag_graph_document(self, graph_doc, doc: Documents):
        """
        辅助函数：给图中的每个节点和关系添加 'doc_id' 和 'graph_id' 属性，以便追踪来源。
        """
        for node in getattr(graph_doc, "nodes", []):
            node.properties = node.properties or {}
            node.properties["graph_id"] = str(doc.graph_id)
            node.properties["doc_id"] = str(doc.doc_id)
        for rel in getattr(graph_doc, "relationships", []):
            rel.properties = rel.properties or {}
            rel.properties["graph_id"] = str(doc.graph_id)
            rel.properties["doc_id"] = str(doc.doc_id)


    def _get_llm(self):
        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError("langchain_openai is required for LLM usage") from exc

        kwargs = {
            "model" : settings.DEEPSEEK_MODEL,
            "temperature": 0.2,
            "api_key": settings.DEEPSEEK_API_KEY,
            "base_url": settings.DEEPSEEK_BASE_URL,
        }

        return ChatOpenAI(**kwargs)


    def _get_embeddings(self):
        try:
            from langchain_openai import OpenAIEmbeddings
        except Exception as exc:
            raise RuntimeError("langchain_openai is required for embeddings") from exc

        kwargs = {
            "model": settings.QWEN_EMBEDDING,
            "api_key": settings.QWEN_API_KEY,
            "base_url": settings.QWEN_BASE_URL,
            "temperature": 0.1,
        }

        return OpenAIEmbeddings(**kwargs)
