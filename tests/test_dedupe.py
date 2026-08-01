from unittest.mock import AsyncMock, MagicMock

from src.gateway.dedupe import check_and_mark
from src.services.redis_service import is_duplicate, mark_processed, DEDUP_PREFIX, DEDUP_TTL


class TestCheckAndMark:
    async def test_returns_false_when_not_duplicate(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        result = await check_and_mark(mock_redis, "msg_001")

        assert result is False
        mock_redis.get.assert_awaited_once_with(f"{DEDUP_PREFIX}msg_001")
        mock_redis.setex.assert_awaited_once_with(
            f"{DEDUP_PREFIX}msg_001", DEDUP_TTL, "1"
        )

    async def test_returns_true_when_already_duplicate(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")
        mock_redis.setex = AsyncMock()

        result = await check_and_mark(mock_redis, "msg_002")

        assert result is True
        mock_redis.get.assert_awaited_once_with(f"{DEDUP_PREFIX}msg_002")
        mock_redis.setex.assert_not_awaited()

    async def test_returns_false_for_first_message(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        result = await check_and_mark(mock_redis, "first_msg")

        assert result is False

    async def test_returns_true_for_second_call_same_id(self):
        mock_redis = AsyncMock()
        call_count = 0

        async def fake_get(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return "1"

        mock_redis.get = AsyncMock(side_effect=fake_get)
        mock_redis.setex = AsyncMock()

        result1 = await check_and_mark(mock_redis, "msg_003")
        result2 = await check_and_mark(mock_redis, "msg_003")

        assert result1 is False
        assert result2 is True


class TestIsDuplicate:
    async def test_not_duplicate_when_key_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await is_duplicate(mock_redis, "msg_100")

        assert result is False
        mock_redis.get.assert_awaited_once_with(f"{DEDUP_PREFIX}msg_100")

    async def test_is_duplicate_when_key_exists(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")

        result = await is_duplicate(mock_redis, "msg_101")

        assert result is True

    async def test_not_duplicate_when_empty_string(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="")

        result = await is_duplicate(mock_redis, "msg_102")

        assert result is False


class TestMarkProcessed:
    async def test_sets_key_with_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_processed(mock_redis, "msg_200")

        mock_redis.setex.assert_awaited_once_with(
            f"{DEDUP_PREFIX}msg_200", DEDUP_TTL, "1"
        )

    async def test_stores_correct_value(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_processed(mock_redis, "msg_201")

        args = mock_redis.setex.call_args
        assert args[0][2] == "1"
        assert args[0][1] == DEDUP_TTL
