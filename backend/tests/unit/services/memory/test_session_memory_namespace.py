import pytest
from app.services.memory.session_memory import SessionMemory


class FakeRedis:
    def __init__(self):
        self._data = {}

    async def lpush(self, key, value):
        if key not in self._data:
            self._data[key] = []
        self._data[key].insert(0, value)

    async def ltrim(self, key, start, end):
        if key in self._data:
            self._data[key] = self._data[key][start : end + 1]

    async def expire(self, key, ttl):
        pass

    async def lrange(self, key, start, end):
        return self._data.get(key, [])[start : end + 1]

    async def get(self, key):
        return self._data.get(key)

    async def setex(self, key, ttl, value):
        self._data[key] = value

    async def hset(self, key, field, value):
        if key not in self._data:
            self._data[key] = {}
        self._data[key][field] = value

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
def fake_redis():
    return FakeRedis()


@pytest.fixture
def session_memory(fake_redis):
    sm = SessionMemory(
        redis_client=fake_redis,
        user_id=1,
        space_id="space_abc",
        agent_type="main",
    )
    return sm


@pytest.mark.asyncio
async def test_new_key_format(session_memory):
    await session_memory.add_message("sess_123", "user", "hello")
    recent = await session_memory.get_recent_messages("sess_123", limit=1)
    assert len(recent) == 1
    assert recent[0]["role"] == "user"


@pytest.mark.asyncio
async def test_key_contains_user_space_agent(session_memory, fake_redis):
    await session_memory.add_message("sess_123", "user", "hello")
    keys = await fake_redis.keys("agent:1:space_abc:sess_123:main:*")
    assert len(keys) == 1
    assert "messages" in keys[0]


@pytest.mark.asyncio
async def test_working_memory_key_format(session_memory, fake_redis):
    await session_memory.set_working_memory("sess_123", "foo", "bar")
    val = await session_memory.get_working_memory("sess_123", "foo")
    assert val == "bar"
    keys = await fake_redis.keys("agent:1:space_abc:sess_123:main:working_memory")
    assert len(keys) == 1


@pytest.mark.asyncio
async def test_get_active_sessions_pattern(session_memory):
    await session_memory.add_message("sess_a", "user", "hello")
    await session_memory.add_message("sess_b", "assistant", "hi")
    sessions = await session_memory.get_active_sessions()
    assert set(sessions) == {"sess_a", "sess_b"}


@pytest.mark.asyncio
async def test_legacy_methods_still_work(session_memory, fake_redis):
    await session_memory.add_message_legacy("sess_old", "user", "hello")
    recent = await session_memory.get_recent_messages_legacy("sess_old")
    assert len(recent) == 1
    keys = await fake_redis.keys("session:sess_old:messages")
    assert len(keys) == 1
