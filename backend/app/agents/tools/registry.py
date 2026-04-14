"""
AgentToolRegistry - 统一注册、发现、获取 Agent 可调用的 StructuredTool。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Users

logger = logging.getLogger(__name__)


class AgentToolRegistry:
    """
    核心类：统一注册、发现、获取工具 schema。
    构造函数接收 (db: AsyncSession, user: Users, space_id: str|None)。
    """

    def __init__(
        self,
        db: AsyncSession,
        user: Users,
        space_id: Optional[str] = None,
        space_path: Optional[str] = None,
    ):
        self.db = db
        self.user = user
        self.space_id = space_id
        self.space_path = space_path
        self._tools: Dict[str, StructuredTool] = {}
        self._initialized = False

    def _lazy_init(self) -> None:
        if self._initialized:
            return

        # 延迟导入各工具模块，避免循环依赖
        from . import (
            file_tools,
            space_tools,
            markdown_tools,
            graph_tools,
            asset_tools,
            qa_tools,
            data_process_tools,
            review_tools,
            trade_tools,
            memory_tools,
            user_config_tools,
            token_usage_tools,
        )

        builders = [
            file_tools.build_tools,
            space_tools.build_tools,
            markdown_tools.build_tools,
            graph_tools.build_tools,
            asset_tools.build_tools,
            qa_tools.build_tools,
            data_process_tools.build_tools,
            review_tools.build_tools,
            trade_tools.build_tools,
            memory_tools.build_tools,
            user_config_tools.build_tools,
            token_usage_tools.build_tools,
        ]

        for builder in builders:
            try:
                tools = builder(self)
                for tool in tools:
                    self._tools[tool.name] = tool
            except Exception as e:
                logger.warning(f"Failed to build tools from {builder.__module__}: {e}")

        self._initialized = True
        logger.info(f"AgentToolRegistry initialized with {len(self._tools)} tools")

    def get_tools(self) -> List[StructuredTool]:
        """返回所有可用工具列表。"""
        self._lazy_init()
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[StructuredTool]:
        """按名称获取单个工具。"""
        self._lazy_init()
        return self._tools.get(name)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """返回所有工具的 JSON schema 列表，供 LLM tool calling 使用。"""
        self._lazy_init()
        schemas = []
        for tool in self._tools.values():
            schema = {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_schema.model_json_schema() if tool.args_schema else {},
            }
            schemas.append(schema)
        return schemas
