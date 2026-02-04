from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps.auth import get_current_user
from app.core.errors import ServiceError
from app.services.file_service import SpaceFileService
from app.schemas.schemas import FolderCreate, FolderRenameRequest, TreeFolderResponse
from app.db.models import Users

router = APIRouter(prefix="/spaces/{space_id}", tags=["File Management"])


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    space_id: str,
    req: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await SpaceFileService(db).create_folder(space_id, req.parent_id, req.name, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch("/folders/{folder_public_id}/rename")
async def rename_folder(
    space_id: str,
    folder_public_id: str,
    req: FolderRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await SpaceFileService(db).rename_folder(space_id, folder_public_id, req.new_name, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/files/upload-init")
async def init_upload(
    space_id: str,
    folder_id: str,
    filename: str,
    size_bytes: int,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await SpaceFileService(db).init_upload(space_id, folder_id, filename, size_bytes, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/files/upload-complete")
async def complete_upload(
    space_id: str,
    upload_id: str,
    object_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await SpaceFileService(db).complete_upload(space_id, upload_id, object_key, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/tree", response_model=List[TreeFolderResponse])
async def get_space_tree(
    space_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    try:
        return await SpaceFileService(db).get_space_tree(space_id, user=current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
