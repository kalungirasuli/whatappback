"""Per-chatroom conversation context: durable memory for the sales agents.

Tiers (matching the three-level context architecture):
1. Recent messages — PostgreSQL source of truth, Redis fast cache (conv:{id}).
   The last HISTORY_WINDOW messages are kept in full.
2. Rolling summary — when a conversation grows past the window, the oldest
   messages are folded (compacted) into `conversation.summary` by Ollama, so
   the summary always represents "everything older than the last 88 messages".
3. Customer memory — long-term facts stored per customer_key.

Plus shop/business context when a conversation is scoped to a merchant.

The whole object (full recent messages + summary + memory + shop) is attached
to NLU and reply-agent requests so both see the exact same conversation.
"""

import datetime
import json
import logging
import uuid

import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domain.enums import MessageRole
from src.domain.models import (
    ChatInteraction,
    Conversation,
    ConversationMessage,
    CustomerMemory,
    Merchant,
    Product,
)

logger = logging.getLogger(__name__)

REDIS_PREFIX = "conv:"
HISTORY_WINDOW = 88
REDIS_LIMIT = HISTORY_WINDOW
REDIS_MAX_LIMIT = HISTORY_WINDOW
TTL_SECONDS = 7 * 86400
MAX_CONTEXT_MESSAGES = HISTORY_WINDOW
COMPACT_EVERY = 10
MAX_SUMMARY_MESSAGES = 60

OLLAMA_GENERATE_URL = f"{settings.ollama_url}/api/generate"

SUMMARY_PROMPT = (
    "You are the memory manager for a WhatsApp marketplace chatroom.\n"
    "You maintain a rolling summary. You are given the CURRENT summary (which may\n"
    "be empty) and NEW messages that have just moved out of the active window.\n"
    "Respond with ONE JSON object and nothing else:\n"
    '{"update": "...", "memory": {...}}\n\n'
    "- update: the single new paragraph of up to 3 sentences to APPEND to the\n"
    "  existing summary (what happened in the new messages: what the customer\n"
    "  wants, budget, colours, sizes, delivery preference, current stage).\n"
    '  Use field "summary" instead of "update" when the existing summary is empty.\n'
    "- memory: durable customer facts ONLY, each with a simple key, e.g.\n"
    '  {"name": "Sarah", "preferred_length": "20 inches", "preferred_color": "black",\n'
    '   "budget": "80 USD"}. Prefer existing keys, keep values short. Include nothing speculative.\n\n'
    "Existing summary:\n{existing_summary}\n\n"
    "New messages (oldest first):\n{transcript}"
)


class ConversationContext:
    """Read/write chatroom memory across Redis (fast) + Postgres (durable)."""

    async def ensure_conversation(
        self,
        db: AsyncSession,
        phone: str,
        role: MessageRole,
        merchant_id: int | None = None,
        customer_id: int | None = None,
        backfill: bool = False,
    ) -> Conversation:
        query = select(Conversation).where(
            Conversation.phone_number == phone,
            Conversation.role == role,
            (Conversation.merchant_id.is_(None) if merchant_id is None else Conversation.merchant_id == merchant_id),
        )
        result = await db.execute(query)
        conv = result.scalars().first()

        if conv:
            conv.last_message_at = datetime.datetime.now(datetime.UTC)
            if customer_id and not conv.customer_id:
                conv.customer_id = customer_id
            await db.commit()
            return conv

        conv = Conversation(
            phone_number=phone[:20],
            role=role,
            merchant_id=merchant_id,
            customer_id=customer_id,
            public_id=f"chat_{uuid.uuid4().hex[:12]}",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        if backfill:
            await self._backfill_from_chat_log(db, conv)
        return conv

    async def load_context(
        self,
        db: AsyncSession,
        redis,
        conversation_id: int,
        max_messages: int = MAX_CONTEXT_MESSAGES,
    ) -> dict:
        messages = await self._load_messages_redis(redis, conversation_id, max_messages)
        if not messages:
            messages = await self._load_messages_db(db, conversation_id, max_messages)
            await self._seed_redis(redis, conversation_id, messages)

        conv = await db.get(Conversation, conversation_id)
        return {
            "conversation": conv,
            "messages": messages,
            "summary": conv.summary if conv else None,
            "memory": await self._load_memory(db, conv.phone_number if conv else None),
            "shop": await self._load_shop_context(db, conv.merchant_id if conv else None),
        }

    async def append(
        self,
        db: AsyncSession,
        redis,
        conversation_id: int,
        role: str,
        content: str,
    ) -> None:
        if content is None:
            content = ""
        await self._append_redis(redis, conversation_id, role, content)
        try:
            db.add(ConversationMessage(conversation_id=conversation_id, role=role, content=content))
            conv = await db.get(Conversation, conversation_id)
            if conv:
                conv.last_message_at = datetime.datetime.now(datetime.UTC)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Failed to persist conversation message")

        await self.maybe_refresh_summary(db, redis, conversation_id)

    async def maybe_refresh_summary(
        self,
        db: AsyncSession,
        redis,
        conversation_id: int,
    ) -> None:
        """Compaction trigger: when the active window overflows, fold the oldest
        messages (beyond the last HISTORY_WINDOW) into the rolling summary."""
        if redis is None:
            return
        try:
            count = await redis.llen(self._redis_key(conversation_id))
        except Exception:
            logger.warning("Redis llen failed for conv %s", conversation_id)
            return
        overflow = count - HISTORY_WINDOW
        if overflow > 0 and overflow % COMPACT_EVERY == 0:
            await self._compact_old_messages(db, redis, conversation_id, overflow)

    # ---- internals -------------------------------------------------------

    @staticmethod
    def _redis_key(conversation_id: int) -> str:
        return f"{REDIS_PREFIX}{conversation_id}"

    async def _load_messages_redis(self, redis, conversation_id: int, max_messages: int) -> list[dict]:
        if redis is None:
            return []
        try:
            key = self._redis_key(conversation_id)
            raw = await redis.lrange(key, -max_messages, -1)
            messages = []
            for item in raw:
                try:
                    messages.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    continue
            return messages
        except Exception as e:
            logger.warning("Redis history load failed for conv %s: %s", conversation_id, e)
            return []

    async def _load_messages_db(self, db: AsyncSession, conversation_id: int, max_messages: int) -> list[dict]:
        try:
            result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(max_messages)
            )
            rows = result.scalars().all()
            rows.reverse()
            return [{"role": r.role, "content": r.content} for r in rows]
        except Exception as e:
            logger.warning("DB history load failed for conv %s: %s", conversation_id, e)
            return []

    async def _seed_redis(self, redis, conversation_id: int, messages: list[dict]) -> None:
        if redis is None or not messages:
            return
        try:
            key = self._redis_key(conversation_id)
            for msg in messages[-REDIS_MAX_LIMIT:]:
                await redis.rpush(key, json.dumps(msg))
            await redis.ltrim(key, -REDIS_LIMIT, -1)
            await redis.expire(key, TTL_SECONDS)
        except Exception as e:
            logger.warning("Redis history seed failed for conv %s: %s", conversation_id, e)

    async def _append_redis(self, redis, conversation_id: int, role: str, content: str) -> None:
        if redis is None:
            return
        try:
            key = self._redis_key(conversation_id)
            await redis.rpush(key, json.dumps({"role": role, "content": content}))
            await redis.ltrim(key, -REDIS_LIMIT, -1)
            await redis.expire(key, TTL_SECONDS)
        except Exception as e:
            logger.warning("Redis history append failed for conv %s: %s", conversation_id, e)

    async def _load_memory(self, db: AsyncSession, customer_key: str | None) -> dict:
        if not customer_key:
            return {}
        try:
            result = await db.execute(
                select(CustomerMemory).where(CustomerMemory.customer_key == customer_key)
            )
            row = result.scalars().first()
            return row.memory if row else {}
        except Exception as e:
            logger.warning("Memory load failed for %s: %s", customer_key, e)
            return {}

    async def _save_memory(self, db: AsyncSession, customer_key: str | None, memory: dict) -> None:
        if not customer_key or not memory:
            return
        try:
            result = await db.execute(
                select(CustomerMemory).where(CustomerMemory.customer_key == customer_key)
            )
            row = result.scalars().first()
            if row is None:
                row = CustomerMemory(customer_key=customer_key, memory={})
                db.add(row)
            row.memory.update({k: v for k, v in memory.items() if v is not None})
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning("Memory save failed for %s: %s", customer_key, e)

    async def _load_shop_context(self, db: AsyncSession, merchant_id: int | None) -> dict | None:
        if not merchant_id:
            return None
        try:
            merchant = await db.get(Merchant, merchant_id)
            if not merchant:
                return None
            result = await db.execute(
                select(Product)
                .where(Product.merchant_id == merchant_id, Product.status == "active")
                .order_by(Product.created_at.desc())
                .limit(5)
            )
            products = [
                {"name": p.name, "brand": p.brand, "category": p.category, "price": p.price}
                for p in result.scalars().all()
            ]
            return {
                "business_name": merchant.business_name,
                "category": merchant.category,
                "status": merchant.status,
                "location_lat": merchant.location_lat,
                "location_lng": merchant.location_lng,
                "products": products,
            }
        except Exception as e:
            logger.warning("Shop context load failed for merchant %s: %s", merchant_id, e)
            return None

    async def _compact_old_messages(
        self, db: AsyncSession, redis, conversation_id: int, overflow: int
    ) -> None:
        """Fold the oldest `overflow` messages of the active window into the
        rolling summary, persist summary + memory, then drop them from Redis."""
        try:
            key = self._redis_key(conversation_id)
            raw = await redis.lrange(key, 0, overflow - 1)
            messages = []
            for item in raw:
                try:
                    messages.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    continue
            if not messages:
                return

            transcript = "\n".join(
                f"{m.get('role', 'user')}: {str(m.get('content', '')).strip()}"
                for m in messages
            )

            conv = await db.get(Conversation, conversation_id)
            existing = conv.summary if conv else None
            parsed = await self._call_summary_llm(existing or "", transcript)
            if not parsed:
                return

            merged = self._merge_summary_piece(existing, parsed)
            if conv and merged:
                conv.summary = merged
                await db.commit()

            customer_key = conv.phone_number if conv else None
            await self._save_memory(db, customer_key, parsed.get("memory") or {})

            await redis.ltrim(key, overflow, -1)
        except Exception as e:
            logger.warning("Summary compaction failed for conv %s: %s", conversation_id, e)

    @staticmethod
    def _merge_summary_piece(existing: str | None, parsed: dict) -> str:
        piece = (parsed.get("summary") or parsed.get("update") or "").strip()
        if not piece:
            return existing or ""
        if existing and existing.strip():
            return f"{existing.strip()}\n{piece}"
        return piece

    async def _call_summary_llm(self, existing_summary: str, transcript: str) -> dict | None:
        payload = {
            "model": settings.ollama_model,
            "prompt": SUMMARY_PROMPT.format(
                existing_summary=existing_summary or "", transcript=transcript
            ),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 512},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                resp = await client.post(OLLAMA_GENERATE_URL, json=payload)
                resp.raise_for_status()
                raw = resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning("Summary LLM call failed: %s", e)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse summary LLM JSON: %s", raw[:200])
            return None

    async def _backfill_from_chat_log(self, db: AsyncSession, conv: Conversation) -> None:
        """Seed a fresh conversation from existing chat_interactions rows."""
        try:
            result = await db.execute(
                select(ChatInteraction)
                .where(ChatInteraction.phone_number == conv.phone_number)
                .order_by(ChatInteraction.created_at.asc())
                .limit(60)
            )
            rows = result.scalars().all()
            if not rows:
                return
            messages: list[dict] = []
            for row in rows:
                if row.thread_messages:
                    for m in row.thread_messages:
                        sender = m.get("sender")
                        text = m.get("text")
                        if sender in ("user", "ai") and text:
                            messages.append(
                                {"role": "user" if sender == "user" else "assistant", "content": text}
                            )
                    continue
                if row.user_text:
                    messages.append({"role": "user", "content": row.user_text})
                if row.response_text:
                    messages.append({"role": "assistant", "content": row.response_text})
            for msg in messages:
                db.add(
                    ConversationMessage(
                        conversation_id=conv.id, role=msg["role"], content=msg["content"]
                    )
                )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("Chat log backfill failed for phone %s", conv.phone_number)