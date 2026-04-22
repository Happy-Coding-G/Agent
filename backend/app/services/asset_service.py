from __future__ import annotations

import datetime
import logging
import math
import uuid
from typing import Any, TypedDict

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_client import embed_query_with_fallback
from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import (
    DataAssets,
    DataLineageType,
    DataRightsStatus,
    DataRightsTransactions,
    DataSensitivityLevel,
    DocChunkEmbeddings,
    DocChunks,
    Documents,
    Users,
)
from app.services.base import SpaceAwareService, get_llm_client, preview_text
from app.services.graph.graph_service import KnowledgeGraphService
from app.services.lineage_service import LineageEventType, LineageService

logger = logging.getLogger(__name__)


class AssetWorkflowState(TypedDict):
    space_public_id: str
    prompt: str
    docs: list[dict[str, Any]]
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    report_markdown: str


class AssetService(SpaceAwareService):
    """资产服务 - 继承 SpaceAwareService，统一使用 data_assets 表"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.graph_service = KnowledgeGraphService(db)

    def _db_asset_to_dict(self, asset: DataAssets) -> dict[str, Any]:
        return {
            "asset_id": asset.asset_id,
            "space_public_id": asset.space_public_id or "",
            "title": asset.asset_name,
            "summary": asset.content_summary or "",
            "created_at": asset.created_at.isoformat() if asset.created_at else "",
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else "",
            "prompt": asset.generation_prompt or "",
            "content_markdown": asset.content_markdown or "",
            "graph_snapshot": asset.graph_snapshot or {},
            "asset_type": asset.asset_type,
            "asset_origin": asset.asset_origin,
            "asset_status": asset.asset_status,
            "data_type": asset.data_type,
            "sensitivity_level": asset.sensitivity_level.value
            if asset.sensitivity_level
            else None,
            "quality_overall_score": asset.quality_overall_score,
            "lineage_root": asset.lineage_root,
            "source_asset_ids": asset.source_asset_ids or [],
        }

    async def list_assets(
        self,
        space_public_id: str,
        user: Users,
        limit: int = 100,
        offset: int = 0,
    ):
        await self._require_space(space_public_id, user)

        result = await self.db.execute(
            select(DataAssets)
            .where(
                and_(
                    DataAssets.space_public_id == space_public_id,
                    DataAssets.owner_id == user.id,
                )
            )
            .order_by(DataAssets.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        db_assets = result.scalars().all()

        return [
            {
                "asset_id": a.asset_id,
                "title": a.asset_name,
                "created_at": a.created_at.isoformat() if a.created_at else "",
                "summary": a.content_summary or "",
            }
            for a in db_assets
        ]

    async def get_asset(self, space_public_id: str, asset_id: str, user: Users):
        await self._require_space(space_public_id, user)

        result = await self.db.execute(
            select(DataAssets).where(
                and_(
                    DataAssets.asset_id == asset_id,
                    DataAssets.owner_id == user.id,
                )
            )
        )
        db_asset = result.scalar_one_or_none()
        if db_asset:
            return self._db_asset_to_dict(db_asset)

        raise ServiceError(404, "Asset not found")

    async def generate_asset(
        self,
        *,
        space_public_id: str,
        prompt: str | None,
        user: Users,
        source_asset_ids: list[str] | None = None,
        asset_origin: str = "space_generated",
    ):
        space = await self._require_space(space_public_id, user)

        # 1. 智能文档筛选：根据 prompt 提取关键词，召回相关文档
        query = (prompt or "").strip()
        if query:
            docs = await self._select_relevant_docs(space.id, query)
        else:
            docs = await self._list_docs(space.id)

        graph = await self.graph_service.get_graph(space_public_id, user)

        workflow = self._build_workflow()
        state: AssetWorkflowState = {
            "space_public_id": space_public_id,
            "prompt": query,
            "docs": docs,
            "graph_nodes": graph.get("nodes", []),
            "graph_edges": graph.get("edges", []),
            "report_markdown": "",
        }
        result = await workflow.ainvoke(state)

        markdown_text = (result.get("report_markdown") or "").strip()
        if not markdown_text:
            raise ServiceError(500, "Asset generation returned empty content")

        now = datetime.datetime.now(datetime.timezone.utc)
        summary = preview_text(markdown_text, max_length=180)
        graph_snapshot = {
            "node_count": len(result.get("graph_nodes", [])),
            "edge_count": len(result.get("graph_edges", [])),
        }
        source_document_ids = [doc["doc_id"] for doc in docs]

        # 2. 检查来源资产的 derivative_right（如果来源资产非用户自有）
        if source_asset_ids:
            await self._verify_derivative_rights(user, source_asset_ids)

        # 3. 总是创建新的数字资产记录（不再 upsert）
        asset_status = "awaiting_listing_confirmation" if asset_origin == "chat_generated" else "draft"
        asset_id = uuid.uuid4().hex
        db_asset = DataAssets(
            asset_id=asset_id,
            owner_id=user.id,
            asset_name=f"Knowledge Asset {now.isoformat()[:19]}",
            asset_type="knowledge_report",
            asset_origin=asset_origin,
            asset_status=asset_status,
            data_type="knowledge_report",
            sensitivity_level=DataSensitivityLevel.MEDIUM,
            content_markdown=markdown_text,
            content_summary=summary,
            graph_snapshot=graph_snapshot,
            generation_prompt=result.get("prompt") or "",
            space_public_id=space_public_id,
            source_document_ids=source_document_ids,
            source_asset_ids=source_asset_ids or [],
            raw_data_source="space_documents_and_knowledge_graph",
            storage_location=f"db://data_assets/{asset_id}",
            is_available_for_trade=False,
        )
        self.db.add(db_asset)
        await self.db.commit()
        await self.db.refresh(db_asset)

        lineage_service = LineageService(self.db)

        for doc_id in source_document_ids:
            await lineage_service.record_lineage(
                entity_type=DataLineageType.KNOWLEDGE,
                entity_id=asset_id,
                event_type=LineageEventType.DERIVED,
                source_entity_type=DataLineageType.FILE,
                source_entity_id=str(doc_id),
                user_id=user.id,
                space_id=space_public_id,
                metadata={
                    "generation_type": "knowledge_asset",
                    "prompt": prompt or "",
                    "operation": "create",
                },
                transformation_logic="LLM-generated report from documents and knowledge graph",
            )

        for src_asset_id in source_asset_ids or []:
            await lineage_service.record_lineage(
                entity_type=DataLineageType.ASSET,
                entity_id=asset_id,
                event_type=LineageEventType.DERIVED,
                source_entity_type=DataLineageType.ASSET,
                source_entity_id=src_asset_id,
                user_id=user.id,
                space_id=space_public_id,
                metadata={
                    "generation_type": "knowledge_asset_derived",
                    "operation": "create",
                },
                transformation_logic="Derived knowledge asset from source assets",
            )

        return self._db_asset_to_dict(db_asset)

    async def _verify_derivative_rights(
        self,
        user: Users,
        source_asset_ids: list[str],
    ) -> None:
        """验证用户对来源资产拥有 derivative_right。"""
        now = datetime.datetime.now(datetime.timezone.utc)
        for src_id in source_asset_ids:
            result = await self.db.execute(
                select(DataAssets).where(DataAssets.asset_id == src_id)
            )
            src_asset = result.scalar_one_or_none()
            if not src_asset:
                raise ServiceError(404, f"Source asset not found: {src_id}")

            # 自己拥有的资产无需额外权限
            if src_asset.owner_id == user.id:
                continue

            # 检查所有活跃权益交易中是否有包含 derivative_right 的
            txs_result = await self.db.execute(
                select(DataRightsTransactions)
                .where(
                    and_(
                        DataRightsTransactions.buyer_id == user.id,
                        DataRightsTransactions.data_asset_id == src_id,
                        DataRightsTransactions.status == DataRightsStatus.ACTIVE,
                        DataRightsTransactions.valid_from <= now,
                        DataRightsTransactions.valid_until >= now,
                    )
                )
            )
            transactions = list(txs_result.scalars().all())
            has_derivative = any(
                "derivative_right" in (tx.rights_types or [])
                for tx in transactions
            )
            if not has_derivative:
                raise ServiceError(
                    403,
                    f"No derivative_right for source asset: {src_id}",
                )

    async def _list_docs(self, space_db_id: int, limit: int = 200) -> list[dict[str, Any]]:
        q = await self.db.execute(
            select(Documents)
            .where(Documents.space_id == space_db_id)
            .order_by(Documents.updated_at.desc())
            .limit(limit)
        )
        docs = q.scalars().all()
        result = []
        for doc in docs:
            text = (doc.markdown_text or "").strip()
            result.append(
                {
                    "doc_id": str(doc.doc_id),
                    "title": doc.title or f"Document {str(doc.doc_id)[:8]}",
                    "status": doc.status,
                    "markdown_preview": text[:1200],
                }
            )
        return result

    async def _select_relevant_docs(
        self,
        space_db_id: int,
        query: str,
        top_k_docs: int = 10,
    ) -> list[dict[str, Any]]:
        """
        基于查询向量与文档 chunk 的相似度，智能筛选相关文档。

        策略：
        1. 将 query 转为 embedding
        2. 获取空间内所有 chunk 及其 embeddings
        3. 计算 cosine similarity，取 top chunks
        4. 按 doc_id 聚合，返回最相关的 N 个文档
        """
        docs = await self._list_docs(space_db_id)
        if not docs:
            return []

        try:
            query_vector, _ = await embed_query_with_fallback(query)
        except Exception as e:
            logger.warning(f"Failed to embed query for asset doc filtering: {e}")
            return docs

        if not query_vector:
            return docs

        # 截断/填充到 1536 维（与数据库存储一致）
        target_dim = 1536
        actual_dim = len(query_vector)
        if actual_dim != target_dim:
            if actual_dim > target_dim:
                query_vector = query_vector[:target_dim]
            else:
                query_vector = query_vector + [0.0] * (target_dim - actual_dim)

        stmt = (
            select(DocChunks, DocChunkEmbeddings, Documents)
            .join(DocChunkEmbeddings, DocChunkEmbeddings.chunk_id == DocChunks.chunk_id)
            .join(Documents, Documents.doc_id == DocChunks.doc_id)
            .where(Documents.space_id == space_db_id)
        )
        rows = (await self.db.execute(stmt)).all()

        if not rows:
            return docs

        def _cosine_similarity(a: list[float], b: list[float]) -> float:
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(y * y for y in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        def _to_float_list(value: Any) -> list[float]:
            if value is None:
                return []
            if isinstance(value, list):
                return [float(x) for x in value]
            if isinstance(value, tuple):
                return [float(x) for x in value]
            if isinstance(value, str):
                text = value.strip().strip("[]")
                if not text:
                    return []
                try:
                    return [float(piece.strip()) for piece in text.split(",")]
                except ValueError:
                    return []
            try:
                return [float(x) for x in value]
            except Exception:
                return []

        scored_chunks: list[tuple[float, str]] = []
        for chunk, embedding_row, doc in rows:
            vector = _to_float_list(embedding_row.embedding)
            if not vector or len(vector) != len(query_vector):
                continue
            score = _cosine_similarity(query_vector, vector)
            scored_chunks.append((score, str(doc.doc_id)))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        relevant_doc_ids: list[str] = []
        seen: set[str] = set()
        for score, doc_id in scored_chunks:
            if doc_id not in seen:
                seen.add(doc_id)
                relevant_doc_ids.append(doc_id)
                if len(relevant_doc_ids) >= top_k_docs:
                    break

        doc_map = {doc["doc_id"]: doc for doc in docs}
        filtered = [doc_map[doc_id] for doc_id in relevant_doc_ids if doc_id in doc_map]

        return filtered if filtered else docs

    def _build_workflow(self):
        from langgraph.graph import END, StateGraph

        builder = StateGraph(AssetWorkflowState)
        builder.add_node("collect_context", self._collect_context_node)
        builder.add_node("generate_report", self._generate_report_node)
        builder.add_edge("collect_context", "generate_report")
        builder.add_edge("generate_report", END)
        builder.set_entry_point("collect_context")
        return builder.compile()

    async def _collect_context_node(
        self, state: AssetWorkflowState
    ) -> AssetWorkflowState:
        docs = state.get("docs", [])
        nodes = state.get("graph_nodes", [])
        edges = state.get("graph_edges", [])

        hint = state.get("prompt") or "Generate a concise personal asset report."
        state["prompt"] = hint
        state["docs"] = docs
        state["graph_nodes"] = nodes
        state["graph_edges"] = edges
        return state

    async def _generate_report_node(
        self, state: AssetWorkflowState
    ) -> AssetWorkflowState:
        llm = get_llm_client(temperature=0.3)
        docs_preview = "\n".join(
            [
                f"- {item.get('title')} ({item.get('doc_id')}): {item.get('markdown_preview', '')[:240]}"
                for item in state.get("docs", [])[:24]
            ]
        )
        edge_preview = "\n".join(
            [
                f"- {edge.get('source_doc_id')} -> {edge.get('target_doc_id')} ({edge.get('relation_type')})"
                for edge in state.get("graph_edges", [])[:40]
            ]
        )

        prompt = (
            "You are an assistant that organizes a user's knowledge assets.\n"
            "Create a markdown report with sections:\n"
            "1) Overview\n2) Key Knowledge Domains\n3) Important Document Nodes\n4) Relationship Insights\n5) Recommended Next Actions.\n"
            "Keep it practical and concise in Chinese.\n\n"
            f"User instruction:\n{state.get('prompt')}\n\n"
            f"Document snippets:\n{docs_preview or '(none)'}\n\n"
            f"Graph relations:\n{edge_preview or '(none)'}\n"
        )
        resp = await llm.ainvoke(prompt)
        content = resp.content if hasattr(resp, "content") else str(resp)
        state["report_markdown"] = content if isinstance(content, str) else str(content)
        return state
