import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.auth.otp import OTPService, OTP_KEY_PREFIX, OTP_RATE_PREFIX


class TestGenerateAndSendOTP:
    async def test_generate_otp_stores_in_redis(self):
        redis = AsyncMock()
        redis.get.return_value = None
        service = OTPService(redis)

        with patch("src.auth.otp.send_text", new_callable=AsyncMock):
            result = await service.generate_and_send("+256700000000")

        assert result is True
        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args
        key = call_args[0][0]
        ttl = call_args[0][1]
        code = call_args[0][2]
        assert key.startswith(OTP_KEY_PREFIX)
        assert ttl == 300
        assert len(code) == 6
        assert code.isdigit()

    async def test_generate_otp_sends_whatsapp_message(self):
        redis = AsyncMock()
        redis.get.return_value = None
        service = OTPService(redis)

        with patch("src.auth.otp.send_text", new_callable=AsyncMock) as mock_send:
            await service.generate_and_send("+256700000000")

        mock_send.assert_awaited_once()
        args = mock_send.call_args[0]
        assert args[0] == "256700000000"
        assert "verification code" in args[1].lower()
        assert "whatAppseller" in args[1]

    async def test_otp_format_is_6_digits(self):
        redis = AsyncMock()
        redis.get.return_value = None
        service = OTPService(redis)

        with patch("src.auth.otp.send_text", new_callable=AsyncMock):
            await service.generate_and_send("+256700000000")

        code = redis.setex.call_args[0][2]
        assert len(code) == 6
        assert code.isdigit()
        assert 0 <= int(code) <= 999999


class TestVerifyOTP:
    async def test_verify_otp_correct_code(self):
        redis = AsyncMock()
        redis.get.return_value = "123456"
        service = OTPService(redis)

        result = await service.verify("+256700000000", "123456")

        assert result is True
        redis.delete.assert_awaited_once()

    async def test_verify_otp_wrong_code(self):
        redis = AsyncMock()
        redis.get.return_value = "123456"
        service = OTPService(redis)

        result = await service.verify("+256700000000", "999999")

        assert result is False
        redis.delete.assert_not_awaited()

    async def test_verify_otp_expired(self):
        redis = AsyncMock()
        redis.get.return_value = None
        service = OTPService(redis)

        result = await service.verify("+256700000000", "123456")

        assert result is False
        redis.delete.assert_not_awaited()


class TestRateLimitOTP:
    async def test_rate_limit_otp(self):
        redis = AsyncMock()
        redis.get.return_value = "3"
        service = OTPService(redis)

        with patch("src.auth.otp.send_text", new_callable=AsyncMock) as mock_send:
            result = await service.generate_and_send("+256700000000")

        assert result is False
        redis.setex.assert_not_awaited()
        mock_send.assert_not_awaited()
