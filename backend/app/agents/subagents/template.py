"""Template for dynamically created subagents.

This is not a domain-specific subagent.
It is a generic workflow shell that the MainAgent can instantiate
when a request is too broad for a single direct answer, tool call,
or skill execution.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SubAgentTemplate:
    name: str = "dynamic_workflow"
    purpose: str = "为复杂任务生成可执行的多步骤子代理工作流"
    trigger_conditions: List[str] = field(
        default_factory=lambda: [
            "任务包含多个阶段",
            "需要跨能力组合执行",
            "MainAgent 无法单次完成",
            "需要先规划再执行",
        ]
    )
    default_workflow: List[str] = field(
        default_factory=lambda: [
            "澄清目标与交付物",
            "收集上下文与约束",
            "拆分任务阶段",
            "逐步执行子任务",
            "验证结果并汇总输出",
        ]
    )
    deliverable: str = "结构化的执行计划与后续执行入口"


class DynamicWorkflowSubAgent:
    """Generic dynamic subagent scaffold.

    Current scope:
    - create a structured workflow shell for complex tasks
    - optionally expand steps with LLM
    - return a stable plan object for later execution
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.template = SubAgentTemplate()

    async def run(
        self,
        task_name: str,
        goal: str,
        deliverable: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        suggested_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        workflow_steps = suggested_steps or await self._generate_steps(task_name, goal)

        return {
            "success": True,
            "subagent_type": self.template.name,
            "task_name": task_name,
            "goal": goal,
            "deliverable": deliverable or self.template.deliverable,
            "context": context or {},
            "workflow_steps": workflow_steps,
            "template": asdict(self.template),
            "status": "templated",
            "message": "已为复杂任务生成动态 subagent 模板，可继续填充具体执行动作。",
        }

    async def _generate_steps(self, task_name: str, goal: str) -> List[str]:
        if not self.llm_client:
            return self._default_steps(task_name, goal)

        prompt = (
            "你是一个复杂任务工作流设计器。请基于任务目标生成 4 到 6 个中文执行步骤。"
            "只返回 JSON 数组字符串，不要返回其他文本。\n\n"
            f"任务名称: {task_name}\n"
            f"任务目标: {goal}\n"
        )

        try:
            response = await self.llm_client.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            steps = json.loads(content)
            if isinstance(steps, list) and all(isinstance(item, str) for item in steps):
                return steps
        except Exception:
            pass

        return self._default_steps(task_name, goal)

    def _default_steps(self, task_name: str, goal: str) -> List[str]:
        return [
            f"理解复杂任务边界：{task_name}",
            f"抽取关键目标与约束：{goal}",
            "识别需要组合的能力模块",
            "执行阶段化处理与中间校验",
            "汇总结果并给出后续动作",
        ]
