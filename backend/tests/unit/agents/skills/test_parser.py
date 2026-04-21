"""Tests for SkillMDParser three-tier progressive loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.agents.skills.parser import SkillMDDocument, SkillMDParser


class TestSkillMDDocumentSchema:
    """Test SkillMDDocument schema generation at different levels."""

    def _make_doc(self) -> SkillMDDocument:
        return SkillMDDocument(
            skill_id="test_skill",
            name="Test Skill",
            capability_type="skill",
            description="A test skill for unit testing.",
            executor=None,
            input_schema={"type": "object"},
            output_summary="test output",
            suitable_scenarios=["scenario_a", "scenario_b"],
            workflow_steps=["step_1", "step_2"],
            raw_markdown="# Test\n\nSome body content",
            frontmatter={},
            model="deepseek-chat",
            color="blue",
            tools=["tool_a", "tool_b"],
            skills=["sub_skill"],
            examples=[{"input": "x", "output": "y"}],
            system_prompt="Some body content",
            temperature=0.5,
            max_rounds=5,
            permission_mode="auto",
            memory={"namespace": "test"},
        )

    def test_to_l1_schema_fields(self):
        doc = self._make_doc()
        schema = doc.to_l1_schema()

        assert set(schema.keys()) <= {"name", "display_name", "capability_type", "description", "tools"}
        assert schema["name"] == "test_skill"
        assert schema["display_name"] == "Test Skill"
        assert schema["capability_type"] == "skill"
        assert schema["description"] == "A test skill for unit testing."
        assert schema["tools"] == ["tool_a", "tool_b"]

    def test_to_l1_schema_no_tools(self):
        doc = self._make_doc()
        doc.tools = []
        schema = doc.to_l1_schema()
        assert "tools" not in schema

    def test_to_capability_schema_l1(self):
        doc = self._make_doc()
        schema = doc.to_capability_schema(level="l1")
        assert "workflow_steps" not in schema
        assert "suitable_scenarios" not in schema
        assert "examples" not in schema
        assert "memory" not in schema
        assert schema["name"] == "test_skill"

    def test_to_capability_schema_l2_default(self):
        doc = self._make_doc()
        schema = doc.to_capability_schema()

        # Default should be L2 (full schema)
        assert schema["name"] == "test_skill"
        assert schema["workflow_steps"] == ["step_1", "step_2"]
        assert schema["suitable_scenarios"] == ["scenario_a", "scenario_b"]
        assert schema["examples"] == [{"input": "x", "output": "y"}]
        assert schema["parameters"] == {"type": "object"}
        assert schema["temperature"] == 0.5
        assert schema["max_rounds"] == 5
        assert schema["permission_mode"] == "auto"
        assert schema["memory"] == {"namespace": "test"}

    def test_to_capability_schema_l2_explicit(self):
        doc = self._make_doc()
        schema = doc.to_capability_schema(level="l2")
        assert "workflow_steps" in schema
        assert "parameters" in schema


class TestSkillMDParserMetadataOnly:
    """Test parser metadata-only loading and list_metadata."""

    @pytest.fixture
    def temp_docs_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "docs"
            docs_dir.mkdir()

            # Create a test .md with frontmatter and large body
            md_path = docs_dir / "test_skill.md"
            md_content = (
                "---\n"
                "skill_id: test_skill\n"
                "name: Test Skill\n"
                "capability_type: skill\n"
                "description: A test skill\n"
                "tools: [tool_a, tool_b]\n"
                "---\n\n"
                "# 工作流步骤\n"
                "- Step 1\n"
                "- Step 2\n\n"
                "# 适用场景\n"
                "- Scenario A\n"
                "- Scenario B\n\n"
                "This is a very long body that should not be parsed in metadata-only mode.\n"
            ) + ("Lorem ipsum dolor sit amet.\n" * 100)
            md_path.write_text(md_content, encoding="utf-8")

            # Create a second file
            md_path2 = docs_dir / "test_agent.md"
            md_path2.write_text(
                "---\n"
                "skill_id: test_agent\n"
                "name: Test Agent\n"
                "capability_type: agent\n"
                "description: A test agent\n"
                "---\n\n"
                "Agent body content here.\n",
                encoding="utf-8",
            )

            yield docs_dir

    def test_load_all_metadata_only(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        parser._load_all(metadata_only=True)

        assert parser._metadata_loaded is True
        assert parser._loaded is False
        assert len(parser._documents) == 2

        doc = parser._documents["test_skill"]
        assert doc.name == "Test Skill"
        assert doc.description == "A test skill"
        assert doc.tools == ["tool_a", "tool_b"]
        # Body should be empty in metadata-only mode
        assert doc.raw_markdown == ""
        assert doc.system_prompt == ""
        assert doc.workflow_steps == []
        assert doc.suitable_scenarios == []

    def test_load_all_full_after_metadata(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        parser._load_all(metadata_only=True)
        parser._load_all(metadata_only=False)

        assert parser._loaded is True

        doc = parser._documents["test_skill"]
        assert doc.raw_markdown != ""
        assert "工作流步骤" in doc.raw_markdown
        assert doc.workflow_steps == ["Step 1", "Step 2"]
        assert doc.suitable_scenarios == ["Scenario A", "Scenario B"]

    def test_list_metadata(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        docs = parser.list_metadata()

        assert len(docs) == 2
        assert all(doc.raw_markdown == "" for doc in docs)

    def test_list_metadata_filter_by_type(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        skill_docs = parser.list_metadata(capability_type="skill")
        agent_docs = parser.list_metadata(capability_type="agent")

        assert len(skill_docs) == 1
        assert skill_docs[0].skill_id == "test_skill"
        assert len(agent_docs) == 1
        assert agent_docs[0].skill_id == "test_agent"

    def test_get_document_triggers_full_load(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        # First trigger metadata-only load via list_metadata
        _ = parser.list_metadata()
        assert parser._metadata_loaded is True
        assert parser._loaded is False

        # get_document should trigger full load
        doc = parser.get_document("test_skill")
        assert doc is not None
        assert doc.raw_markdown != ""
        assert doc.workflow_steps == ["Step 1", "Step 2"]

    def test_get_schemas_l1_vs_l2(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])

        l1_schemas = parser.get_schemas(level="l1")
        l2_schemas = parser.get_schemas(level="l2")

        assert len(l1_schemas) == len(l2_schemas) == 2

        # L1 schemas should be smaller
        l1_skill = next(s for s in l1_schemas if s["name"] == "test_skill")
        l2_skill = next(s for s in l2_schemas if s["name"] == "test_skill")

        assert "workflow_steps" not in l1_skill
        assert "suitable_scenarios" not in l1_skill
        assert "parameters" not in l1_skill

        assert "workflow_steps" in l2_skill
        assert "suitable_scenarios" in l2_skill
        assert "parameters" in l2_skill

    def test_list_documents_triggers_full_load(self, temp_docs_dir):
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        docs = parser.list_documents()

        assert len(docs) == 2
        assert all(doc.raw_markdown != "" for doc in docs)
        assert parser._loaded is True

    def test_parser_backward_compat_default(self, temp_docs_dir):
        """Test that default behavior is unchanged (L2 full schema)."""
        parser = SkillMDParser(docs_dirs=[temp_docs_dir])
        schemas = parser.get_schemas()

        schema = next(s for s in schemas if s["name"] == "test_skill")
        assert "workflow_steps" in schema
        assert "parameters" in schema
