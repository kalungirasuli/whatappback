import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY_PREFIX = "conv_history:"
CONVERSATION_HISTORY_TTL = 86400
MAX_HISTORY_MESSAGES = 20


class ContextBuilder:
    async def build_buyer_context(
        self,
        nlu_result,
        buyer_phone: str,
        search_results: list = None,
    ) -> str:
        sections: list[str] = []

        sections.append(f"Buyer intent: {nlu_result.intent}")
        sections.append(f"Confidence: {nlu_result.confidence:.2f}")

        if nlu_result.entities:
            entity_lines = []
            for key, value in nlu_result.entities.items():
                if key == "product_name":
                    entity_lines.append(f"Product name: {value}")
                elif key == "color":
                    if isinstance(value, list):
                        entity_lines.append(f"Colors: {', '.join(value)}")
                    else:
                        entity_lines.append(f"Color: {value}")
                elif key == "category":
                    if isinstance(value, list):
                        entity_lines.append(f"Categories: {', '.join(value)}")
                    else:
                        entity_lines.append(f"Category: {value}")
                elif key == "price_min":
                    entity_lines.append(f"Min price: {float(value):,.0f} UGX")
                elif key == "price_max":
                    entity_lines.append(f"Max price: {float(value):,.0f} UGX")
                elif key == "location":
                    entity_lines.append(f"Location preference: {value}")
            if entity_lines:
                sections.append("Extracted entities:\n" + "\n".join(f"  - {l}" for l in entity_lines))

        history = await self.get_conversation_history(buyer_phone, max_messages=10)
        if history:
            history_lines = []
            for msg in history[-10:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            sections.append("Recent conversation:\n" + "\n".join(history_lines))

        if search_results:
            result_lines = []
            for i, r in enumerate(search_results[:5], 1):
                product_name = getattr(r, "product_id", f"Product #{getattr(r, 'product_id', i)}")
                match_label = getattr(r, "match_label", "")
                result_lines.append(f"  {i}. Product ID {product_name} - Match: {match_label}")
            sections.append("Search results:\n" + "\n".join(result_lines))

        return "\n\n".join(sections)

    async def build_merchant_context(
        self,
        message_text: str,
        merchant_phone: str,
    ) -> str:
        sections: list[str] = []

        sections.append(f"Merchant phone: {merchant_phone[:7]}***{merchant_phone[-4:]}" if len(merchant_phone) > 11 else f"Merchant phone: {merchant_phone}")
        sections.append(f"Merchant message: {message_text}")

        history = await self.get_conversation_history(merchant_phone, max_messages=10)
        if history:
            history_lines = []
            for msg in history[-10:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            sections.append("Recent conversation:\n" + "\n".join(history_lines))

        return "\n\n".join(sections)

    async def get_conversation_history(
        self, phone: str, max_messages: int = 10, redis: Redis = None
    ) -> list[dict]:
        if redis is None:
            return []

        key = f"{CONVERSATION_HISTORY_PREFIX}{phone}"
        try:
            raw = await redis.lrange(key, -max_messages, -1)
            messages: list[dict] = []
            for item in raw:
                try:
                    messages.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    continue
            return messages
        except Exception as e:
            logger.warning("Failed to fetch conversation history for %s: %s", phone[:7], e)
            return []

    @staticmethod
    async def save_message_to_history(
        redis: Redis, phone: str, role: str, content: str
    ) -> None:
        key = f"{CONVERSATION_HISTORY_PREFIX}{phone}"
        try:
            entry = json.dumps({"role": role, "content": content})
            await redis.rpush(key, entry)
            await redis.ltrim(key, -MAX_HISTORY_MESSAGES, -1)
            await redis.expire(key, CONVERSATION_HISTORY_TTL)
        except Exception as e:
            logger.warning("Failed to save conversation history for %s: %s", phone[:7], e)
