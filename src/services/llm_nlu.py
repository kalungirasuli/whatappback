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


NLU_SYSTEM_PROMPT = """You are a product search intent classifier for a marketplace called whatAppseller. Use ONLY the exact intent type names listed below.

Analyze the user's message and the has_image flag. Determine what they want:

Valid intent types (use EXACTLY these values, no spaces or extra words):
- "visual_search"
- "product_search"
- "general_question"
- "greeting"
- "help"
- "chat"

Examples:
- "I need a phone under 500k" → type: "product_search"
- "Hello" → type: "greeting"
- "Can I pay with Mobile Money?" → type: "general_question"
- [image] → type: "visual_search"
- "Thanks!" → type: "chat"
- "What can I do?" → type: "help"

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

Preserve unknown product names and attributes exactly when you cannot classify them. Do not invent missing values.

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
    async def extract(self, text: str, has_image: bool = False) -> LLMNLUResult:
        user_message = f"User message: {text}\nHas image: {has_image}"
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
