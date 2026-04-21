"""Sidechain 日志管理。

设计目标：
1. 完整记录 Agent 内部执行过程（思考、工具调用、观察、决策）
2. Parent 的上下文窗口不可见（防止污染）
3. 支持事后审计和调试
4. 支持 Agent 自身的状态恢复（checkpoint）

存储策略：
- 内存中缓存 entries（批量写入）
- 异步批量写入 PostgreSQL sidechain_logs 表
- 支持 LLM 压缩生成摘要
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SidechainEntry:
    """Sidechain 单条日志条目。"""

    session_id: str
    parent_session_id: str
    agent_id: str
    event_type: str  # "thought" | "tool_call" | "observation" | "decision" | "error" | "task_start" | "task_complete" | "task_timeout" | "task_error"
    content: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    entry_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }


class SidechainLogger:
    """Agent 执行过程的独立日志。

    每个 AgentSession 拥有独立的 SidechainLogger 实例。
    session_id 格式: {parent_session_id}:{agent_id}
    """

    FLUSH_BATCH_SIZE = 10
    FLUSH_INTERVAL_SECONDS = 5

    def __init__(
        self,
        session_id: str,
        parent_session_id: str,
        agent_id: str,
        max_entries: int = 1000,
    ):
        self.session_id = session_id
        self.parent_session_id = parent_session_id
        self.agent_id = agent_id
        self.max_entries = max_entries
        self.entries: List[SidechainEntry] = []
        self._pending_entries: List[SidechainEntry] = []
        self._flush_count = 0

    async def log(self, event_type: str, content: Dict[str, Any]) -> None:
        """记录事件到 sidechain。"""
        entry = SidechainEntry(
            session_id=self.session_id,
            parent_session_id=self.parent_session_id,
            agent_id=self.agent_id,
            event_type=event_type,
            content=content,
        )
        self.entries.append(entry)
        self._pending_entries.append(entry)

        # 内存上限保护
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
            logger.warning(
                f"Sidechain entries exceeded max {self.max_entries}, truncated oldest"
            )

        # 触发异步刷新
        await self._flush_if_needed()

    async def _flush_if_needed(self) -> None:
        """条件触发批量写入数据库。"""
        if len(self._pending_entries) >= self.FLUSH_BATCH_SIZE:
            await self._flush_to_db()

    async def _flush_to_db(self) -> None:
        """将 pending entries 批量写入 PostgreSQL。"""
        if not self._pending_entries:
            return

        try:
            from app.db.models import SidechainLog
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                logs = [
                    SidechainLog(
                        session_id=e.session_id,
                        parent_session_id=e.parent_session_id,
                        agent_id=e.agent_id,
                        event_type=e.event_type,
                        content=e.content,
                        created_at=e.timestamp,
                    )
                    for e in self._pending_entries
                ]
                db.add_all(logs)
                await db.commit()

            self._flush_count += len(self._pending_entries)
            self._pending_entries.clear()
        except Exception as e:
            logger.warning(
                f"Failed to flush sidechain logs to DB: {e}. "
                f"Entries remain in memory."
            )

    async def finalize(self) -> None:
        """强制刷新所有 pending entries。"""
        await self._flush_to_db()

    async def get_entries(
        self,
        event_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[SidechainEntry]:
        """查询日志条目（优先从内存读取，缺失时从数据库补）。"""
        # 从内存过滤
        results = self.entries
        if event_types:
            results = [e for e in results if e.event_type in event_types]

        if len(results) >= limit:
            return results[-limit:]

        # 从数据库补
        try:
            from app.db.models import SidechainLog
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import select, desc

            async with AsyncSessionLocal() as db:
                stmt = (
                    select(SidechainLog)
                    .where(SidechainLog.session_id == self.session_id)
                    .order_by(desc(SidechainLog.created_at))
                    .limit(limit)
                )
                if event_types:
                    stmt = stmt.where(SidechainLog.event_type.in_(event_types))

                result = await db.execute(stmt)
                db_entries = result.scalars().all()

                memory_ids = {e.timestamp for e in self.entries}
                for row in db_entries:
                    if row.created_at not in memory_ids:
                        results.append(
                            SidechainEntry(
                                session_id=row.session_id,
                                parent_session_id=row.parent_session_id,
                                agent_id=row.agent_id,
                                event_type=row.event_type,
                                content=row.content,
                                timestamp=row.created_at,
                                entry_id=row.id,
                            )
                        )
        except Exception as e:
            logger.warning(f"Failed to load sidechain entries from DB: {e}")

        return results[-limit:]

    async def get_summary(self, llm_client=None) -> str:
        """生成执行摘要（用于返回 parent）。

        如果提供了 llm_client，使用 LLM 压缩；
        否则生成简单的文本摘要。
        """
        entries = await self.get_entries(limit=50)
        if not entries:
            return "无执行记录。"

        # 统计信息
        event_counts: Dict[str, int] = {}
        tool_calls = []
        errors = []
        for e in entries:
            event_counts[e.event_type] = event_counts.get(e.event_type, 0) + 1
            if e.event_type == "tool_call":
                tool_name = e.content.get("tool", "unknown")
                tool_calls.append(tool_name)
            elif e.event_type == "task_error":
                errors.append(str(e.content.get("error", "")))

        # 简单摘要
        parts = [
            f"Agent {self.agent_id} 执行摘要:",
            f"- 总事件数: {len(entries)}",
            f"- 工具调用: {len(tool_calls)} 次 ({', '.join(set(tool_calls))})",
        ]
        if errors:
            parts.append(f"- 错误: {len(errors)} 个")
        if event_counts.get("task_complete"):
            parts.append("- 状态: 完成")
        elif event_counts.get("task_timeout"):
            parts.append("- 状态: 超时")
        elif event_counts.get("task_error"):
            parts.append("- 状态: 失败")

        simple_summary = "\n".join(parts)

        # 如果有 LLM，尝试生成更好的摘要
        if llm_client and len(entries) > 5:
            try:
                summary_input = "\n".join(
                    f"[{e.event_type}] {json.dumps(e.content, ensure_ascii=False)[:200]}"
                    for e in entries[-20:]
                )
                prompt = (
                    f"请将以下 Agent 执行日志压缩为 1-2 句话的中文摘要，"
                    f"突出关键操作和结果:\n\n{summary_input}"
                )
                response = await llm_client.ainvoke(prompt)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
                return content.strip()
            except Exception as e:
                logger.warning(f"LLM sidechain summary failed: {e}")

        return simple_summary

    def get_tool_call_history(self) -> List[Dict[str, Any]]:
        """获取工具调用历史。"""
        return [
            e.content
            for e in self.entries
            if e.event_type == "tool_call"
        ]
