"""Agent 间通信协议。

定义 AgentRequest / AgentResult / AgentMessage 数据结构，
用于 MainAgent 与 SubAgent、Agent 与 Agent 之间的标准化通信。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class AgentMessage:
    """Agent 间消息。

    用于 Redis Pub/Sub 消息总线上的通信。
    """

    type: str  # "request" | "response" | "event" | "progress"
    sender: str  # 发送者 session_id 或 agent_id
    topic: str  # 消息主题
    payload: Dict[str, Any] = field(default_factory=dict)  # 消息内容
    recipient: Optional[str] = None  # 接收者 agent_id（None 表示广播）
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: Optional[str] = None  # 用于追踪请求-响应链

    def dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "sender": self.sender,
            "topic": self.topic,
            "payload": self.payload,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def parse_raw(cls, data: Dict[str, Any]) -> "AgentMessage":
        return cls(
            type=data["type"],
            sender=data["sender"],
            topic=data["topic"],
            payload=data.get("payload", {}),
            recipient=data.get("recipient"),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            correlation_id=data.get("correlation_id"),
        )


@dataclass
class AgentRequest:
    """Agent 任务请求。

    MainAgent 向 Agent 派发任务时的请求结构。
    只传递上下文摘要，不传递完整历史。
    """

    agent_id: str  # 目标 Agent 标识
    task_description: str  # 自然语言任务描述
    arguments: Dict[str, Any] = field(default_factory=dict)  # 结构化参数
    parent_session_id: str = ""  # parent 会话 ID
    context_summary: str = ""  # 上下文摘要（非完整历史）
    allowed_tools: List[str] = field(default_factory=list)  # 允许使用的工具
    max_rounds: int = 10
    timeout_seconds: int = 300
    correlation_id: Optional[str] = None  # 追踪 ID
    user_id: Optional[int] = None  # 当前用户 ID
    space_id: Optional[str] = None  # 当前空间 ID

    def __post_init__(self):
        if not self.correlation_id:
            self.correlation_id = str(uuid.uuid4())

    def dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "task_description": self.task_description,
            "arguments": self.arguments,
            "parent_session_id": self.parent_session_id,
            "context_summary": self.context_summary,
            "allowed_tools": self.allowed_tools,
            "max_rounds": self.max_rounds,
            "timeout_seconds": self.timeout_seconds,
            "correlation_id": self.correlation_id,
            "user_id": self.user_id,
            "space_id": self.space_id,
        }

    @classmethod
    def parse_raw(cls, data: Dict[str, Any]) -> "AgentRequest":
        return cls(
            agent_id=data["agent_id"],
            task_description=data.get("task_description", ""),
            arguments=data.get("arguments", {}),
            parent_session_id=data.get("parent_session_id", ""),
            context_summary=data.get("context_summary", ""),
            allowed_tools=data.get("allowed_tools", []),
            max_rounds=data.get("max_rounds", 10),
            timeout_seconds=data.get("timeout_seconds", 300),
            correlation_id=data.get("correlation_id"),
            user_id=data.get("user_id"),
            space_id=data.get("space_id"),
        )


@dataclass
class AgentResult:
    """Agent 任务结果。

    Agent 执行完成后返回的结果结构。
    只包含最终摘要和关键产出物，完整过程在 sidechain 中。
    """

    success: bool
    summary: str  # LLM 生成的执行摘要
    artifacts: List[Dict[str, Any]] = field(default_factory=list)  # 关键产出物
    error: Optional[str] = None
    sidechain_id: str = ""  # 可查询详细日志的 ID
    token_usage: Optional[int] = None
    correlation_id: Optional[str] = None
    agent_id: Optional[str] = None  # 执行 Agent 的标识
    rounds_used: int = 0  # 实际使用的轮数
    tool_calls_count: int = 0  # 工具调用次数

    def dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "error": self.error,
            "sidechain_id": self.sidechain_id,
            "token_usage": self.token_usage,
            "correlation_id": self.correlation_id,
            "agent_id": self.agent_id,
            "rounds_used": self.rounds_used,
            "tool_calls_count": self.tool_calls_count,
        }

    @classmethod
    def parse_raw(cls, data: Dict[str, Any]) -> "AgentResult":
        return cls(
            success=data.get("success", False),
            summary=data.get("summary", ""),
            artifacts=data.get("artifacts", []),
            error=data.get("error"),
            sidechain_id=data.get("sidechain_id", ""),
            token_usage=data.get("token_usage"),
            correlation_id=data.get("correlation_id"),
            agent_id=data.get("agent_id"),
            rounds_used=data.get("rounds_used", 0),
            tool_calls_count=data.get("tool_calls_count", 0),
        )
