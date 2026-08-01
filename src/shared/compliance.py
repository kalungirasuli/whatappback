import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from src.core.dependencies import get_redis

logger = logging.getLogger(__name__)

CONSENT_PREFIX = "consent:"
CONSENT_TTL = 31536000

ANONYMIZED_PREFIX = "anonymized:"
ANONYMIZED_TTL = 31536000


class ComplianceService:
    def __init__(self):
        self._redis: Redis | None = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def check_consent(self, phone: str) -> bool:
        redis = await self._get_redis()
        key = f"{CONSENT_PREFIX}{phone}"
        consent_value = await redis.get(key)

        if consent_value is None:
            return False

        return consent_value in ("true", "1", "yes", "granted")

    async def record_consent(self, phone: str, consent_type: str = "data_processing") -> None:
        redis = await self._get_redis()
        key = f"{CONSENT_PREFIX}{phone}"
        consent_record = f"{consent_type}:{datetime.now(timezone.utc).isoformat()}"
        await redis.setex(key, CONSENT_TTL, consent_record)
        logger.info(
            "Consent recorded: phone=%s***%s type=%s",
            phone[:4],
            phone[-3:] if len(phone) > 7 else "***",
            consent_type,
        )

    async def revoke_consent(self, phone: str) -> None:
        redis = await self._get_redis()
        key = f"{CONSENT_PREFIX}{phone}"
        await redis.delete(key)
        logger.info(
            "Consent revoked: phone=%s***%s",
            phone[:4],
            phone[-3:] if len(phone) > 7 else "***",
        )

    async def get_data_retention_info(self, phone: str) -> dict:
        redis = await self._get_redis()
        key = f"{CONSENT_PREFIX}{phone}"
        consent_value = await redis.get(key)

        ttl = await redis.ttl(key)

        return {
            "phone_masked": self.mask_phone(phone),
            "has_consent": consent_value is not None,
            "consent_record": consent_value,
            "retention_ttl_seconds": ttl,
            "retention_expiry": (
                datetime.now(timezone.utc).timestamp() + ttl
                if ttl > 0
                else None
            ),
            "data_minimization_enabled": True,
            "right_to_erasure_supported": True,
        }

    @staticmethod
    def mask_phone(phone: str) -> str:
        if not phone or len(phone) < 7:
            return "***"

        digits = phone.lstrip("+")
        if len(digits) <= 4:
            return phone[:2] + "***"

        visible_start = min(3, len(digits) - 3)
        visible_end = min(4, len(digits))

        masked_middle = "*" * min(5, len(digits) - visible_start - visible_end)
        return f"{digits[:visible_start]}***{digits[-visible_end:]}"

    async def anonymize_buyer_data(self, buyer_id: int) -> None:
        redis = await self._get_redis()
        key = f"{ANONYMIZED_PREFIX}buyer:{buyer_id}"
        await redis.setex(key, ANONYMIZED_TTL, datetime.now(timezone.utc).isoformat())

        try:
            from src.core.dependencies import async_session_factory
            from sqlalchemy import update
            from src.domain.models import Buyer, Conversation, ConversationLog

            async with async_session_factory() as db:
                await db.execute(
                    update(Buyer)
                    .where(Buyer.id == buyer_id)
                    .values(
                        phone_number=f"anonymized_{buyer_id}",
                        is_banned=False,
                        banned_reason=None,
                        banned_at=None,
                    )
                )

                await db.execute(
                    update(Conversation)
                    .where(Conversation.phone_number.like(f"%{buyer_id}%"))
                    .values(phone_number=f"anonymized_{buyer_id}")
                )

                await db.commit()

            logger.info("Buyer data anonymized: buyer_id=%d", buyer_id)
        except Exception as e:
            logger.error("Failed to anonymize buyer data for buyer_id=%d: %s", buyer_id, e)

    async def check_data_processor_basis(self, phone: str) -> dict:
        has_consent = await self.check_consent(phone)
        is_anonymized = await self._check_anonymized(phone)

        return {
            "lawful_basis": "consent" if has_consent else "none",
            "has_consent": has_consent,
            "is_anonymized": is_anonymized,
            "data_minimized": True,
            "purpose_limitation": "marketplace product discovery and merchant-buyer communication",
            "retention_period": "12 months or until consent withdrawn",
        }

    async def _check_anonymized(self, phone: str) -> bool:
        redis = await self._get_redis()
        keys = await redis.keys(f"{ANONYMIZED_PREFIX}*:{phone}")
        return len(keys) > 0
