import logging
import random
import string

from redis.asyncio import Redis

from src.core.config import settings
from src.services.whatsapp import send_text
from src.shared.phone_utils import normalize_phone

logger = logging.getLogger(__name__)

OTP_KEY_PREFIX = "otp:"
OTP_RATE_PREFIX = "otp_rate:"


class OTPService:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def generate_and_send(self, phone: str) -> bool:
        normalized = normalize_phone(phone)

        rate_key = f"{OTP_RATE_PREFIX}{normalized}"
        rate_count = await self.redis.get(rate_key)
        if rate_count and int(rate_count) >= settings.otp_rate_limit_per_phone:
            return False

        code = "".join(random.choices(string.digits, k=6))

        otp_key = f"{OTP_KEY_PREFIX}{normalized}"
        await self.redis.setex(otp_key, settings.otp_expire_seconds, code)

        await self.redis.incr(rate_key)
        await self.redis.expire(rate_key, settings.otp_rate_limit_window_seconds)

        logger.info("OTP for %s: %s (expires in %ds)", normalized, code, settings.otp_expire_seconds)

        message = (
            f"Your whatAppseller verification code is: {code}\n"
            f"Expires in {settings.otp_expire_seconds // 60} minutes."
        )
        await send_text(normalized, message)

        return True

    async def verify(self, phone: str, code: str) -> bool:
        normalized = normalize_phone(phone)
        otp_key = f"{OTP_KEY_PREFIX}{normalized}"
        stored_code = await self.redis.get(otp_key)

        if stored_code is None:
            return False

        if stored_code == code:
            await self.redis.delete(otp_key)
            return True

        return False
