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

SKILLS_DOCS_DIR = Path(__file__).with_name("docs")


@dataclass
class SkillMDDocument:
    """Parsed SKILL.md document."""

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

    def to_capability_schema(self) -> Dict[str, Any]:
        """Convert to schema format expected by MainAgent LLM prompts."""
        return {
            "name": self.skill_id,
            "display_name": self.name,
            "capability_type": self.capability_type,
            "description": self.description,
            "workflow_steps": self.workflow_steps,
            "suitable_scenarios": self.suitable_scenarios,
            "output_summary": self.output_summary,
            "parameters": self.input_schema,
        }


class SkillMDParser:
    """Parser for SKILL.md workflow documents."""

    def __init__(self, docs_dir: Optional[Path] = None):
        self.docs_dir = docs_dir or SKILLS_DOCS_DIR
        self._documents: Dict[str, SkillMDDocument] = {}
        self._loaded = False

    def _load_all(self) -> None:
        if self._loaded:
            return
        if not self.docs_dir.exists():
            logger.warning(f"SKILL.md docs directory not found: {self.docs_dir}")
            self._loaded = True
            return

        for md_path in sorted(self.docs_dir.glob("*.md")):
            try:
                doc = self._parse_file(md_path)
                self._documents[doc.skill_id] = doc
            except Exception as e:
                logger.warning(f"Failed to parse SKILL.md {md_path}: {e}")

        self._loaded = True
        logger.info(f"Loaded {len(self._documents)} SKILL.md documents from {self.docs_dir}")

    def _parse_file(self, path: Path) -> SkillMDDocument:
        raw = path.read_text(encoding="utf-8")

        # Split YAML frontmatter
        if raw.startswith("---"):
            _, frontmatter_text, body = raw.split("---", 2)
        else:
            frontmatter_text = ""
            body = raw

        frontmatter = yaml.safe_load(frontmatter_text.strip() or "{}") or {}
        body = body.strip()

        skill_id = frontmatter.get("skill_id") or path.stem
        name = frontmatter.get("name") or skill_id
        capability_type = frontmatter.get("capability_type", "skill")
        description = frontmatter.get("description", "")
        executor = frontmatter.get("executor")
        input_schema = frontmatter.get("input_schema", {"type": "object", "properties": {}})
        output_summary = frontmatter.get("output_summary", "")

        # Extract structured sections from markdown body
        workflow_steps = self._extract_list_section(body, "工作流步骤", "workflow steps")
        suitable_scenarios = self._extract_list_section(body, "适用场景", "suitable scenarios")

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
            raw_markdown=body,
            frontmatter=frontmatter,
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

    def get_schemas(self, capability_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return capability schemas for LLM prompt injection."""
        return [doc.to_capability_schema() for doc in self.list_documents(capability_type)]
