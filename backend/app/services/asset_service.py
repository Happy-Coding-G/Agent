from __future__ import annotations

import datetime
import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ServiceError
from app.db.models import Documents, Users
from app.services.base import SpaceAwareService, get_llm_client, preview_text
from app.services.graph_service import KnowledgeGraphService
from app.utils.state_store import load_state, save_state


class AssetWorkflowState(TypedDict):
    space_public_id: str
    prompt: str
    docs: list[dict[str, Any]]
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    report_markdown: str


class AssetService(SpaceAwareService):
    """资产服务 - 继承 SpaceAwareService"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.graph_service = KnowledgeGraphService(db)

    def _load_assets(self, space_public_id: str) -> list[dict[str, Any]]:
        assets = load_state("assets", space_public_id, [])
        return assets if isinstance(assets, list) else []

    def _save_assets(self, space_public_id: str, items: list[dict[str, Any]]) -> None:
        save_state("assets", space_public_id, items)

    async def list_assets(self, space_public_id: str, user: Users):
        await self._require_space(space_public_id, user)
        assets = self._load_assets(space_public_id)
        return [
            {
                "asset_id": item.get("asset_id"),
                "title": item.get("title"),
                "created_at": item.get("created_at"),
                "summary": item.get("summary"),
            }
            for item in reversed(assets)
        ]

    async def get_asset(self, space_public_id: str, asset_id: str, user: Users):
        await self._require_space(space_public_id, user)
        assets = self._load_assets(space_public_id)
        for item in assets:
            if item.get("asset_id") == asset_id:
                return item
        raise ServiceError(404, "Asset not found")

    async def generate_asset(
        self, *, space_public_id: str, prompt: str | None, user: Users
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

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        asset_id = uuid.uuid4().hex
        summary = preview_text(markdown_text, max_length=180)
        record = {
            "asset_id": asset_id,
            "space_public_id": space_public_id,
            "title": f"Knowledge Asset {now[:19]}",
            "summary": summary,
            "created_at": now,
            "updated_at": now,
            "prompt": result.get("prompt") or "",
            "content_markdown": markdown_text,
            "graph_snapshot": {
                "node_count": len(result.get("graph_nodes", [])),
                "edge_count": len(result.get("graph_edges", [])),
            },
        }

        assets = self._load_assets(space_public_id)
        assets.append(record)
        self._save_assets(space_public_id, assets)
        return record

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
