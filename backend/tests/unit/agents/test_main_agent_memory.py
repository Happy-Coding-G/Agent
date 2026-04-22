import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.core import MainAgent
from app.agents.core.state import AgentType


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_memory_service():
    m = AsyncMock()
    m.recall_chat_context = AsyncMock(return_value=[
        {"role": "user", "content": "prev"},
        {"role": "assistant", "content": "ok"},
    ])
    m.remember_chat_turn = AsyncMock(return_value={"short_term": {}, "episodic": {}})
    return m


@pytest.fixture
def main_agent(mock_db, mock_memory_service):
    agent = MainAgent(
        db=mock_db,
        llm_client=None,
        memory_service=mock_memory_service,
    )
    return agent


@pytest.mark.asyncio
async def test_stream_chat_recalls_context_when_session_id_present(main_agent, mock_memory_service):
    chunks = []
    async for chunk in main_agent.stream_chat(
        message="hello",
        space_id="space_1",
        user_id=1,
        session_id="sess_1",
    ):
        chunks.append(chunk)

    mock_memory_service.recall_chat_context.assert_awaited_once_with(
        session_id="sess_1",
        agent_type="main",
        max_messages=20,
    )


@pytest.mark.asyncio
async def test_stream_chat_no_recall_without_session_id(main_agent, mock_memory_service):
    chunks = []
    async for chunk in main_agent.stream_chat(
        message="hello",
        space_id="space_1",
        user_id=1,
        session_id=None,
    ):
        chunks.append(chunk)

    mock_memory_service.recall_chat_context.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_routes_qa_intent(main_agent, mock_memory_service):
    """Test that QA intent is detected and routed through the graph."""
    chunks = []
    async for chunk in main_agent.stream_chat(
        message="what is this",
        space_id="space_1",
        user_id=1,
        session_id="sess_2",
    ):
        chunks.append(chunk)

    intent_chunk = [c for c in chunks if c.get("type") == "intent"]
    assert intent_chunk[0]["data"] == "qa"


def _async_gen(items):
    async def gen():
        for item in items:
            yield item
    return gen()
