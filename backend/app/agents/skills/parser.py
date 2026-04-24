"""SKILL.md parser.

Reads markdown workflow documents with YAML frontmatter and structured sections.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Skill definitions live in packages/; agent definitions live in subagents/docs.
_SUBAGENTS_DIR = Path(__file__).resolve().parent.parent / "subagents" / "docs"
_SKILLS_PACKAGES_DIR = Path(__file__).resolve().parent / "packages"
SKILLS_DOCS_DIRS = [_SUBAGENTS_DIR]


@dataclass
class SkillMDDocument:
    """Parsed SKILL.md document — Claude Code style agent definition.

    Supports both legacy skill metadata and Claude Code style agent frontmatter:
    - name / description / model / color / tools / examples
    - system_prompt (Markdown body as agent system prompt)
    """

    # Legacy / core fields
    skill_id: str
    name: str
    capability_type: str  # skill | subagent | tool | prompt
    description: str
    executor: Optional[str]
    input_schema: Dict[str, Any]
    output_summary: str
    suitable_scenarios: List[str]
    workflow_steps: List[str]
    raw_markdown: str
    frontmatter: Dict[str, Any]

    # Claude Code style fields
    model: Optional[str] = None
    color: Optional[str] = None
    tools: List[str] = None
    skills: List[str] = None  # 引用的 Skill 名称列表
    examples: List[Dict[str, str]] = None
    system_prompt: str = ""

    # Agent-specific fields (new in agent architecture)
    temperature: float = 0.2
    max_rounds: int = 10
    permission_mode: str = "plan"
    memory: Dict[str, Any] = None

    # Skill package fields (Claude Code style folder structure)
    references: Dict[str, str] = None  # {filename: content} from references/
    package_path: Optional[Path] = None  # Path to skill package folder

    def __post_init__(self):
        if self.tools is None:
            self.tools = []
        if self.skills is None:
            self.skills = []
        if self.examples is None:
            self.examples = []
        if self.memory is None:
            self.memory = {}
        if self.references is None:
            self.references = {}

    def to_l1_schema(self) -> Dict[str, Any]:
        """Convert to L1 lightweight schema (metadata only, ~30 words).

        Used for capability routing decisions in MainAgent _plan_step.
        """
        schema: Dict[str, Any] = {
            "name": self.skill_id,
            "display_name": self.name,
            "capability_type": self.capability_type,
            "description": self.description,
        }
        if self.tools:
            schema["tools"] = self.tools
        return schema

    def to_capability_schema(self, level: str = "l2") -> Dict[str, Any]:
        """Convert to schema format expected by MainAgent LLM prompts.

        Args:
            level: "l1" for lightweight metadata-only schema,
                   "l2" for full schema with workflow_steps, examples, etc.
        """
        if level == "l1":
            return self.to_l1_schema()

        schema: Dict[str, Any] = {
            "name": self.skill_id,
            "display_name": self.name,
            "capability_type": self.capability_type,
            "description": self.description,
            "workflow_steps": self.workflow_steps,
            "suitable_scenarios": self.suitable_scenarios,
            "output_summary": self.output_summary,
            "parameters": self.input_schema,
        }
        if self.model:
            schema["model"] = self.model
        if self.color:
            schema["color"] = self.color
        if self.tools:
            schema["tools"] = self.tools
        if self.examples:
            schema["examples"] = self.examples
        # Agent-specific fields
        schema["temperature"] = self.temperature
        schema["max_rounds"] = self.max_rounds
        schema["permission_mode"] = self.permission_mode
        if self.memory:
            schema["memory"] = self.memory
        return schema


class SkillMDParser:
    """Parser for SKILL.md workflow documents."""

    def __init__(self, docs_dirs: Optional[List[Path]] = None):
        self.docs_dirs = docs_dirs or SKILLS_DOCS_DIRS
        self._documents: Dict[str, SkillMDDocument] = {}
        self._loaded = False

    def _load_all(self, metadata_only: bool = False) -> None:
        if self._loaded:
            return
        if metadata_only and getattr(self, "_metadata_loaded", False):
            return

        total_loaded = 0

        # 1) Markdown definition files from configured docs directories
        for docs_dir in self.docs_dirs:
            if not docs_dir.exists():
                logger.debug(f"SKILL.md docs directory not found: {docs_dir}")
                continue

            for md_path in sorted(docs_dir.glob("*.md")):
                try:
                    doc = self._parse_file(md_path, metadata_only=metadata_only)
                    # Subagent docs take precedence over skill docs with same skill_id
                    self._documents[doc.skill_id] = doc
                    total_loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to parse SKILL.md {md_path}: {e}")

        # 2) Skill packages: packages/{skill_name}/Skill.md
        if _SKILLS_PACKAGES_DIR.exists():
            for pkg_dir in sorted(_SKILLS_PACKAGES_DIR.iterdir()):
                if not pkg_dir.is_dir():
                    continue
                skill_md = pkg_dir / "Skill.md"
                if not skill_md.exists():
                    continue
                try:
                    doc = self._parse_file(
                        skill_md,
                        metadata_only=metadata_only,
                        package_dir=pkg_dir,
                    )
                    # Package skills take precedence over flat-file skills
                    self._documents[doc.skill_id] = doc
                    total_loaded += 1
                except Exception as e:
                    logger.warning(f"Failed to parse skill package {pkg_dir}: {e}")

        if metadata_only:
            self._metadata_loaded = True
        else:
            self._loaded = True
        logger.info(
            f"Loaded {len(self._documents)} SKILL.md documents "
            f"({total_loaded} parsed, metadata_only={metadata_only}) "
            f"from {len(self.docs_dirs)} directories + packages"
        )

    def _parse_file(
        self, path: Path, metadata_only: bool = False, package_dir: Optional[Path] = None
    ) -> SkillMDDocument:
        if metadata_only:
            # Stream-read only frontmatter to avoid loading large bodies
            frontmatter_text = ""
            body = ""
            with path.open("r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.strip() == "---":
                    lines = []
                    for line in f:
                        if line.strip() == "---":
                            break
                        lines.append(line)
                    frontmatter_text = "".join(lines)
        else:
            raw = path.read_text(encoding="utf-8")
            # Split YAML frontmatter
            if raw.startswith("---"):
                _, frontmatter_text, body = raw.split("---", 2)
            else:
                frontmatter_text = ""
                body = raw

        frontmatter = yaml.safe_load(frontmatter_text.strip() or "{}") or {}
        body = body.strip() if not metadata_only else ""

        skill_id = frontmatter.get("skill_id") or frontmatter.get("name") or path.stem
        name = frontmatter.get("name") or skill_id
        capability_type = frontmatter.get("capability_type", "skill")
        description = frontmatter.get("description", "")
        executor = frontmatter.get("executor")
        input_schema = frontmatter.get("input_schema", {"type": "object", "properties": {}})
        output_summary = frontmatter.get("output_summary", "")

        # Claude Code style fields
        model = frontmatter.get("model")
        color = frontmatter.get("color")
        tools = frontmatter.get("tools", [])
        skills = frontmatter.get("skills", [])
        examples = frontmatter.get("examples", [])

        # Agent-specific fields (new in agent architecture)
        temperature = frontmatter.get("temperature", 0.2)
        max_rounds = frontmatter.get("max_rounds", 10)
        permission_mode = frontmatter.get("permission_mode", "plan")
        memory = frontmatter.get("memory", {})

        if metadata_only:
            # Skip body extraction when loading metadata only
            workflow_steps: List[str] = []
            suitable_scenarios: List[str] = []
            system_prompt = ""
            raw_markdown = ""
            references: Dict[str, str] = {}
        else:
            # Extract structured sections from markdown body
            workflow_steps = self._extract_list_section(body, "工作流步骤", "workflow steps", "编排流程")
            suitable_scenarios = self._extract_list_section(body, "适用场景", "suitable scenarios", "适用场景")
            # Use the full markdown body as system_prompt (Claude Code style)
            system_prompt = body
            raw_markdown = body
            # Load references/ from skill package (Claude Code style)
            references = {}
            if package_dir:
                refs_dir = package_dir / "references"
                if refs_dir.exists() and refs_dir.is_dir():
                    for ref_path in sorted(refs_dir.glob("*.md")):
                        try:
                            references[ref_path.name] = ref_path.read_text(
                                encoding="utf-8"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to read reference {ref_path} for {skill_id}: {e}"
                            )

        return SkillMDDocument(
            skill_id=skill_id,
            name=name,
            capability_type=capability_type,
            description=description,
            executor=executor,
            input_schema=input_schema,
            output_summary=output_summary,
            suitable_scenarios=suitable_scenarios,
            workflow_steps=workflow_steps,
            raw_markdown=raw_markdown,
            frontmatter=frontmatter,
            model=model,
            color=color,
            tools=tools,
            skills=skills,
            examples=examples,
            system_prompt=system_prompt,
            temperature=temperature,
            max_rounds=max_rounds,
            permission_mode=permission_mode,
            memory=memory,
            references=references,
            package_path=package_dir,
        )

    def _extract_list_section(
        self, body: str, *section_titles: str
    ) -> List[str]:
        """Extract list items from a markdown section by heading title."""
        lines = body.splitlines()
        in_section = False
        items: List[str] = []

        for line in lines:
            stripped = line.strip()
            # Check if this line is a heading matching any of the titles
            is_heading = any(
                re.match(rf"^#+\s*{re.escape(title)}\s*$", stripped, re.IGNORECASE)
                for title in section_titles
            )
            if is_heading:
                in_section = True
                continue

            if in_section:
                # Stop at next heading of same or higher level
                if re.match(r"^#+\s", stripped):
                    break
                # Collect list items
                list_match = re.match(r"^[\*\-\+\d]+[\.\)]?\s*(.+)$", stripped)
                if list_match:
                    items.append(list_match.group(1).strip())
                elif stripped and not items:
                    # First non-empty line could be a plain text description
                    pass

        return items

    def get_document(self, skill_id: str) -> Optional[SkillMDDocument]:
        self._load_all()
        return self._documents.get(skill_id)

    def list_documents(
        self, capability_type: Optional[str] = None
    ) -> List[SkillMDDocument]:
        self._load_all()
        docs = list(self._documents.values())
        if capability_type:
            docs = [d for d in docs if d.capability_type == capability_type]
        return docs

    def list_metadata(
        self, capability_type: Optional[str] = None
    ) -> List[SkillMDDocument]:
        """Return documents with only frontmatter parsed (no body sections).

        Used for L1 lightweight schema generation.
        """
        self._load_all(metadata_only=True)
        docs = list(self._documents.values())
        if capability_type:
            docs = [d for d in docs if d.capability_type == capability_type]
        return docs

    def get_schemas(
        self, capability_type: Optional[str] = None, level: str = "l2"
    ) -> List[Dict[str, Any]]:
        """Return capability schemas for LLM prompt injection.

        Args:
            capability_type: Filter by capability type (skill/agent/tool).
            level: "l1" for lightweight metadata-only schemas,
                   "l2" for full schemas with workflow steps, examples, etc.
        """
        if level == "l1":
            return [
                doc.to_capability_schema(level="l1")
                for doc in self.list_metadata(capability_type)
            ]
        return [
            doc.to_capability_schema(level="l2")
            for doc in self.list_documents(capability_type)
        ]
