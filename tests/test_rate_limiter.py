from unittest.mock import AsyncMock, MagicMock, patch

from src.shared.rate_limiter import (
    check_rate_limit,
    check_register_rate_limit,
    REGISTER_RATE_KEY,
    REGISTER_WINDOW,
)


class FakePipeline:
    def __init__(self, results):
        self._results = results
        self._calls = []

    def zremrangebyscore(self, *args):
        self._calls.append(("zremrangebyscore", args))
        return self

    def zcard(self, *args):
        self._calls.append(("zcard", args))
        return self

    def zadd(self, key, mapping):
        self._calls.append(("zadd", (key, mapping)))
        return self

    def expire(self, key, ttl):
        self._calls.append(("expire", (key, ttl)))
        return self

    async def execute(self):
        return self._results


class TestCheckRateLimit:
    async def test_not_limited_when_below_max(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 5, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_rate_limit(mock_redis, "rl:test", max_count=10, window=60)

        assert result is False
        mock_redis.pipeline.assert_called_once()

    async def test_limited_when_at_max(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 10, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_rate_limit(mock_redis, "rl:test", max_count=10, window=60)

        assert result is True

    async def test_limited_when_above_max(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 15, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_rate_limit(mock_redis, "rl:test", max_count=10, window=60)

        assert result is True

    async def test_not_limited_when_count_zero(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 0, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_rate_limit(mock_redis, "rl:test", max_count=5, window=60)

        assert result is False

    async def test_pipeline_operations_are_called(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 2, None, None])
        mock_redis.pipeline.return_value = pipe

        await check_rate_limit(mock_redis, "rl:key", max_count=5, window=30)

        op_names = [c[0] for c in pipe._calls]
        assert op_names == ["zremrangebyscore", "zcard", "zadd", "expire"]

    async def test_pipeline_expire_uses_window(self):
        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 1, None, None])
        mock_redis.pipeline.return_value = pipe

        await check_rate_limit(mock_redis, "rl:key", max_count=5, window=120)

        expire_call = [c for c in pipe._calls if c[0] == "expire"][0]
        assert expire_call[1][1] == 120


class TestCheckRegisterRateLimit:
    @patch("src.shared.rate_limiter.settings")
    async def test_uses_correct_key_format(self, mock_settings):
        mock_settings.register_rate_limit_per_number = 3
        mock_settings.register_rate_limit_window_hours = 24

        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 0, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_register_rate_limit(mock_redis, "+256700000000")

        expected_key = REGISTER_RATE_KEY.format(phone="+256700000000")
        assert pipe._calls[0][0] == "zremrangebyscore"
        assert pipe._calls[0][1][0] == expected_key
        assert result is False

    @patch("src.shared.rate_limiter.settings")
    async def test_limited_when_over_register_limit(self, mock_settings):
        mock_settings.register_rate_limit_per_number = 3
        mock_settings.register_rate_limit_window_hours = 24

        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 3, None, None])
        mock_redis.pipeline.return_value = pipe

        result = await check_register_rate_limit(mock_redis, "+256700000001")

        assert result is True

    @patch("src.shared.rate_limiter.settings")
    async def test_window_calculation(self, mock_settings):
        mock_settings.register_rate_limit_per_number = 3
        mock_settings.register_rate_limit_window_hours = 24

        mock_redis = MagicMock()
        pipe = FakePipeline(results=[None, 0, None, None])
        mock_redis.pipeline.return_value = pipe

        await check_register_rate_limit(mock_redis, "+256700000002")

        expire_call = [c for c in pipe._calls if c[0] == "expire"][0]
        expected_window = 24 * REGISTER_WINDOW
        assert expire_call[1][1] == expected_window
