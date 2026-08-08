"""Lisa — the conversational sales assistant for whatAppSeller.

Lisa reads the customer's whole message plus conversation history (kept in Redis),
responds naturally (no canned scripts, no caps), and decides when there is enough
context to trigger a real product search. When Ollama is unavailable or the reply
isn't parseable, she falls back to lightweight heuristics so the shop never goes
silent.
"""

import json
import logging
import re

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_CHAT_URL = f"{settings.ollama_url}/api/chat"

LISA_SYSTEM_PROMPT = (
    "You are Lisa, the friendly sales assistant for whatAppSeller — a WhatsApp marketplace "
    "where people buy and sell in Any country but morjarly Uganda. You chat naturally and help buyers find products.\n\n"
    "Personality:\n"
    "- Warm, upbeat, quick-witted. Match the customer's tone (casual stays casual).\n"
    "- Reply like a real WhatsApp chat, not a robot. medium, natural sentences. No canned option lists.\n"
    "- Prices are in UGX (Ugandan shillings).\n\n"
    "Conversation rules:\n"
    "1. Read the customer's WHOLE message, conversation history, and current stage.\n"
    "2. Be conversation-first. Do not search just because someone says 'need', 'want', or names a broad category.\n"
    "3. For vague requests, stay in chat and ask 1-4 useful questions about type, budget, colour, brand, size, or occasion.\n"
    "4. If the customer is answering your earlier questions and the accumulated context now identifies a product plus useful details, search without asking the same question again.\n"
    "5. Search when the customer explicitly asks to find/search/show products, gives a specific request with useful details, or sends a photo.\n"
    "6. A photo always means SEARCH using the image. After results, keep the customer engaged and invite refinement.\n\n"
    'Respond with ONE JSON object and nothing else. Format:\n'
    '{"action": "search" or "chat", "search_text": "short clean product phrase", "reply": "your message"}\n\n'
    'Rules:\n'
    '- "search": only for an explicit product-search request, a sufficiently specific request, or a photo. '
    'search_text = the product phrase, e.g. "red nike running shoes". '
    'reply = a short friendly line introducing the search (may be an empty string).\n'
    '- "chat": for greetings, vague requests, and context gathering. Ask a useful question rather than searching.\n'
)

PRESENT_PROMPT = (
    "You are Lisa. You searched the catalog and these are the ACTUAL top matches:\n"
    "{results_summary}\n\n"
    "Write a medium, natural WhatsApp message presenting these exact products and keep the customer engaged. "
    "Use ONLY the product names and prices listed above — never invent brands, colours, "
    "models or prices. Mention 1-2 top picks exactly as named. Invite them to tap "
    "\"I'm interested\" on a product they like, and ask one natural question about what to refine next. "
    "2-3 sentences, friendly, no bullet lists."
)

OPENING_PROMPT = (
    "You are Lisa. The customer just sent a photo. You briefly see: \"{image_note}\". "
    "They may have also written a message: \"{caption}\".\n\n"
    "Write a SINGLE short, natural WhatsApp message (1 sentence) acknowledging what "
    "you see and that you're searching for them. Warm, casual, no fluff. "
    "Example: \"Nice sedan! Let me find similar cars for you.\" or "
    "\"I can see the shoes — searching now!\" Reply with ONLY the message text."
)

_FALLBACK_GREETING = (
    "Hey! I'm Lisa 👋 Welcome to whatAppSeller. Tell me what you're looking for or send me "
    "a photo, and I'll find it for you from local sellers!"
)

_FALLBACK_HELP = (
    "Here's how I can help, {name} 😊:\n\n"
    "1. Tell me what you want — e.g. 'red shoes under 100k'\n"
    "2. Or send a photo — I'll find similar products\n\n"
    "I'll show matching products with images, prices and sellers."
)

_FALLBACK_ASK = (
    "Hey! What are you looking for today? Describe it (type, colour, budget) or send me "
    "a photo and I'll find it for you."
)

_FALLBACK_CLARIFY = (
    "I can help with that. What kind are you after, and do you have a budget, colour, "
    "brand, size, or occasion in mind?"
)

_EXPLICIT_SEARCH_RE = re.compile(
    r"\b(search|search for|find|find me|show me|show us|look for|looking for|"
    r"where can i get|do you have|send me|give me|locate|browse)\b",
    re.IGNORECASE,
)
_PRODUCT_TERM_RE = re.compile(
    r"\b(car|cars|vehicle|phone|phones|laptop|shoe|shoes|sneaker|shirt|dress|"
    r"trouser|trousers|clothes|furniture|bag|bags|watch|computer|bike|motorcycle)\b",
    re.IGNORECASE,
)
_DETAIL_RE = re.compile(
    r"\b(red|blue|black|white|green|nike|adidas|samsung|iphone|under|below|above|"
    r"over|budget|cheap|expensive|size|small|medium|large|new|used|automatic|manual|"
    r"occasion|work|school|wedding|men|women|male|female|million|k|ugx|shilling)\b",
    re.IGNORECASE,
)
_SEARCH_DETAIL_RE = re.compile(
    r"\b(under|below|above|over|budget|size|k|ugx|million|cheap|expensive)\b|\d",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(r"\b(hello|hi|hey|yo|sup|how are you|good (morning|afternoon|evening))\b", re.IGNORECASE)
_HELP_RE = re.compile(r"\b(help|how to|what can i do|how do i|instructions|guide)\b", re.IGNORECASE)

_HISTORY_KEY = "lisa:history:{user_id}"
_STAGE_KEY = "lisa:stage:{user_id}"
_HISTORY_LIMIT = 20
_DEFAULT_STAGE = "greeting"


class AgentTurn:
    def __init__(
        self,
        action: str,
        reply: str = "",
        search_text: str = "",
        raw: str = "",
    ) -> None:
        self.action = action
        self.reply = reply
        self.search_text = search_text
        self.raw = raw


class LisaAgent:
    def __init__(self) -> None:
        self.model = settings.ollama_model
        self.base_url = settings.ollama_url

    # ---- public API ------------------------------------------------------

    async def decide(
        self,
        redis,
        user_id: int | str,
        user_text: str,
        has_image: bool,
        image_note: str = "",
    ) -> AgentTurn:
        history = await self._load_history(redis, user_id)
        stage = await self._load_stage(redis, user_id)
        user_turn = self.user_turn_text(user_text, has_image, image_note)
        user_turn = f"[Conversation stage: {stage}]\n{user_turn}" if user_turn else f"[Conversation stage: {stage}]"

        messages = [{"role": "system", "content": LISA_SYSTEM_PROMPT}]
        for h in history[-6:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": user_turn})

        raw = await self._call_ollama(messages)
        turn = self._parse_decision(raw, user_text, has_image)

        explicit_search = self._has_explicit_search(user_text)
        context_product = self._history_has_product_term(history)
        specific_request = self._has_specific_request(user_text) or (
            stage in ("gathering", "post_results")
            and context_product
            and bool(_SEARCH_DETAIL_RE.search(user_text or ""))
        )
        context_search_text = self._context_search_text(history, user_text)
        if not has_image and turn.action == "search" and not (explicit_search or specific_request):
            turn = AgentTurn(action="chat", reply=_FALLBACK_CLARIFY, raw=turn.raw)
        elif not has_image and turn.action == "chat" and (explicit_search or specific_request):
            turn = AgentTurn(
                action="search",
                reply=turn.reply,
                search_text=(turn.search_text or context_search_text or user_text or "").strip(),
                raw=turn.raw,
            )
        elif turn.action == "search" and not turn.search_text:
            turn.search_text = context_search_text

        await self._set_stage(redis, user_id, "ready" if turn.action == "search" else "gathering")
        return turn

    async def present_results(self, redis, user_id: int, top_results: list[dict]) -> str:
        if not top_results:
            return ""
        summary = "\n".join(
            f"- {r.get('name') or 'item'} — {r.get('price')} UGX"
            f" ({r.get('merchant_name') or 'a local seller'})"
            for r in top_results[:5]
        )
        messages = [
            {"role": "system", "content": LISA_SYSTEM_PROMPT},
            {"role": "user", "content": PRESENT_PROMPT.format(results_summary=summary)},
        ]
        raw = await self._call_ollama(messages, force_json=False)
        if not raw:
            return ""
        return self._extract_reply_text(raw)

    async def compose_opening(self, image_note: str, caption: str = "") -> str:
        """Write a natural 1-sentence message acknowledging the user's photo."""
        if not image_note:
            return "Let me see what you have there..."
        messages = [
            {"role": "system", "content": LISA_SYSTEM_PROMPT},
            {"role": "user", "content": OPENING_PROMPT.format(
                image_note=image_note, caption=caption or "[no caption]"
            )},
        ]
        raw = await self._call_ollama(messages, force_json=False)
        if not raw:
            return "I can see your image - searching now!"
        text = self._extract_reply_text(raw)
        return text if text else "I can see your image - searching now!"

    async def record_turn(
        self,
        redis,
        user_id: int | str,
        user_text: str,
        reply: str,
        stage: str | None = None,
    ) -> None:
        try:
            key = _HISTORY_KEY.format(user_id=user_id)
            entries = await self._load_history(redis, user_id)
            entries.append({"role": "user", "content": user_text or ""})
            entries.append({"role": "assistant", "content": reply or ""})
            if stage:
                await self._set_stage(redis, user_id, stage)
            await redis.set(key, json.dumps(entries[-_HISTORY_LIMIT:]))
        except Exception:
            logger.exception("Failed to record Lisa conversation turn")

    async def seed_history(self, redis, user_id: int | str, messages: list[dict]) -> None:
        """Rebuild Lisa's fast Redis memory from durable conversation context."""
        try:
            key = _HISTORY_KEY.format(user_id=user_id)
            entries = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]
            if entries:
                await redis.set(key, json.dumps(entries[-_HISTORY_LIMIT:]))
                await self._set_stage(redis, user_id, "gathering")
        except Exception:
            logger.exception("Failed to seed Lisa conversation history")

    # ---- internals -------------------------------------------------------

    def user_turn_text(self, user_text: str, has_image: bool, image_note: str = "") -> str:
        parts: list[str] = []
        if has_image:
            parts.append("[Customer sent a photo]")
            if image_note:
                parts.append(image_note)
        if user_text and user_text.strip():
            parts.append(user_text.strip())
        return "\n".join(parts) if parts else ""

    async def _call_ollama(self, messages: list[dict], force_json: bool = True) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.5, "num_predict": 400},
        }
        if force_json:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                resp = await client.post(OLLAMA_CHAT_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("message", {}).get("content", "")).strip()
        except httpx.ConnectError:
            logger.warning("Ollama not reachable at %s — Lisa using fallback", self.base_url)
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out after %ss — Lisa using fallback", settings.ollama_timeout)
        except Exception as e:
            logger.error("Ollama chat request failed: %s", e)
        return ""

    @staticmethod
    def _extract_reply_text(raw: str) -> str:
        """Best-effort extraction of Lisa's chat text from an LLM response.

        Handles plain text, markdown-fenced JSON, and invalid JSON where the model
        may have left a string field unescaped.
        """
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        if not text:
            return ""

        # Try strict JSON first.
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("reply", "response_text", "text"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                if isinstance(data.get("message"), dict):
                    value = data["message"].get("content")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            return ""
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Fallback: pull the first field value out of a broken JSON object.
        match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if match:
            return match.group(1).replace('\\"', '"').replace("\\n", "\n").strip()
        for key in ("response_text", "text", "message"):
            match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\"', '"').replace("\\n", "\n").strip()

        # Last resort: strip surrounding braces/quotes.
        return text.strip('{}"').strip()

    def _parse_decision(self, raw: str, user_text: str, has_image: bool) -> AgentTurn:
        if raw:
            try:
                data = json.loads(raw)
                action = str(data.get("action") or "").strip().lower()
                if action in ("search", "chat"):
                    reply = str(data.get("reply") or "")
                    search_text = str(data.get("search_text") or "").strip()
                    if action == "search" and not has_image and not search_text:
                        search_text = (user_text or "").strip()
                    if action == "chat" and not reply:
                        reply = _FALLBACK_ASK
                    return AgentTurn(action=action, reply=reply, search_text=search_text, raw=raw)
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("Failed to parse Lisa decision: %s", raw[:200])

        return self._fallback_decision(user_text, has_image)

    @staticmethod
    def _has_explicit_search(user_text: str) -> bool:
        return bool(_EXPLICIT_SEARCH_RE.search(user_text or "") and _PRODUCT_TERM_RE.search(user_text or ""))

    @staticmethod
    def _has_specific_request(user_text: str) -> bool:
        text = user_text or ""
        return bool(_PRODUCT_TERM_RE.search(text) and _DETAIL_RE.search(text))

    @staticmethod
    def _history_has_product_term(history: list[dict]) -> bool:
        return any(
            _PRODUCT_TERM_RE.search(str(entry.get("content") or ""))
            for entry in history
            if entry.get("role") == "user"
        )

    @staticmethod
    def _context_search_text(history: list[dict], user_text: str) -> str:
        parts = [
            str(entry.get("content") or "").strip()
            for entry in history[-8:]
            if entry.get("role") == "user" and str(entry.get("content") or "").strip()
        ]
        if user_text and user_text.strip():
            parts.append(user_text.strip())
        return " ".join(parts)

    def _fallback_decision(self, user_text: str, has_image: bool) -> AgentTurn:
        lower = (user_text or "").lower()
        if _HELP_RE.search(lower):
            return AgentTurn(action="chat", reply=_FALLBACK_HELP)
        if _GREETING_RE.search(lower) and not self._has_explicit_search(lower):
            return AgentTurn(action="chat", reply=_FALLBACK_GREETING)
        if has_image or self._has_explicit_search(lower) or self._has_specific_request(lower):
            return AgentTurn(action="search", search_text=(user_text or "").strip())
        return AgentTurn(action="chat", reply=_FALLBACK_CLARIFY)

    async def _load_stage(self, redis, user_id: int | str) -> str:
        try:
            stage = await redis.get(_STAGE_KEY.format(user_id=user_id))
            return stage or _DEFAULT_STAGE
        except Exception:
            return _DEFAULT_STAGE

    async def _set_stage(self, redis, user_id: int | str, stage: str) -> None:
        try:
            await redis.set(_STAGE_KEY.format(user_id=user_id), stage)
        except Exception:
            logger.exception("Failed to save Lisa conversation stage")

    async def _load_history(self, redis, user_id: int | str) -> list[dict]:
        try:
            raw = await redis.get(_HISTORY_KEY.format(user_id=user_id))
        except Exception:
            logger.exception("Failed to read Lisa conversation history")
            return []
        if not raw:
            return []
        try:
            entries = json.loads(raw)
            return entries if isinstance(entries, list) else []
        except (json.JSONDecodeError, ValueError, TypeError):
            return []
