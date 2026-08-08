import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_GENERATE_URL = f"{settings.ollama_url}/api/generate"

_TYPE_NORMALIZE = {
    "product search intent": "product_search",
    "visual search intent": "visual_search",
    "general question": "general_question",
}

def _normalize_type(raw: str) -> str:
    key = raw.strip().lower()
    return _TYPE_NORMALIZE.get(key, raw.strip())


@dataclass
class SearchIntent:
    type: str  # visual_search | product_search | general_question | greeting | help | chat | unknown
    description: str = ""
    entities: dict[str, Any] = field(default_factory=dict)


NLU_SYSTEM_PROMPT = """You are the intent classifier for whatAppseller's marketplace chat assistant.

Do NOT rely on keyword hints like "find", "need", "want", "buy" or "search".
Judge the TONE of the current message together with the conversation history:
is this customer NOW asking for a product search, or are they just talking
(confirming, reacting, asking questions, small talk)?

Valid intent types (use EXACTLY these values, no spaces or extra words):
- "visual_search"
- "product_search"
- "general_question"
- "greeting"
- "help"
- "chat"

Classify like a human would:
- "product_search": the message is a genuine, concrete request to FIND products — a
  new request or a refinement of an existing one ("show me more like that", "blue ones",
  "under 100k", "size 8"). It is time to run a search.
- "visual_search": an image is attached and the customer wants similar products.
- "general_question": any question that does NOT ask for a new list — product details,
  price, delivery, shipping, payments, policies ("how much is the phone?").
- "chat": confirmations, reactions and small talk with NO new product request — "ok",
  "yes", "thanks", "nice", "sure", "that works", "tell me more about it".
- "greeting": greetings.
- "help": asking how the service works.

Examples:
- "I need a phone under 500k" → type: "product_search"
- "Hello" → type: "greeting"
- "Can I pay with Mobile Money?" → type: "general_question"
- [image] → type: "visual_search"
- "Thanks!" → type: "chat"
- "What can I do?" → type: "help"
- "ok" after seeing results → type: "chat" (do NOT re-search)
- "show me more like that" → type: "product_search" (new refinement)
- "How much is it?" after a search → type: "general_question"

A single message may contain MULTIPLE intents. For example:
- [SHOE IMAGE] + "Also do you have blue shirts?" = visual_search + product_search
- "I need a phone and also a case" = product_search + product_search

For product_search, extract generic entities for ANY product or item:
- product_name or item_type: the item described; do not restrict it to a fixed category list
- brand, model, variant
- color, gender, size, material, style, condition, occasion
- specifications: an object for arbitrary details such as ram, storage, capacity, year, dimensions
- price_min: minimum price (number, in UGX)
- price_max: maximum price (number, in UGX)
- location: location mentioned (e.g. Kampala)
- normalized_query: a clean search phrase containing the important item and attributes

Preserve unknown names and attributes exactly when you cannot classify them. Do not invent missing values.

CONTEXT RULES (important):
- You are given the ENTIRE conversation history as a JSON array (oldest first),
  plus an "Earlier conversation summary" of anything older than the window,
  durable facts about the customer, and shop context when present.
- Treat the whole history as your memory — behave like a human assistant who
  remembers the full chat. The customer may refer back to products, colours,
  prices or details they mentioned earlier (e.g. "under 100k" keeps the product
  and colour from an earlier message).
- For each intent, fill in entity fields that are implied by the conversation
  (for example when the current message says "show me more like that", carry over
  the product type, colour, and budget from earlier turns).
- Use the summary and memory to disambiguate: do not ask for already-known
  details, do not re-extract settled facts, and never invent a product, colour,
  or price that was not mentioned.

Respond with valid JSON only, no other text. Output format:
{
  "intents": [
    {
      "type": "visual_search",
      "description": "description of what they're looking for",
      "entities": {
        "product_name": "",
        "item_type": "",
        "brand": "",
        "model": "",
        "attributes": {},
        "specifications": {},
        "price_min": null,
        "price_max": null,
        "location": "",
        "normalized_query": ""
      }
    }
  ]
}

For has_image=true, ALWAYS include at least one visual_search intent to handle the image."""


@dataclass
class LLMNLUResult:
    intents: list[SearchIntent] = field(default_factory=list)
    raw_response: str = ""


class LLMNLUService:
    async def extract(
        self,
        text: str,
        has_image: bool = False,
        history: list[dict] | None = None,
        context: dict | None = None,
    ) -> LLMNLUResult:
        # The entire conversation, joined into ONE object attached to the request.
        messages = context.get("messages") if context else None
        if messages is None:
            messages = history or []
        summary = (context or {}).get("summary")
        memory = (context or {}).get("memory")
        shop = (context or {}).get("shop")

        context_block = self._build_context_block(messages, summary, memory, shop)

        user_message = f"{context_block}User message: {text}\nHas image: {has_image}"
        payload = {
            "model": settings.ollama_model,
            "prompt": f"{NLU_SYSTEM_PROMPT}\n\n{user_message}",
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                resp = await client.post(OLLAMA_GENERATE_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("response", "").strip()
        except httpx.ConnectError:
            logger.warning("Ollama not reachable at %s", settings.ollama_url)
            return LLMNLUResult(raw_response="")
        except httpx.TimeoutException:
            logger.warning("Ollama request timed out after %ss", settings.ollama_timeout)
            return LLMNLUResult(raw_response="")
        except Exception as e:
            logger.error("Ollama request failed: %s", e)
            return LLMNLUResult(raw_response="")

        parsed = self._parse_response(raw, text, has_image)
        parsed.raw_response = raw
        return parsed

    @staticmethod
    def _build_context_block(
        history: list[dict],
        summary: str | None = None,
        memory: dict | None = None,
        shop: dict | None = None,
    ) -> str:
        """Render the entire conversation (plus summary/memory/shop) as one block."""
        parts: list[str] = []

        if history:
            turns = [
                {"role": ("customer" if m.get("role") == "user" else "assistant"),
                 "content": str(m.get("content") or "").strip()}
                for m in history
            ]
            turns = [t for t in turns if t["content"]]
            if turns:
                parts.append("Conversation history (entire chat, oldest first) as one JSON object:\n"
                             + json.dumps(turns, ensure_ascii=False))

        if summary:
            parts.append(f"Earlier conversation summary:\n{summary}")

        if memory:
            facts = [f"- {k}: {v}" for k, v in memory.items() if k and v is not None]
            if facts:
                parts.append("Customer memory (durable facts):\n" + "\n".join(facts))

        if shop:
            shop_lines = []
            for key in ("business_name", "category"):
                if shop.get(key):
                    shop_lines.append(f"- {key.replace('_', ' ')}: {shop[key]}")
            products = shop.get("products") or []
            if products:
                shop_lines.append("- Top products: " + ", ".join(
                    f"{p.get('name')}" for p in products[:5]
                ))
            if shop_lines:
                parts.append("Shop context:\n" + "\n".join(shop_lines))

        if not parts:
            return ""
        return "\n\n".join(parts) + "\n\n"

    def _parse_response(self, raw: str, text: str, has_image: bool) -> LLMNLUResult:
        if not raw:
            return LLMNLUResult()

        try:
            data = json.loads(raw)
            raw_intents = data.get("intents", [data])
            intents = []
            for ri in raw_intents:
                if not isinstance(ri, dict):
                    continue
                intent_type = _normalize_type(ri.get("type", "unknown"))
                intents.append(SearchIntent(
                    type=intent_type,
                    description=ri.get("description", ""),
                    entities=ri.get("entities", {}),
                ))

            if not intents:
                return LLMNLUResult()

            return LLMNLUResult(intents=intents)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Ollama JSON response: %s", raw[:200])
            return LLMNLUResult()
