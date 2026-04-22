from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.core.config import settings
from app.db.models import Documents, Users
from app.services.base import SpaceAwareService, preview_text
from app.utils.state_store import load_state, save_state


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _get_neo4j_driver():
    """获取 Neo4j 驱动"""
    try:
        from neo4j import GraphDatabase
        return GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
    except Exception:
        return None


class KnowledgeGraphService(SpaceAwareService):
    """知识图谱服务 - 继承 SpaceAwareService 获得 _require_space"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    def _load_graph_state(self, space_public_id: str) -> dict[str, Any]:
        state = load_state(
            "graphs", space_public_id, {"node_overrides": {}, "edges": []}
        )
        if not isinstance(state, dict):
            return {"node_overrides": {}, "edges": []}
        state.setdefault("node_overrides", {})
        state.setdefault("edges", [])
        return state

    def _save_graph_state(self, space_public_id: str, state: dict[str, Any]) -> None:
        save_state("graphs", space_public_id, state)

    async def _list_docs(self, space_db_id: int, limit: int = 200) -> list[Documents]:
        q = await self.db.execute(
            select(Documents)
            .where(Documents.space_id == space_db_id)
            .order_by(Documents.updated_at.desc())
            .limit(limit)
        )
        return q.scalars().all()

    async def _fetch_neo4j_graph(self, doc_ids: set[str], graph_ids: set[str] = None) -> tuple[list[dict], list[dict]]:
        """从 Neo4j 获取图谱数据"""
        driver = _get_neo4j_driver()
        if not driver:
            return [], []

        neo4j_nodes = []
        neo4j_edges = []

        # 如果没有传入 graph_ids，使用空的
        if graph_ids is None:
            graph_ids = set()

        try:
            with driver.session(database=settings.NEO4J_DATABASE) as session:
                # 查询所有实体（使用 graph_id 或 doc_id 过滤）
                # 优先使用 graph_id 过滤
                if graph_ids:
                    result = session.run('''
                        MATCH (e) WHERE e.graph_id IN $graph_ids
                        RETURN e.name as name,
                               labels(e) as labels,
                               e.description as description,
                               e.doc_id as doc_id,
                               e.graph_id as graph_id,
                               e.attributes as attributes
                        LIMIT 500
                    ''', graph_ids=list(graph_ids))
                elif doc_ids:
                    result = session.run('''
                        MATCH (e) WHERE e.doc_id IN $doc_ids
                        RETURN e.name as name,
                               labels(e) as labels,
                               e.description as description,
                               e.doc_id as doc_id,
                               e.graph_id as graph_id,
                               e.attributes as attributes
                        LIMIT 500
                    ''', doc_ids=list(doc_ids))
                else:
                    result = None

                entity_id_map = {}  # 用于构建关系

                for record in result:
                    attrs = record.get("attributes", "{}")
                    if isinstance(attrs, str):
                        try:
                            import json
                            attrs = json.loads(attrs)
                        except:
                            attrs = {}

                    name = record.get("name", "") or "Unknown"
                    doc_id = record.get("doc_id", "")
                    graph_id = record.get("graph_id", "")

                    # 为实体创建唯一ID（使用 name 作为标识）
                    entity_id = f"entity:{graph_id}:{name}"

                    labels = record.get("labels", [])
                    if isinstance(labels, list):
                        primary_label = labels[0] if labels else "Entity"
                    else:
                        primary_label = "Entity"

                    # 从 attributes 提取 tags
                    tags = []
                    if isinstance(attrs, dict):
                        role = attrs.get("role", "")
                        if role:
                            tags.append(role)

                    neo4j_nodes.append({
                        "doc_id": entity_id,  # 使用 entity ID
                        "name": name,
                        "label": name,  # 使用 name 作为 label
                        "labels": labels,
                        "description": record.get("description", "") or name,
                        "graph_id": graph_id,
                        "attributes": attrs,
                        "node_type": "entity",
                        "tags": tags,
                        "status": "completed",
                    })

                    # 记录 entity_id 和原始 doc_id 的映射
                    entity_id_map[(doc_id, name)] = entity_id

                # 查询所有关系
                rel_result = session.run('''
                    MATCH (a)-[r]->(b)
                    WHERE a.name IS NOT NULL AND b.name IS NOT NULL
                    RETURN a.name as source_name,
                           b.name as target_name,
                           a.doc_id as source_doc_id,
                           b.doc_id as target_doc_id,
                           a.graph_id as source_graph_id,
                           b.graph_id as target_graph_id,
                           r.type as relation_type,
                           r.fact as fact,
                           r.confidence as confidence,
                           r.polarity as polarity,
                           r.qualifiers as qualifiers,
                           r.attributes as attributes
                    LIMIT 1000
                ''')

                for record in rel_result:
                    attrs = record.get("attributes", "{}")
                    qualifiers = record.get("qualifiers", "{}")
                    if isinstance(attrs, str):
                        try:
                            import json
                            attrs = json.loads(attrs) if attrs else {}
                            qualifiers = json.loads(qualifiers) if qualifiers else {}
                        except:
                            attrs = {}
                            qualifiers = {}

                    source_name = record.get("source_name", "")
                    target_name = record.get("target_name", "")
                    source_doc_id = record.get("source_doc_id", "")
                    target_doc_id = record.get("target_doc_id", "")
                    source_graph_id = record.get("source_graph_id", "")
                    target_graph_id = record.get("target_graph_id", "")

                    # 使用 entity ID
                    source_entity_id = f"entity:{source_graph_id}:{source_name}"
                    target_entity_id = f"entity:{target_graph_id}:{target_name}"

                    neo4j_edges.append({
                        "edge_id": f"rel:{source_graph_id}:{source_name}:{target_name}",
                        "source_doc_id": source_entity_id,
                        "target_doc_id": target_entity_id,
                        "source_name": source_name,
                        "target_name": target_name,
                        "relation_type": record.get("relation_type", "RELATES"),
                        "description": record.get("fact", "") or record.get("relation_type", "RELATES"),
                        "fact": record.get("fact", ""),
                        "confidence": float(record.get("confidence", 1.0)) if record.get("confidence") else 1.0,
                        "polarity": int(record.get("polarity", 1)) if record.get("polarity") else 1,
                        "qualifiers": qualifiers,
                        "attributes": attrs,
                        "edge_type": "entity_relation",
                        "created_at": _now_iso(),
                        "updated_at": _now_iso(),
                    })

        except Exception as e:
            import logging
            logging.warning(f"[GraphService] Neo4j query failed: {e}")
        finally:
            driver.close()

        return neo4j_nodes, neo4j_edges

    async def get_graph(self, space_public_id: str, user: Users):
        space_db_id = await self._require_space(space_public_id, user)
        docs = await self._list_docs(space_db_id)
        doc_map = {str(doc.doc_id): doc for doc in docs}
        state = self._load_graph_state(space_public_id)
        overrides = state.get("node_overrides", {})
        edges = state.get("edges", [])

        nodes = []
        for doc_id, doc in doc_map.items():
            override = overrides.get(doc_id, {}) if isinstance(overrides, dict) else {}
            label = override.get("label") or doc.title or f"Document {doc_id[:8]}"
            description = override.get("description") or preview_text(doc.markdown_text)
            tags = override.get("tags") or []
            nodes.append(
                {
                    "doc_id": doc_id,
                    "label": label,
                    "description": description,
                    "tags": tags if isinstance(tags, list) else [],
                    "status": doc.status,
                    "updated_at": doc.updated_at,
                    "node_type": "document",
                }
            )

        valid_doc_ids = set(doc_map.keys())
        sanitized_edges = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("source_doc_id", ""))
            tgt = str(edge.get("target_doc_id", ""))
            if (src in valid_doc_ids) and (tgt in valid_doc_ids):
                sanitized_edges.append({
                    **edge,
                    "edge_type": "document_relation",
                })

        if len(sanitized_edges) != len(edges):
            state["edges"] = sanitized_edges
            self._save_graph_state(space_public_id, state)

        # 提取 graph_ids
        graph_ids = {str(doc.graph_id) for doc in docs if doc.graph_id}
        # 从 Neo4j 获取实体和关系
        neo4j_nodes, neo4j_edges = await self._fetch_neo4j_graph(valid_doc_ids, graph_ids)

        # 添加实体节点（标记为 entity 类型）
        for node in neo4j_nodes:
            nodes.append({
                "doc_id": node.get("doc_id", ""),
                "name": node.get("name", ""),
                "label": node.get("label", node.get("name", "Entity")),
                "labels": node.get("labels", ["Entity"]),
                "description": node.get("description", ""),
                "graph_id": node.get("graph_id", ""),
                "attributes": node.get("attributes", {}),
                "node_type": "entity",
                "tags": node.get("tags", []),
                "status": node.get("status", "completed"),
                "updated_at": _now_iso(),
            })

        # 添加实体关系（标记为 entity_relation 类型）
        for edge in neo4j_edges:
            sanitized_edges.append({
                "edge_id": edge.get("edge_id", ""),
                "source_doc_id": edge.get("source_doc_id", ""),
                "target_doc_id": edge.get("target_doc_id", ""),
                "source_name": edge.get("source_name", ""),
                "target_name": edge.get("target_name", ""),
                "relation_type": edge.get("relation_type", "RELATES"),
                "description": edge.get("description", ""),
                "fact": edge.get("fact", ""),
                "confidence": edge.get("confidence", 1.0),
                "polarity": edge.get("polarity", 1),
                "qualifiers": edge.get("qualifiers", {}),
                "attributes": edge.get("attributes", {}),
                "edge_type": "entity_relation",
                "created_at": edge.get("created_at", _now_iso()),
                "updated_at": edge.get("updated_at", _now_iso()),
            })

        return {"nodes": nodes, "edges": sanitized_edges}

    async def update_node(
        self,
        *,
        space_public_id: str,
        doc_id: str,
        label: str | None,
        description: str | None,
        tags: list[str] | None,
        user: Users,
    ):
        space_db_id = await self._require_space(space_public_id, user)
        doc = await self._get_doc(space_db_id, doc_id)

        state = self._load_graph_state(space_public_id)
        overrides = state.setdefault("node_overrides", {})
        current = overrides.get(doc_id, {}) if isinstance(overrides, dict) else {}
        current = current if isinstance(current, dict) else {}

        if label is not None:
            current["label"] = label
            doc.title = label or doc.title
        if description is not None:
            current["description"] = description
        if tags is not None:
            current["tags"] = tags

        current["updated_at"] = _now_iso()
        overrides[doc_id] = current
        self._save_graph_state(space_public_id, state)
        await self.db.commit()

        return {"doc_id": doc_id, **current}

    async def create_edge(
        self,
        *,
        space_public_id: str,
        source_doc_id: str,
        target_doc_id: str,
        relation_type: str,
        description: str | None,
        user: Users,
    ):
        space_db_id = await self._require_space(space_public_id, user)
        await self._get_doc(space_db_id, source_doc_id)
        await self._get_doc(space_db_id, target_doc_id)

        state = self._load_graph_state(space_public_id)
        edges = state.setdefault("edges", [])

        edge = {
            "edge_id": uuid.uuid4().hex,
            "source_doc_id": source_doc_id,
            "target_doc_id": target_doc_id,
            "relation_type": relation_type,
            "description": description or "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        edges.append(edge)
        self._save_graph_state(space_public_id, state)
        return edge

    async def update_edge(
        self,
        *,
        space_public_id: str,
        edge_id: str,
        relation_type: str | None,
        description: str | None,
        user: Users,
    ):
        await self._require_space(space_public_id, user)
        state = self._load_graph_state(space_public_id)
        edges = state.get("edges", [])
        if not isinstance(edges, list):
            raise ServiceError(500, "Graph storage is corrupted")

        for edge in edges:
            if edge.get("edge_id") != edge_id:
                continue
            if relation_type is not None:
                edge["relation_type"] = relation_type
            if description is not None:
                edge["description"] = description
            edge["updated_at"] = _now_iso()
            self._save_graph_state(space_public_id, state)
            return edge
        raise ServiceError(404, "Edge not found")

    async def delete_edge(self, *, space_public_id: str, edge_id: str, user: Users):
        await self._require_space(space_public_id, user)
        state = self._load_graph_state(space_public_id)
        edges = state.get("edges", [])
        if not isinstance(edges, list):
            raise ServiceError(500, "Graph storage is corrupted")

        kept = [edge for edge in edges if edge.get("edge_id") != edge_id]
        if len(kept) == len(edges):
            raise ServiceError(404, "Edge not found")

        state["edges"] = kept
        self._save_graph_state(space_public_id, state)
        return {"status": "OK"}

    async def _get_doc(self, space_db_id: int, doc_id: str) -> Documents:
        try:
            doc_uuid = uuid.UUID(doc_id)
        except ValueError as exc:
            raise ServiceError(400, "Invalid doc_id") from exc

        q = await self.db.execute(
            select(Documents).where(
                Documents.space_id == space_db_id, Documents.doc_id == doc_uuid
            )
        )
        doc = q.scalars().first()
        if not doc:
            raise ServiceError(404, "Document node not found")
        return doc
