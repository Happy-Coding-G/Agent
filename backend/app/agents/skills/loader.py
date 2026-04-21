"""SkillLoader - Claude Code 风格的三层加载器。

L1: Frontmatter（始终加载）- 用于判断何时触发 Skill
L2: Body（Skill 被触发时加载）- 完整指令
L3: Linked files（按需加载）- 附加文档、示例、脚本
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.agents.skills.parser import SKILLS_DOCS_DIRS

logger = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    """Skill 定义 - 包含 frontmatter 和 body 的解析结果。"""

    name: str
    description: str
    capability_type: str
    allowed_tools: List[str]
    skills: List[str]  # 引用的子 Skill
    body: str
    frontmatter: Dict[str, Any]
    path: Path

    def __post_init__(self):
        if self.allowed_tools is None:
            self.allowed_tools = []
        if self.skills is None:
            self.skills = []


class SkillLoader:
    """Claude Code 风格 Skill 三层加载器。

    目录结构:
        skills/docs/skill-name/SKILL.md
        skills/docs/skill-name/examples/*.md
        skills/docs/skill-name/references/*.md
    """

    def __init__(self, docs_dirs: Optional[List[Path]] = None):
        self.docs_dirs = docs_dirs or SKILLS_DOCS_DIRS
        self._l1_cache: Dict[str, SkillDefinition] = {}
        self._l2_cache: Dict[str, str] = {}
        self._l3_cache: Dict[str, str] = {}

    def _find_skill_path(self, skill_name: str) -> Optional[Path]:
        """查找 Skill 目录或文件路径。"""
        # 先尝试目录形式: skill-name/SKILL.md
        for docs_dir in self.docs_dirs:
            dir_path = docs_dir / skill_name / "SKILL.md"
            if dir_path.exists():
                return dir_path
            # 再尝试旧版文件形式: skill-name.md
            file_path = docs_dir / f"{skill_name}.md"
            if file_path.exists():
                return file_path
        return None

    def _read_frontmatter(self, path: Path) -> tuple[Dict[str, Any], str, bool]:
        """高效读取 frontmatter，避免加载大文件的全部内容。

        先读前 4KB，如果包含完整的 ---...--- 则只解析 frontmatter，
        body 返回空字符串（由 load_level2 按需补全）。
        否则回退到完整读取。

        Returns:
            (frontmatter_dict, body_or_empty, is_complete_full_read)
        """
        chunk_size = 4096
        with path.open("r", encoding="utf-8") as f:
            chunk = f.read(chunk_size)

        if not chunk.startswith("---"):
            # 没有 frontmatter，完整读取
            full = path.read_text(encoding="utf-8")
            return {}, full, True

        lines = chunk.splitlines()
        fm_lines = []
        found_end = False
        for line in lines[1:]:
            if line.strip() == "---":
                found_end = True
                break
            fm_lines.append(line)

        if not found_end:
            # frontmatter 超过 4KB，回退到完整读取
            full = path.read_text(encoding="utf-8")
            parts = full.split("---", 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1].strip() or "{}") or {}
                return frontmatter, parts[2], True
            return {}, full, True

        # 成功在 4KB 内读完 frontmatter
        frontmatter = yaml.safe_load("\n".join(fm_lines)) or {}
        return frontmatter, "", False

    def load_level1(self, skill_name: str) -> Optional[SkillDefinition]:
        """加载 Level 1: 只解析 frontmatter（始终可用）。

        返回 SkillDefinition，包含 frontmatter 元数据。
        body 可能为空，由 load_level2 按需补全。
        """
        if skill_name in self._l1_cache:
            return self._l1_cache[skill_name]

        path = self._find_skill_path(skill_name)
        if not path:
            logger.warning(f"Skill not found: {skill_name}")
            return None

        frontmatter, body, _ = self._read_frontmatter(path)

        # 解析 allowed-tools（Claude Code 风格）或 tools
        allowed_tools = frontmatter.get("allowed-tools") or frontmatter.get("tools", [])
        if isinstance(allowed_tools, str):
            allowed_tools = allowed_tools.split()

        skills = frontmatter.get("skills", [])
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]

        definition = SkillDefinition(
            name=frontmatter.get("name", skill_name),
            description=frontmatter.get("description", ""),
            capability_type=frontmatter.get("capability_type", "skill"),
            allowed_tools=allowed_tools,
            skills=skills,
            body=body.strip() if body else "",
            frontmatter=frontmatter,
            path=path,
        )

        self._l1_cache[skill_name] = definition
        return definition

    def load_level2(self, skill_name: str) -> Optional[str]:
        """加载 Level 2: 返回完整 body（Skill 被触发时加载）。

        包含角色定义、执行流程、质量标准等完整指令。
        如果 L1 未加载 body，会从文件补全。
        """
        if skill_name in self._l2_cache:
            return self._l2_cache[skill_name]

        skill = self.load_level1(skill_name)
        if not skill:
            return None

        # 如果 L1 没有加载 body（frontmatter-only 优化），现在补全
        if not skill.body:
            path = skill.path
            full = path.read_text(encoding="utf-8")
            if full.startswith("---"):
                parts = full.split("---", 2)
                if len(parts) >= 3:
                    skill.body = parts[2].strip()
                else:
                    skill.body = full.strip()
            else:
                skill.body = full.strip()

        self._l2_cache[skill_name] = skill.body
        return skill.body

    def load_level3(self, skill_name: str, file_path: str) -> Optional[str]:
        """加载 Level 3: 按需加载 linked files。

        file_path 是相对于 Skill 目录的相对路径。
        例如: "examples/pricing_example.md", "references/market_data.csv"
        """
        cache_key = f"{skill_name}/{file_path}"
        if cache_key in self._l3_cache:
            return self._l3_cache[cache_key]

        skill = self.load_level1(skill_name)
        if not skill:
            return None

        # 文件相对于 Skill 目录
        if skill.path.parent.is_dir() and skill.path.name == "SKILL.md":
            full_path = skill.path.parent / file_path
        else:
            # 旧版单文件模式: 使用 docs 目录作为 base
            full_path = skill.path.parent / skill_name / file_path

        if not full_path.exists():
            logger.warning(f"Linked file not found: {full_path}")
            return None

        content = full_path.read_text(encoding="utf-8")
        self._l3_cache[cache_key] = content
        return content

    def get_skill_prompt(self, skill_name: str) -> Optional[str]:
        """获取 Skill 的完整 prompt（L1 + L2 组合）。

        返回可用于注入 Agent 上下文的完整指令文本。
        """
        skill = self.load_level1(skill_name)
        if not skill:
            return None

        body = self.load_level2(skill_name)
        if not body:
            return None

        # 组合为 Agent 可使用的 prompt 格式
        prompt_parts = [
            f"## Skill: {skill.name}",
            f"\n{skill.description}\n",
            body,
        ]

        # 如果有引用的子 Skill，递归加载（防止循环引用）
        if skill.skills:
            sub_skills_text = []
            for sub_name in skill.skills:
                if sub_name == skill_name:
                    continue  # 跳过自引用
                sub_body = self.load_level2(sub_name)
                if sub_body:
                    sub_skills_text.append(f"### Sub-Skill: {sub_name}\n{sub_body}")
            if sub_skills_text:
                prompt_parts.append("\n## 引用的子技能\n")
                prompt_parts.extend(sub_skills_text)

        return "\n".join(prompt_parts)

    def list_skills(self) -> List[str]:
        """列出所有可用的 Skill 名称。"""
        skills: set = set()
        for docs_dir in self.docs_dirs:
            if not docs_dir.exists():
                continue
            # 目录形式
            for subdir in docs_dir.iterdir():
                if subdir.is_dir() and (subdir / "SKILL.md").exists():
                    skills.add(subdir.name)
            # 文件形式
            for md_file in docs_dir.glob("*.md"):
                skills.add(md_file.stem)
        return sorted(skills)
