from __future__ import annotations

import datetime
import uuid
from typing import Any, TypedDict

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import DataAssets, DataLineageType, DataSensitivityLevel, Documents, Users
from app.services.base import SpaceAwareService, get_llm_client, preview_text
from app.services.graph.graph_service import KnowledgeGraphService
from app.services.lineage_service import LineageEventType, LineageService


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
            "data_type": asset.data_type,
            "sensitivity_level": asset.sensitivity_level.value if asset.sensitivity_level else None,
            "quality_overall_score": asset.quality_overall_score,
            "lineage_root": asset.lineage_root,
        }

    async def list_assets(self, space_public_id: str, user: Users):
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
    ):
        space = await self._require_space(space_public_id, user)
        docs = await self._list_docs(space.id)
        graph = await self.graph_service.get_graph(space_public_id, user)

        workflow = self._build_workflow()
        state: AssetWorkflowState = {
            "space_public_id": space_public_id,
            "prompt": (prompt or "").strip(),
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
        asset_id = uuid.uuid4().hex
        summary = preview_text(markdown_text, max_length=180)
        graph_snapshot = {
            "node_count": len(result.get("graph_nodes", [])),
            "edge_count": len(result.get("graph_edges", [])),
        }
        title = f"Knowledge Asset {now.isoformat()[:19]}"

        source_document_ids = [doc["doc_id"] for doc in docs]

        db_asset = DataAssets(
            asset_id=asset_id,
            owner_id=user.id,
            asset_name=title,
            asset_type="knowledge_report",
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
            is_available_for_trade=True,
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
                metadata={"generation_type": "knowledge_asset", "prompt": prompt or ""},
                transformation_logic="LLM-generated report from documents and knowledge graph",
            )

        for src_asset_id in (source_asset_ids or []):
            await lineage_service.record_lineage(
                entity_type=DataLineageType.ASSET,
                entity_id=asset_id,
                event_type=LineageEventType.DERIVED,
                source_entity_type=DataLineageType.ASSET,
                source_entity_id=src_asset_id,
                user_id=user.id,
                space_id=space_public_id,
                metadata={"generation_type": "knowledge_asset_derived"},
                transformation_logic="Derived knowledge asset from source assets",
            )

        return self._db_asset_to_dict(db_asset)

    async def _list_docs(self, space_db_id: int) -> list[dict[str, Any]]:
        q = await self.db.execute(
            select(Documents)
            .where(Documents.space_id == space_db_id)
            .order_by(Documents.updated_at.desc())
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
