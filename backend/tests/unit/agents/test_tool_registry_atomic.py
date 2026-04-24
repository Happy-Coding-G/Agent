from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.tools.registry import AgentToolRegistry


def test_tool_registry_only_exposes_atomic_capabilities():
    user = MagicMock()
    user.id = 1

    registry = AgentToolRegistry(
        db=MagicMock(),
        user=user,
        space_id="space_1",
        space_path="/tmp/uploads",
    )

    tool_names = {tool.name for tool in registry.get_tools()}

    assert "file_search" in tool_names
    assert "file_read" in tool_names
    assert "asset_manage" in tool_names
    assert "create_listing" in tool_names

    assert "vector_search" in tool_names
    assert "graph_search" in tool_names
    assert "rerank" in tool_names
    assert "qa_hybrid_search" in tool_names
    assert "qa_generate_answer" in tool_names
    assert "review_document" in tool_names
    assert "check_document_quality" in tool_names
    assert "check_document_compliance" in tool_names
    assert "check_document_completeness" in tool_names
    assert "judge_review" in tool_names
    assert "organize_assets" in tool_names
