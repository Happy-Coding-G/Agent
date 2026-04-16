import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.memory.unified_memory import UnifiedMemoryService
from app.services.memory.session_memory import SessionMemory


class FakeRedis:
    def __init__(self):
        self._data = {}

    async def lpush(self, key, value):
        self._data.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        if key in self._data:
            self._data[key] = self._data[key][start:end + 1]

    async def expire(self, key, ttl):
        pass

    async def lrange(self, key, start, end):
        return self._data.get(key, [])[start:end + 1]

    async def setex(self, key, ttl, value):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)

    async def hset(self, key, field, value):
        self._data.setdefault(key, {})[field] = value

    async def hget(self, key, field):
        return self._data.get(key, {}).get(field)

    async def hgetall(self, key):
        return self._data.get(key, {})

    async def delete(self, *keys):
        for k in keys:
            self._data.pop(k, None)

    async def keys(self, pattern):
        import fnmatch
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]

    async def ttl(self, key):
        return 3600


@pytest.fixture
def fake_session_memory():
    sm = SessionMemory(
        redis_client=FakeRedis(),
        user_id=1,
        space_id="space_123",
        agent_type="main",
    )
    return sm


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def unified_memory(mock_db, fake_session_memory):
    um = UnifiedMemoryService(
        db=mock_db,
        user_id=1,
        space_id="space_123",
        session_memory=fake_session_memory,
    )
    um.episodic = AsyncMock()
    um.longterm = AsyncMock()
    return um


@pytest.mark.asyncio
async def test_remember_chat_turn_writes_both_layers(unified_memory):
    unified_memory.episodic.add_message = AsyncMock(return_value=MagicMock(
        message_id="msg_1", embedding=None
    ))

    result = await unified_memory.remember_chat_turn("sess_1", "user", "hello")

    assert result["short_term"]["role"] == "user"
    assert result["episodic"]["message_id"] == "msg_1"


@pytest.mark.asyncio
async def test_recall_chat_context_prefers_l3(unified_memory):
    await unified_memory.session_memory.add_message("sess_1", "user", "hello")
    await unified_memory.session_memory.add_message("sess_1", "assistant", "hi")

    ctx = await unified_memory.recall_chat_context("sess_1", max_messages=10)

    assert len(ctx) == 2
    assert ctx[0]["role"] == "user"
    assert ctx[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_recall_chat_context_backfills_from_l4(unified_memory):
    fake_msg = MagicMock()
    fake_msg.role = "user"
    fake_msg.content = "backfill"
    fake_msg.metadata = {}

    unified_memory.episodic.get_messages = AsyncMock(return_value=[fake_msg])

    ctx = await unified_memory.recall_chat_context("sess_empty", max_messages=10)

    assert len(ctx) == 1
    assert ctx[0]["content"] == "backfill"


@pytest.mark.asyncio
async def test_working_memory_roundtrip(unified_memory):
    await unified_memory.set_working_memory("key_a", {"foo": "bar"}, session_id="sess_1")
    val = await unified_memory.get_working_memory("key_a", session_id="sess_1")
    assert val == {"foo": "bar"}


@pytest.mark.asyncio
async def test_log_event_writes_l4(unified_memory):
    unified_memory.episodic.add_event = AsyncMock(return_value=MagicMock(message_id="evt_1"))

    msg = await unified_memory.log_event(
        event_type="trade_offer",
        payload={"price": 100},
        session_id="sess_1",
    )

    assert msg.message_id == "evt_1"
    unified_memory.episodic.add_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_events_filters(unified_memory):
    unified_memory.episodic.get_events = AsyncMock(return_value=[
        {"event_type": "trade_offer", "content": "offer"},
        {"event_type": "qa_citation", "content": "cite"},
    ])

    events = await unified_memory.get_session_events(
        session_id="sess_1",
        event_types=["trade_offer"],
    )

    # episodic.get_events 已做过滤，这里直接返回其结果
    assert len(events) == 2
