from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.core.errors import ServiceError
from app.db.models import Users
from app.db.session import get_db
from app.schemas.schemas import MarkdownDocDetail, MarkdownDocSummary
from app.services.markdown_service import MarkdownDocumentService

router = APIRouter(prefix="/spaces/{space_id}/markdown-docs", tags=["Markdown"])


@router.get("", response_model=list[MarkdownDocSummary])
async def list_markdown_docs(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await MarkdownDocumentService(db).list_documents(space_id, current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/{doc_id}", response_model=MarkdownDocDetail)
async def get_markdown_doc(
    space_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await MarkdownDocumentService(db).get_document(space_id, doc_id, current_user)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


