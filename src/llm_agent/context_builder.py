import json
import logging

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY_PREFIX = "conv_history:"
CONVERSATION_HISTORY_TTL = 86400
MAX_HISTORY_MESSAGES = 20


class ContextBuilder:
    """Formats what we know about a chatroom into a context block for the LLM.

    The pieces arrive pre-built (recent messages, summary, customer memory,
    shop context) from ConversationContext; this class only renders them.
    """

    # ---- legacy Redis helpers (kept for compatibility) -------------------

    async def get_conversation_history(
        self, phone: str, max_messages: int = 10, redis=None
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
        redis, phone: str, role: str, content: str
    ) -> None:
        key = f"{CONVERSATION_HISTORY_PREFIX}{phone}"
        try:
            entry = json.dumps({"role": role, "content": content})
            await redis.rpush(key, entry)
            await redis.ltrim(key, -MAX_HISTORY_MESSAGES, -1)
            await redis.expire(key, CONVERSATION_HISTORY_TTL)
        except Exception as e:
            logger.warning("Failed to save conversation history for %s: %s", phone[:7], e)

    async def build_buyer_context(
        self,
        nlu_result,
        buyer_phone: str,
        search_results: list = None,
        history: list[dict] | None = None,
        shop_context: dict | None = None,
        summary: str | None = None,
        memory: dict | None = None,
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

        if summary:
            sections.append(f"Earlier conversation summary: {summary}")

        if memory:
            memory_lines = [f"  - {k}: {v}" for k, v in memory.items() if k and v is not None]
            if memory_lines:
                sections.append("About this customer:\n" + "\n".join(memory_lines))

        if shop_context:
            shop_lines = []
            for key in ("business_name", "category"):
                if shop_context.get(key):
                    shop_lines.append(f"{key.replace('_', ' ').title()}: {shop_context[key]}")
            products = shop_context.get("products") or []
            if products:
                product_lines = [
                    f"- {p.get('name')} — {p.get('price')} UGX"
                    for p in products[:5]
                ]
                shop_lines.append("Top products:\n" + "\n".join(product_lines))
            if shop_lines:
                sections.append("This shop:\n" + "\n".join(shop_lines))

        if history:
            history_lines = []
            for msg in history[-88:]:
                role = "Customer" if msg.get("role") == "user" else "Assistant"
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
        history: list[dict] | None = None,
    ) -> str:
        sections: list[str] = []

        sections.append(f"Merchant phone: {merchant_phone[:7]}***{merchant_phone[-4:]}" if len(merchant_phone) > 11 else f"Merchant phone: {merchant_phone}")
        sections.append(f"Merchant message: {message_text}")

        if history:
            history_lines = []
            for msg in history[-10:]:
                role = "Merchant" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")
                history_lines.append(f"{role}: {content}")
            sections.append("Recent conversation:\n" + "\n".join(history_lines))

        return "\n\n".join(sections)