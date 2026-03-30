from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.core.errors import ServiceError
from app.db.models import Users
from app.db.session import get_db
from app.schemas.schemas import (
    GraphDataResponse,
    GraphEdgeCreateRequest,
    GraphEdgePayload,
    GraphEdgeUpdateRequest,
    GraphNodeUpdateRequest,
)
from app.services.graph import KnowledgeGraphService

router = APIRouter(prefix="/spaces/{space_id}/graph", tags=["Knowledge Graph"])


@router.get("", response_model=GraphDataResponse)
async def get_graph(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await KnowledgeGraphService(db).get_graph(space_id, current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.patch("/nodes/{doc_id}")
async def update_node(
    space_id: str,
    doc_id: str,
    req: GraphNodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await KnowledgeGraphService(db).update_node(
            space_public_id=space_id,
            doc_id=doc_id,
            label=req.label,
            description=req.description,
            tags=req.tags,
            user=current_user,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/edges", response_model=GraphEdgePayload, status_code=status.HTTP_201_CREATED)
async def create_edge(
    space_id: str,
    req: GraphEdgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await KnowledgeGraphService(db).create_edge(
            space_public_id=space_id,
            source_doc_id=req.source_doc_id,
            target_doc_id=req.target_doc_id,
            relation_type=req.relation_type,
            description=req.description,
            user=current_user,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.patch("/edges/{edge_id}", response_model=GraphEdgePayload)
async def update_edge(
    space_id: str,
    edge_id: str,
    req: GraphEdgeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await KnowledgeGraphService(db).update_edge(
            space_public_id=space_id,
            edge_id=edge_id,
            relation_type=req.relation_type,
            description=req.description,
            user=current_user,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.delete("/edges/{edge_id}")
async def delete_edge(
    space_id: str,
    edge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await KnowledgeGraphService(db).delete_edge(
            space_public_id=space_id,
            edge_id=edge_id,
            user=current_user,
        )
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
