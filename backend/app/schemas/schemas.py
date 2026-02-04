from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# --- 用户相关 ---
class AuthRequest(BaseModel):
    identifier: str
    credential: str
    identity_type: str = "password"
    display_name: Optional[str] = None


class AuthResponse(BaseModel):
    status: str
    user_id: int
    message: str


class UserResponse(BaseModel):
    id: int
    user_key: str
    display_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: int
    user_key: str


# --- 空间相关 ---
class SpaceCreate(BaseModel):
    name: str


class SpaceResponse(BaseModel):
    id: int
    public_id: str
    name: str
    owner_user_id: int

    class Config:
        from_attributes = True


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="文件夹名称")
    parent_id: Optional[int] = Field(None, description="父文件夹ID，根目录传空")


class FileRenameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=255)


class FolderRenameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=255)


class FileBrief(BaseModel):
    id: int
    public_id: str
    name: str
    size_bytes: Optional[int]
    mime: Optional[str]


class TreeFolderResponse(BaseModel):
    id: int
    public_id: str
    name: str
    path_cache: str
    # 嵌套自身，形成树结构
    children: List["TreeFolderResponse"] = []
    # 包含该目录下的文件
    files: List[FileBrief] = []

    class Config:
        from_attributes = True
