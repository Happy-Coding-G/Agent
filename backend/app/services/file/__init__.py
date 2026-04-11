"""
File services package

提供文件相关的业务逻辑服务:
- SpaceFileService: 文件管理服务
"""

from .file_service import SpaceFileService
from .file_service import SpaceFileService as FileService

__all__ = ["SpaceFileService", "FileService"]