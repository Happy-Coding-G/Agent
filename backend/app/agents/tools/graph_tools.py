"""
Graph Tools - 包装 KnowledgeGraphService
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class GraphManageInput(BaseModel):
    action: str = Field(description="操作类型: get, update_node, create_edge, update_edge, delete_edge")
    space_id: str = Field(description="空间public_id")
    doc_id: Optional[str] = Field(None, description="文档/节点ID")
    edge_id: Optional[str] = Field(None, description="边ID")
    label: Optional[str] = Field(None, description="节点标签")
    description: Optional[str] = Field(None, description="描述")
    tags: Optional[List[str]] = Field(None, description="节点标签列表")
    source_doc_id: Optional[str] = Field(None, description="源节点ID")
    target_doc_id: Optional[str] = Field(None, description="目标节点ID")
    relation_type: Optional[str] = Field(None, description="关系类型")


def build_tools(registry: "AgentToolRegistry") -> List[StructuredTool]:
    db = registry.db
    user = registry.user

    async def graph_manage(
        action: str,
        space_id: str,
        doc_id: Optional[str] = None,
        edge_id: Optional[str] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source_doc_id: Optional[str] = None,
        target_doc_id: Optional[str] = None,
        relation_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.graph.graph_service import KnowledgeGraphService
        from app.core.errors import ServiceError
        service = KnowledgeGraphService(db)

        try:
            if action == "get":
                graph = await service.get_graph(space_id, user)
                return {"success": True, "graph": graph}
            elif action == "update_node":
                if not doc_id:
                    return {"success": False, "error": "doc_id is required"}
                result = await service.update_node(
                    space_public_id=space_id,
                    doc_id=doc_id,
                    label=label,
                    description=description,
                    tags=tags,
                    user=user,
                )
                return {"success": True, "node": result}
            elif action == "create_edge":
                if not source_doc_id or not target_doc_id:
                    return {"success": False, "error": "source_doc_id and target_doc_id are required"}
                result = await service.create_edge(
                    space_public_id=space_id,
                    source_doc_id=source_doc_id,
                    target_doc_id=target_doc_id,
                    relation_type=relation_type or "related_to",
                    description=description,
                    user=user,
                )
                return {"success": True, "edge": result}
            elif action == "update_edge":
                if not edge_id:
                    return {"success": False, "error": "edge_id is required"}
                result = await service.update_edge(
                    space_public_id=space_id,
                    edge_id=edge_id,
                    relation_type=relation_type,
                    description=description,
                    user=user,
                )
                return {"success": True, "edge": result}
            elif action == "delete_edge":
                if not edge_id:
                    return {"success": False, "error": "edge_id is required"}
                result = await service.delete_edge(
                    space_public_id=space_id,
                    edge_id=edge_id,
                    user=user,
                )
                return {"success": True, "result": result}
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except ServiceError as e:
            return {"success": False, "error": e.detail, "status_code": e.status_code}
        except Exception as e:
            logger.exception(f"graph_manage failed: {e}")
            return {"success": False, "error": str(e)}

    return [
        StructuredTool.from_function(
            name="graph_manage",
            func=graph_manage,
            description="管理知识图谱（获取图谱、更新节点、创建/更新/删除边）",
            args_schema=GraphManageInput,
            coroutine=graph_manage,
        ),
    ]
