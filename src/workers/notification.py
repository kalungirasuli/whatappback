import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from src.core.dependencies import get_redis
from src.services.whatsapp import send_text, send_template
from src.shared.templates import INTEREST_BODY, RESTOCK_BODY

logger = logging.getLogger(__name__)

MESSAGING_WINDOW_PREFIX = "messaging_window:"
MESSAGING_WINDOW_TTL = 86400

INTEREST_NOTIFICATION_PREFIX = "interest_notif:"
INTEREST_NOTIFICATION_TTL = 86400


class NotificationService:
    def __init__(self):
        self._redis: Redis | None = None

    async def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = await get_redis()
        return self._redis

    async def send_interest_notification(
        self,
        merchant_phone: str,
        product_id: int,
        buyer_phone: str,
        product_name: str = "Product",
        price: float = 0.0,
        currency: str = "UGX",
    ) -> bool:
        redis = await self._get_redis()

        dedup_key = f"{INTEREST_NOTIFICATION_PREFIX}{merchant_phone}:{product_id}:{buyer_phone}"
        already_notified = await redis.get(dedup_key)
        if already_notified:
            logger.info(
                "Interest notification already sent: merchant=%s product=%d buyer=%s",
                merchant_phone[:7],
                product_id,
                buyer_phone[:7],
            )
            return False

        within_window = await self.check_messaging_window(merchant_phone)
        if not within_window:
            logger.info(
                "Messaging window expired for merchant=%s, cannot send interest notification",
                merchant_phone[:7],
            )
            return False

        body = INTEREST_BODY.format(
            product_name=product_name,
            price=price,
            currency=currency,
        )

        try:
            result = await send_text(merchant_phone, body)
            if result is not None:
                await redis.setex(dedup_key, INTEREST_NOTIFICATION_TTL, "sent")
                await self.record_outbound_message(merchant_phone)

                logger.info(
                    "Interest notification sent: merchant=%s product=%d buyer=%s",
                    merchant_phone[:7],
                    product_id,
                    buyer_phone[:7],
                )
                return True
            else:
                logger.warning("WhatsApp send returned None for merchant=%s", merchant_phone[:7])
                return False
        except Exception as e:
            logger.error(
                "Failed to send interest notification to merchant=%s: %s",
                merchant_phone[:7],
                e,
            )
            return False

    async def send_restock_notification(
        self,
        buyer_phone: str,
        product_id: int,
        product_name: str = "Product",
        price: float = 0.0,
        currency: str = "UGX",
    ) -> bool:
        redis = await self._get_redis()

        dedup_key = f"restock_notif:{buyer_phone}:{product_id}"
        already_notified = await redis.get(dedup_key)
        if already_notified:
            logger.info(
                "Restock notification already sent: buyer=%s product=%d",
                buyer_phone[:7],
                product_id,
            )
            return False

        body = RESTOCK_BODY.format(
            product_name=product_name,
            price=price,
            currency=currency,
        )

        try:
            result = await send_text(buyer_phone, body)
            if result is not None:
                await redis.setex(dedup_key, INTEREST_NOTIFICATION_TTL, "sent")
                logger.info(
                    "Restock notification sent: buyer=%s product=%d",
                    buyer_phone[:7],
                    product_id,
                )
                return True
            else:
                logger.warning("WhatsApp send returned None for buyer=%s", buyer_phone[:7])
                return False
        except Exception as e:
            logger.error(
                "Failed to send restock notification to buyer=%s: %s",
                buyer_phone[:7],
                e,
            )
            return False

    async def check_messaging_window(self, merchant_phone: str) -> bool:
        redis = await self._get_redis()
        key = f"{MESSAGING_WINDOW_PREFIX}{merchant_phone}"

        last_outbound = await redis.get(key)
        if not last_outbound:
            return True

        try:
            last_outbound_dt = datetime.fromisoformat(last_outbound)
            if last_outbound_dt.tzinfo is None:
                last_outbound_dt = last_outbound_dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            elapsed = (now - last_outbound_dt).total_seconds()
            return elapsed < 86400
        except (ValueError, TypeError):
            logger.warning("Invalid timestamp in messaging window for merchant=%s", merchant_phone[:7])
            return True

    async def record_outbound_message(self, merchant_phone: str) -> None:
        redis = await self._get_redis()
        key = f"{MESSAGING_WINDOW_PREFIX}{merchant_phone}"
        now = datetime.now(timezone.utc).isoformat()
        await redis.setex(key, MESSAGING_WINDOW_TTL, now)

    async def record_inbound_message(self, phone: str) -> None:
        redis = await self._get_redis()
        key = f"inbound_window:{phone}"
        now = datetime.now(timezone.utc).isoformat()
        await redis.setex(key, MESSAGING_WINDOW_TTL, now)

    async def check_buyer_window(self, buyer_phone: str) -> bool:
        redis = await self._get_redis()
        key = f"inbound_window:{buyer_phone}"
        last_inbound = await redis.get(key)
        if not last_inbound:
            return False

        try:
            last_inbound_dt = datetime.fromisoformat(last_inbound)
            if last_inbound_dt.tzinfo is None:
                last_inbound_dt = last_inbound_dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            elapsed = (now - last_inbound_dt).total_seconds()
            return elapsed < 86400
        except (ValueError, TypeError):
            return False
