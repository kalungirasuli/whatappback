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
    "where people buy and sell in Uganda. You chat naturally and help buyers find products.\n\n"
    "Personality:\n"
    "- Warm, upbeat, quick-witted. Match the customer's tone (casual stays casual).\n"
    "- Reply like a real WhatsApp chat, not a robot. Short, natural sentences. No canned option lists.\n"
    "- Prices are in UGX (Ugandan shillings).\n\n"
    "Your job:\n"
    "1. Read the customer's WHOLE message and the conversation history.\n"
    "2. Decide: is there enough info to search the product catalog, or should you keep chatting "
    "or ask 1-2 short questions first?\n"
    "3. A photo means SEARCH using the image — never chat without searching when a photo is sent.\n"
    "4. If the customer changes topic or adds details, search for the new thing too.\n\n"
    'Respond with ONE JSON object and nothing else. Format:\n'
    '{"action": "search" or "chat", "search_text": "short clean product phrase", "reply": "your message"}\n\n'
    'Rules:\n'
    '- "search": when the customer clearly wants a product (or sent a photo). '
    'search_text = the product phrase, e.g. "red nike running shoes". '
    'reply = a short friendly line introducing the search (may be an empty string).\n'
    '- "chat": when there is no clear product to search yet. Greet, chat, or ask 1-2 short '
    'questions to narrow it down. reply = your full chat message.\n'
)

PRESENT_PROMPT = (
    "You are Lisa. You searched the catalog and these are the ACTUAL top matches:\n"
    "{results_summary}\n\n"
    "Write a short, natural WhatsApp message presenting these exact products. "
    "Use ONLY the product names and prices listed above — never invent brands, colours, "
    "models or prices. Mention 1-2 top picks exactly as named. Invite them to tap "
    "\"I'm interested\" on a product they like, or tell you what to refine. "
    "2-3 sentences, friendly, no bullet lists."
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

_LOOKS_LIKE_PRODUCT_RE = re.compile(
    r"\b(looking for|search|find|do you have|where can i get|need|want|"
    r"sell me|interested|buy|show me|price|how much|cost|any)\b",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(r"\b(hello|hi|hey|yo|sup|how are you|good (morning|afternoon|evening))\b", re.IGNORECASE)
_HELP_RE = re.compile(r"\b(help|how to|what can i do|how do i|instructions|guide)\b", re.IGNORECASE)

_HISTORY_KEY = "lisa:history:{user_id}"
_HISTORY_LIMIT = 20


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
        user_id: int,
        user_text: str,
        has_image: bool,
        image_note: str = "",
    ) -> AgentTurn:
        history = await self._load_history(redis, user_id)
        user_turn = self.user_turn_text(user_text, has_image, image_note)

        messages = [{"role": "system", "content": LISA_SYSTEM_PROMPT}]
        for h in history[-14:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": user_turn})

        raw = await self._call_ollama(messages)
        return self._parse_decision(raw, user_text, has_image)

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

    async def record_turn(self, redis, user_id: int, user_text: str, reply: str) -> None:
        try:
            key = _HISTORY_KEY.format(user_id=user_id)
            entries = await self._load_history(redis, user_id)
            entries.append({"role": "user", "content": user_text or ""})
            entries.append({"role": "assistant", "content": reply or ""})
            await redis.set(key, json.dumps(entries[-_HISTORY_LIMIT:]))
        except Exception:
            logger.exception("Failed to record Lisa conversation turn")

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

    def _fallback_decision(self, user_text: str, has_image: bool) -> AgentTurn:
        lower = (user_text or "").lower()
        if _HELP_RE.search(lower):
            return AgentTurn(action="chat", reply=_FALLBACK_HELP)
        if _GREETING_RE.search(lower) and not _LOOKS_LIKE_PRODUCT_RE.search(lower):
            return AgentTurn(action="chat", reply=_FALLBACK_GREETING)
        if has_image or _LOOKS_LIKE_PRODUCT_RE.search(lower):
            return AgentTurn(action="search", search_text=(user_text or "").strip())
        return AgentTurn(action="chat", reply=_FALLBACK_ASK)

    async def _load_history(self, redis, user_id: int) -> list[dict]:
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
