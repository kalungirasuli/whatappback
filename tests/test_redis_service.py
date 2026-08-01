import json
from unittest.mock import AsyncMock

from src.services.redis_service import (
    get_session,
    set_session,
    clear_session,
    get_wizard_step,
    set_wizard_step,
    clear_wizard,
    is_duplicate,
    mark_processed,
    SESSION_PREFIX,
    WIZARD_PREFIX,
    DEDUP_PREFIX,
    SEARCH_SESSION_TTL,
    MERCHANT_SESSION_TTL,
    WIZARD_TTL,
    DEDUP_TTL,
)


class TestSessionGetSetClear:
    async def test_set_session_stores_json(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        data = {"step": "search", "query": "shoes"}
        await set_session(mock_redis, "+256700000000", data)

        mock_redis.setex.assert_awaited_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == f"{SESSION_PREFIX}+256700000000"
        assert args[0][1] == SEARCH_SESSION_TTL
        stored = json.loads(args[0][2])
        assert stored == data

    async def test_set_session_custom_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        data = {"merchant_id": 1}
        await set_session(mock_redis, "+256700000000", data, ttl=MERCHANT_SESSION_TTL)

        args = mock_redis.setex.call_args
        assert args[0][1] == MERCHANT_SESSION_TTL

    async def test_get_session_returns_dict(self):
        mock_redis = AsyncMock()
        stored = {"step": "browse", "category": "Electronics"}
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))

        result = await get_session(mock_redis, "+256700000000")

        assert result == stored
        mock_redis.get.assert_awaited_once_with(f"{SESSION_PREFIX}+256700000000")

    async def test_get_session_returns_none_when_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await get_session(mock_redis, "+256700000000")

        assert result is None

    async def test_get_session_returns_none_when_empty(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="")

        result = await get_session(mock_redis, "+256700000000")

        assert result is None

    async def test_clear_session_deletes_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        await clear_session(mock_redis, "+256700000000")

        mock_redis.delete.assert_awaited_once_with(f"{SESSION_PREFIX}+256700000000")

    async def test_roundtrip_session_data(self):
        mock_redis = AsyncMock()
        original = {"query": "laptop", "filters": {"min_price": 100000, "max_price": 500000}}

        captured_value = None

        async def fake_setex(key, ttl, value):
            nonlocal captured_value
            captured_value = value

        mock_redis.setex = AsyncMock(side_effect=fake_setex)
        mock_redis.get = AsyncMock(return_value=None)

        await set_session(mock_redis, "+256700000000", original)

        mock_redis.get = AsyncMock(return_value=captured_value)
        result = await get_session(mock_redis, "+256700000000")

        assert result == original


class TestWizardGetSetClear:
    async def test_set_wizard_step_stores_step_and_data(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await set_wizard_step(mock_redis, "+256700000000", "business_name", {"partial": True})

        args = mock_redis.setex.call_args
        assert args[0][0] == f"{WIZARD_PREFIX}+256700000000"
        assert args[0][1] == WIZARD_TTL
        stored = json.loads(args[0][2])
        assert stored["step"] == "business_name"
        assert stored["data"] == {"partial": True}

    async def test_set_wizard_step_no_data(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await set_wizard_step(mock_redis, "+256700000000", "category")

        args = mock_redis.setex.call_args
        stored = json.loads(args[0][2])
        assert stored["step"] == "category"
        assert stored["data"] == {}

    async def test_get_wizard_step_returns_dict(self):
        mock_redis = AsyncMock()
        wizard_data = {"step": "location", "data": {"business_name": "Cafe"}}
        mock_redis.get = AsyncMock(return_value=json.dumps(wizard_data))

        result = await get_wizard_step(mock_redis, "+256700000000")

        assert result == wizard_data
        mock_redis.get.assert_awaited_once_with(f"{WIZARD_PREFIX}+256700000000")

    async def test_get_wizard_step_returns_none_when_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await get_wizard_step(mock_redis, "+256700000000")

        assert result is None

    async def test_clear_wizard_deletes_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        await clear_wizard(mock_redis, "+256700000000")

        mock_redis.delete.assert_awaited_once_with(f"{WIZARD_PREFIX}+256700000000")

    async def test_wizard_roundtrip(self):
        mock_redis = AsyncMock()
        captured = None

        async def fake_setex(key, ttl, value):
            nonlocal captured
            captured = value

        mock_redis.setex = AsyncMock(side_effect=fake_setex)
        mock_redis.get = AsyncMock(return_value=None)

        await set_wizard_step(mock_redis, "+256700000000", "confirm", {"business_name": "Shop"})

        mock_redis.get = AsyncMock(return_value=captured)
        result = await get_wizard_step(mock_redis, "+256700000000")

        assert result["step"] == "confirm"
        assert result["data"]["business_name"] == "Shop"


class TestDedupFunctions:
    async def test_is_duplicate_true(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")

        result = await is_duplicate(mock_redis, "msg_300")

        assert result is True
        mock_redis.get.assert_awaited_once_with(f"{DEDUP_PREFIX}msg_300")

    async def test_is_duplicate_false(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await is_duplicate(mock_redis, "msg_301")

        assert result is False

    async def test_is_duplicate_empty_string(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="")

        result = await is_duplicate(mock_redis, "msg_302")

        assert result is False

    async def test_mark_processed_stores_with_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_processed(mock_redis, "msg_400")

        mock_redis.setex.assert_awaited_once_with(
            f"{DEDUP_PREFIX}msg_400", DEDUP_TTL, "1"
        )

    async def test_mark_processed_overwrites(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_processed(mock_redis, "msg_401")
        await mark_processed(mock_redis, "msg_401")

        assert mock_redis.setex.await_count == 2
