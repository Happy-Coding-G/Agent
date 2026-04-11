"""
Agent 状态管理模块

提供 Agent 类型定义和状态管理功能。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


class AgentType(str, Enum):
    """Agent 类型枚举"""

    MAIN = "main"           # 主 Agent
    QA = "qa"               # 问答 Agent
    TRADE = "trade"         # 交易 Agent
    DATA_PROCESS = "data_process"  # 数据处理 Agent
    ANALYSIS = "analysis"   # 分析 Agent
    CODE = "code"           # 代码 Agent
    CUSTOM = "custom"       # 自定义 Agent


class AgentStatus(str, Enum):
    """Agent 状态枚举"""

    IDLE = "idle"           # 空闲
    RUNNING = "running"     # 运行中
    PAUSED = "paused"       # 暂停
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 失败
    CANCELLED = "cancelled" # 已取消


@dataclass
class AgentState:
    """Agent 状态数据类"""

    agent_id: str
    agent_type: AgentType
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    memory: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def update_status(self, status: AgentStatus) -> None:
        """更新状态"""
        self.status = status
        self.updated_at = datetime.utcnow()

    def add_memory(self, role: str, content: str, **kwargs) -> None:
        """添加记忆"""
        self.memory.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs
        })
        # 限制记忆长度
        if len(self.memory) > 100:
            self.memory = self.memory[-100:]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "status": self.status.value,
            "current_task": self.current_task,
            "context": self.context,
            "memory_count": len(self.memory),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# 全局状态存储
_agent_states: Dict[str, AgentState] = {}


def get_agent_state(agent_id: str) -> Optional[AgentState]:
    """获取 Agent 状态"""
    return _agent_states.get(agent_id)


def set_agent_state(agent_id: str, state: AgentState) -> None:
    """设置 Agent 状态"""
    _agent_states[agent_id] = state


def remove_agent_state(agent_id: str) -> None:
    """移除 Agent 状态"""
    _agent_states.pop(agent_id, None)


def list_agent_states() -> List[Dict[str, Any]]:
    """列出所有 Agent 状态"""
    return [state.to_dict() for state in _agent_states.values()]
