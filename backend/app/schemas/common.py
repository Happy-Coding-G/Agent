"""Common response schemas."""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ResponseModel(BaseModel, Generic[DataT]):
    success: bool = Field(default=True, description="请求是否成功")
    data: Optional[DataT] = Field(default=None, description="响应数据")
    message: Optional[str] = Field(default=None, description="补充消息")