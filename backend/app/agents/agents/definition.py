"""AgentDefinition - 从 .md 定义文件解析的 Agent 配置数据类。

增强自 SkillMDDocument，增加 Agent 特有的配置字段：
- permission_mode: 权限模式（plan | auto | notify）
- memory: 记忆配置（namespace、persist_events、max_sidechain_entries）
- max_rounds: 最大执行轮数
- system_prompt: 覆盖默认的系统提示
- temperature: LLM 温度参数
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentMemoryConfig:
    """Agent 记忆配置。"""

    namespace: str = ""  # L3 Redis key 前缀
    persist_events: bool = True  # 是否写入 L4 sidechain
    max_sidechain_entries: int = 1000  # sidechain 最大条目数

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AgentMemoryConfig":
        if not data:
            return cls()
        return cls(
            namespace=data.get("namespace", ""),
            persist_events=data.get("persist_events", True),
            max_sidechain_entries=data.get("max_sidechain_entries", 1000),
        )


@dataclass
class AgentDefinition:
    """Agent 定义 - 从 .md 文件解析的完整配置。

    继承并扩展了 SkillMDDocument 的字段，增加 Agent 特有的行为配置。
    """

    # 基础标识
    skill_id: str
    name: str
    capability_type: str  # "agent" | "skill" | "tool" | "prompt"
    description: str

    # 执行配置
    executor: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    output_summary: str = ""

    # Claude Code style 字段
    model: Optional[str] = None
    temperature: float = 0.2
    color: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)  # 引用的 Skill 名称列表
    examples: List[Dict[str, str]] = field(default_factory=list)
    system_prompt: str = ""


    # Agent 特有字段
    max_rounds: int = 10
    permission_mode: str = "plan"  # plan | auto | notify
    memory: AgentMemoryConfig = field(default_factory=AgentMemoryConfig)

    # 原始数据保留
    raw_markdown: str = ""
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    suitable_scenarios: List[str] = field(default_factory=list)
    workflow_steps: List[str] = field(default_factory=list)

    def to_capability_schema(self, level: str = "l2") -> Dict[str, Any]:
        """转换为 MainAgent LLM prompt 使用的 capability schema。

        Args:
            level: "l1" 只返回轻量元数据（name, display_name, capability_type,
                   description, tools），用于路由决策。
                   "l2" 返回完整 schema（当前默认行为，向后兼容）。
        """
        if level == "l1":
            schema: Dict[str, Any] = {
                "name": self.skill_id,
                "display_name": self.name,
                "capability_type": self.capability_type,
                "description": self.description,
            }
            if self.tools:
                schema["tools"] = self.tools
            return schema

        schema = {
            "name": self.skill_id,
            "display_name": self.name,
            "capability_type": self.capability_type,
            "description": self.description,
            "workflow_steps": self.workflow_steps,
            "suitable_scenarios": self.suitable_scenarios,
            "output_summary": self.output_summary,
            "parameters": self.input_schema,
            "max_rounds": self.max_rounds,
            "permission_mode": self.permission_mode,
        }
        if self.model:
            schema["model"] = self.model
        if self.color:
            schema["color"] = self.color
        if self.tools:
            schema["tools"] = self.tools
        if self.examples:
            schema["examples"] = self.examples
        if self.memory.namespace:
            schema["memory_namespace"] = self.memory.namespace
        return schema

    def is_agent(self) -> bool:
        """判断是否为 Agent（独立会话式）。"""
        return self.capability_type in ("agent", "subagent")

    def is_skill(self) -> bool:
        """判断是否为 Skill（可复用分析能力）。"""
        return self.capability_type == "skill"

    def is_tool(self) -> bool:
        """判断是否为 Tool（原子操作）。"""
        return self.capability_type == "tool"
