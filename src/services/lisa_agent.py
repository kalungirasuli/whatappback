
"""
Lisa — conversational sales agent for WhatAppSeller.

Lisa is responsible for:
- understanding the current customer message in conversation context;
- deciding whether the application needs product retrieval;
- producing a natural conversational response;
- preserving conversational state.

IMPORTANT:
Lisa does not use keyword-based rules to determine intent.

The LLM is the semantic decision maker.

Python is responsible only for:
- loading/storing conversation state;
- calling Ollama;
- validating structured output;
- safely handling infrastructure failures.

Conversation state is scoped by conversation_id and shop_id.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.config import settings


logger = logging.getLogger(__name__)

OLLAMA_CHAT_URL = f"{settings.ollama_url}/api/chat"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

LISA_SYSTEM_PROMPT = """
You are Lisa, the conversational sales assistant for WhatAppSeller.

WhatAppSeller is a marketplace where customers talk naturally with sellers
through an AI sales assistant.

Your job is to understand what the customer means and decide what should
happen next.

You are NOT a keyword classifier.

Do not use words such as "want", "need", "find", "show", "buy", "search",
"phone", "shoe", etc. as automatic triggers.

Interpret the customer's meaning using the current message and the
conversation context.

==================================================
CONVERSATIONAL MEMORY
==================================================

You receive the conversation history and possibly:

- an earlier conversation summary;
- durable customer memory;
- shop/business context;
- previous search context;
- previous search results.

Treat these as conversational memory.

The customer may refer to something without repeating it.

Examples:

Customer:
"I need black Nike shoes under 200k."

Assistant:
"Here are some options."

Customer:
"Show me cheaper ones."

Understand that "ones" refers to the shoes and that the customer wants
another product search using the existing context.

Customer:
"How much is the second one?"

This is NOT a new product search. The customer is asking about a product
already identified in the conversation.

Customer:
"Same but blue."

This is a refinement of the existing product request and requires a search.

Customer:
"Okay, I like that."

This is conversational acknowledgement and does not require a search.

==================================================
CURRENT INTENT
==================================================

Decide what the customer is trying to accomplish NOW.

Possible actions:

"search"
"chat"

Use "search" when fulfilling the customer's request requires retrieving
products from the catalogue.

Use "chat" when the request can be handled conversationally without product
retrieval.

Do not decide based only on the current sentence.

==================================================
SEARCH
==================================================

A search can be:

- a completely new product request;
- a refinement of an existing search;
- a request for alternatives;
- a request for similar products;
- a request for another colour/size/model/brand;
- a request for products matching an image;
- a request to find something already discussed.

When searching, construct search_text using ALL relevant information that
has been established by the conversation.

For example:

Earlier:
"I need a black 18-inch human hair wig."

Current:
"Show me cheaper ones."

The search_text should preserve the established product context while
changing the relevant constraint.

Do not throw away information simply because the customer did not repeat it.

==================================================
DO NOT SEARCH
==================================================

Do not search merely because a product was mentioned.

Examples:

"What is the price of the phone?"

"Is this phone new?"

"Can I pay by Mobile Money?"

"How long does delivery take?"

These can be handled conversationally if no retrieval is required.

Likewise:

"thanks"
"okay"
"nice"
"yes"
"that works"

are conversational unless the surrounding context clearly indicates that
the customer is requesting another action.

==================================================
IMPLICIT REFERENCES
==================================================

Resolve references from conversation context.

Examples:

- "it"
- "that"
- "this one"
- "the first one"
- "the second one"
- "those"
- "same one"
- "another"
- "more like that"
- "cheaper"
- "bigger"
- "smaller"
- "another colour"

If the reference is clear, use it.

If it is ambiguous, do not invent information.

==================================================
MULTIPLE REQUESTS
==================================================

A message may contain multiple actions.

Example:

"I like the first phone. How much is it, and show me similar ones."

Interpret the message semantically.

If product retrieval is required, action should be "search".

The response should still naturally address the customer's question rather
than blindly triggering a search.

==================================================
IMAGE
==================================================

An image does not automatically mean search.

Understand the relationship between the image and the customer's text.

For example:

Image + "find something similar"
=> search

Image + "what colour is this?"
=> chat

Image + "thanks"
=> chat

If the image is relevant to product discovery, include that information in
search_text.

==================================================
RESPONSE STYLE
==================================================

Reply like a real WhatsApp salesperson.

Be:

- warm;
- natural;
- concise;
- conversational;
- helpful.

Do not use canned scripts.

Do not unnecessarily ask questions when enough information already exists.

Do not ask for information that the customer has already provided.

If the customer has provided enough information to search, search.

If important information is genuinely missing and a search cannot reasonably
be performed, ask ONE useful question.

==================================================
SEARCH TEXT
==================================================

search_text must be a concise semantic representation of the customer's
current product request.

It should preserve relevant information from previous turns.

Example:

Conversation:
"I need a Toyota Premio."
"2018 or newer."
"Automatic."
"Under 40 million."

Current:
"Show me some."

search_text:

"Toyota Premio 2018 or newer automatic under 40 million UGX"

Do not include irrelevant conversation.

Do not invent missing attributes.

==================================================
NEVER ASSUME DETAILS
==================================================

search_text and reply must contain ONLY:

- words the customer actually said, or
- facts genuinely established earlier in this conversation.

Never add a product category, brand, size, colour, model, quantity, or any
detail that the customer did not mention and that is not already established
in the conversation.

Example:

Customer:
"find me blackskys"

search_text MUST be:

"black sky"

It MUST NOT be "black sky shoes". The word "shoes" was never mentioned or
established, so it must never be added.

Likewise, do not ask about size, colour, budget, or delivery before results
are presented unless the customer raised it themselves.

==================================================
OUTPUT
==================================================

Return valid JSON only.

Format:

{
    "action": "search" | "chat",

    "search_text": "",

    "reply": "",

    "interpretation": "",

    "references": [],

    "confidence": 0.0
}

Definitions:

action:
The action required NOW.

search_text:
Only relevant when action="search".

reply:
The natural response to the customer.

interpretation:
A short semantic explanation for application observability.
Do NOT expose hidden chain-of-thought.

references:
Important previous conversation entities resolved for this turn.

confidence:
A number between 0 and 1 representing confidence in the interpretation.

Do not add fields.

Do not use markdown.

Do not output reasoning or chain-of-thought.
"""


PRESENT_PROMPT = """
You are Lisa, a conversational sales assistant.

The catalogue search has already been performed.

These are the ACTUAL products returned:

{results_summary}

Present these products naturally.

Rules:

- Use only product names and prices provided above.
- Never invent brands, colours, models, availability or prices.
- Mention one or two strong matches.
- Do not repeat product names.
- If the results already satisfy the customer's request, do not ask them to
  refine the search.
- Move the conversation naturally toward the next useful action.
- Ask at most one short question when appropriate.
- Keep the response to 2-3 natural WhatsApp sentences.
- Do not use bullet lists.
"""


OPENING_PROMPT = """
You are Lisa.

The customer sent an image.

Image description:
"{image_note}"

Customer message:
"{caption}"

Write one short natural WhatsApp message acknowledging the image and
explaining what you will do next.

Do not invent details that are not present in the image description.

Return only the message text.
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentTurn:
    action: str
    reply: str = ""
    search_text: str = ""
    interpretation: str = ""
    references: list[str] | None = None
    confidence: float = 0.0
    raw: str = ""

    def __post_init__(self) -> None:
        if self.references is None:
            self.references = []


# ---------------------------------------------------------------------------
# Redis keys
# ---------------------------------------------------------------------------

_HISTORY_KEY = "lisa:history:{shop_id}:{conversation_id}"
_STATE_KEY = "lisa:state:{shop_id}:{conversation_id}"

_HISTORY_LIMIT = 30


class LisaAgent:
    """
    Conversational sales agent.

    IMPORTANT:
    This class deliberately contains no regex-based intent detection.

    The LLM determines whether the customer needs a search.
    """

    def __init__(self) -> None:
        self.model = settings.ollama_model
        self.base_url = settings.ollama_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def decide(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
        user_text: str,
        has_image: bool = False,
        image_note: str = "",
        summary: str | None = None,
        memory: dict[str, Any] | None = None,
        shop_context: dict[str, Any] | None = None,
    ) -> AgentTurn:
        """
        Interpret the current message using the conversation as memory.

        There is intentionally no Python semantic fallback.
        """

        history = await self._load_history(
            redis,
            conversation_id=conversation_id,
            shop_id=shop_id,
        )

        state = await self._load_state(
            redis,
            conversation_id=conversation_id,
            shop_id=shop_id,
        )

        current_message = self._build_user_message(
            user_text=user_text,
            has_image=has_image,
            image_note=image_note,
        )

        messages = [
            {
                "role": "system",
                "content": LISA_SYSTEM_PROMPT,
            }
        ]

        context = self._build_context(
            history=history,
            state=state,
            summary=summary,
            memory=memory,
            shop_context=shop_context,
        )

        if context:
            messages.append(
                {
                    "role": "system",
                    "content": context,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": current_message,
            }
        )

        raw = await self._call_ollama(
            messages,
            force_json=True,
        )

        if not raw:
            # This is an infrastructure failure, NOT an intent decision.
            #
            # Do not call a regex classifier here.
            #
            # The caller can retry, queue the message, or return a generic
            # temporary failure response.
            return AgentTurn(
                action="chat",
                reply=(
                    "I'm having a little trouble connecting right now. "
                    "Please give me a moment and try again."
                ),
                confidence=0.0,
            )

        turn = self._parse_decision(raw)

        if turn is None:
            return AgentTurn(
                action="chat",
                reply=(
                    "I didn't quite catch that. "
                    "Could you say that another way?"
                ),
                confidence=0.0,
                raw=raw,
            )

        return turn

    async def present_results(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
        top_results: list[dict],
        summary: str | None = None,
        memory: dict[str, Any] | None = None,
        shop_context: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate a natural response from actual catalogue results.
        """

        if not top_results:
            return ""

        results_summary = "\n".join(
            (
                f"- {result.get('name') or 'item'} — "
                f"{result.get('price')} UGX "
                f"({result.get('merchant_name') or 'a local seller'})"
            )
            for result in top_results[:5]
        )

        history = await self._load_history(
            redis,
            conversation_id=conversation_id,
            shop_id=shop_id,
        )

        messages = [
            {
                "role": "system",
                "content": LISA_SYSTEM_PROMPT,
            }
        ]

        context = self._build_context(
            history=history,
            state={},
            summary=summary,
            memory=memory,
            shop_context=shop_context,
        )

        if context:
            messages.append(
                {
                    "role": "system",
                    "content": context,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": PRESENT_PROMPT.format(
                    results_summary=results_summary,
                ),
            }
        )

        raw = await self._call_ollama(
            messages,
            force_json=False,
        )

        if not raw:
            return self._fallback_present(top_results)

        reply = self._extract_reply_text(raw)

        return reply or self._fallback_present(top_results)

    async def compose_opening(
        self,
        image_note: str,
        caption: str = "",
    ) -> str:
        """
        Generate a natural acknowledgement for an image.
        """

        if not image_note:
            return "Let me take a look at that for you."

        messages = [
            {
                "role": "system",
                "content": LISA_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": OPENING_PROMPT.format(
                    image_note=image_note,
                    caption=caption or "[no caption]",
                ),
            },
        ]

        raw = await self._call_ollama(
            messages,
            force_json=False,
        )

        if not raw:
            return "I can see your image. Let me take a look."

        return (
            self._extract_reply_text(raw)
            or "I can see your image. Let me take a look."
        )

    async def record_turn(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
        user_text: str,
        reply: str,
        state: dict[str, Any] | None = None,
    ) -> None:
        """
        Persist the conversation in Redis.

        Redis is the fast working memory.
        Durable conversation storage should still live in your database.
        """

        try:
            key = self._history_key(
                shop_id=shop_id,
                conversation_id=conversation_id,
            )

            entries = await self._load_history(
                redis,
                conversation_id=conversation_id,
                shop_id=shop_id,
            )

            if user_text:
                entries.append(
                    {
                        "role": "user",
                        "content": user_text,
                    }
                )

            if reply:
                entries.append(
                    {
                        "role": "assistant",
                        "content": reply,
                    }
                )

            await redis.set(
                key,
                json.dumps(
                    entries[-_HISTORY_LIMIT:],
                    ensure_ascii=False,
                ),
            )

            if state is not None:
                await self._set_state(
                    redis,
                    conversation_id=conversation_id,
                    shop_id=shop_id,
                    state=state,
                )

        except Exception:
            logger.exception(
                "Failed to record Lisa conversation turn"
            )

    async def seed_history(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
        messages: list[dict],
    ) -> None:
        """
        Restore Redis working memory from durable conversation storage.
        """

        try:
            entries = []

            for message in messages:
                role = message.get("role", "user")
                content = str(message.get("content") or "").strip()

                if content:
                    entries.append(
                        {
                            "role": role,
                            "content": content,
                        }
                    )

            if not entries:
                return

            await redis.set(
                self._history_key(
                    shop_id=shop_id,
                    conversation_id=conversation_id,
                ),
                json.dumps(
                    entries[-_HISTORY_LIMIT:],
                    ensure_ascii=False,
                ),
            )

        except Exception:
            logger.exception(
                "Failed to seed Lisa conversation history"
            )

    # ------------------------------------------------------------------
    # Context construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        history: list[dict],
        state: dict[str, Any],
        summary: str | None,
        memory: dict[str, Any] | None,
        shop_context: dict[str, Any] | None,
    ) -> str:
        sections: list[str] = []

        if history:
            sections.append(
                "CONVERSATION HISTORY:\n"
                + json.dumps(
                    history,
                    ensure_ascii=False,
                )
            )

        if summary:
            sections.append(
                "EARLIER CONVERSATION SUMMARY:\n"
                + str(summary)
            )

        if memory:
            sections.append(
                "CUSTOMER MEMORY:\n"
                + json.dumps(
                    memory,
                    ensure_ascii=False,
                )
            )

        if state:
            sections.append(
                "CURRENT CONVERSATION STATE:\n"
                + json.dumps(
                    state,
                    ensure_ascii=False,
                )
            )

        if shop_context:
            sections.append(
                "SHOP CONTEXT:\n"
                + json.dumps(
                    shop_context,
                    ensure_ascii=False,
                )
            )

        if not sections:
            return ""

        return (
            "Use the following information as conversational context. "
            "Do not treat old conversation as the customer's current request "
            "unless the current message refers to it.\n\n"
            + "\n\n".join(sections)
        )

    @staticmethod
    def _build_user_message(
        user_text: str,
        has_image: bool,
        image_note: str,
    ) -> str:
        parts: list[str] = []

        if has_image:
            parts.append(
                "CUSTOMER ATTACHED AN IMAGE."
            )

            if image_note:
                parts.append(
                    f"IMAGE DESCRIPTION:\n{image_note}"
                )

        if user_text and user_text.strip():
            parts.append(
                f"CURRENT CUSTOMER MESSAGE:\n{user_text.strip()}"
            )

        if not parts:
            return "The customer sent an empty message."

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    async def _call_ollama(
        self,
        messages: list[dict],
        force_json: bool = True,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 600,
            },
        }

        if force_json:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(
                timeout=settings.ollama_timeout,
            ) as client:
                response = await client.post(
                    OLLAMA_CHAT_URL,
                    json=payload,
                )

                response.raise_for_status()

                data = response.json()

                return str(
                    data.get("message", {}).get("content", "")
                ).strip()

        except httpx.ConnectError:
            logger.warning(
                "Ollama not reachable at %s",
                self.base_url,
            )

        except httpx.TimeoutException:
            logger.warning(
                "Ollama request timed out after %ss",
                settings.ollama_timeout,
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama returned HTTP %s: %s",
                exc.response.status_code,
            )

        except Exception:
            logger.exception(
                "Ollama chat request failed"
            )

        return ""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decision(
        raw: str,
    ) -> AgentTurn | None:
        """
        Validate the model's semantic decision.

        This method MUST NOT infer intent.

        It only accepts/rejects the model's decision.
        """

        if not raw:
            return None

        try:
            data = json.loads(raw)

        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning(
                "Failed to parse Lisa decision: %s",
                raw[:500],
            )
            return None

        if not isinstance(data, dict):
            return None

        action = str(
            data.get("action") or ""
        ).strip().lower()

        if action not in {"search", "chat"}:
            logger.warning(
                "Lisa returned invalid action: %s",
                action,
            )
            return None

        search_text = str(
            data.get("search_text") or ""
        ).strip()

        reply = str(
            data.get("reply") or ""
        ).strip()

        interpretation = str(
            data.get("interpretation") or ""
        ).strip()

        references = data.get("references")

        if not isinstance(references, list):
            references = []

        references = [
            str(value)
            for value in references
            if value
        ]

        try:
            confidence = float(
                data.get("confidence", 0.0)
            )
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(
            0.0,
            min(1.0, confidence),
        )

        # Do not manufacture search_text here.
        #
        # If the model says "search" but does not provide a query,
        # that is an invalid/incomplete model decision.
        #
        # The application should not silently replace it with the latest
        # user sentence because doing so destroys conversational context.
        if action == "search" and not search_text:
            logger.warning(
                "Lisa requested search without search_text"
            )
            return None

        return AgentTurn(
            action=action,
            reply=reply,
            search_text=search_text,
            interpretation=interpretation,
            references=references,
            confidence=confidence,
            raw=raw,
        )

    @staticmethod
    def _extract_reply_text(raw: str) -> str:
        """
        Extract conversational text from an LLM response.

        This is formatting/parsing only.
        It does not determine intent.
        """

        if not raw:
            return ""

        text = raw.strip()

        try:
            data = json.loads(text)

            if isinstance(data, dict):
                for key in (
                    "reply",
                    "response_text",
                    "text",
                ):
                    value = data.get(key)

                    if isinstance(value, str) and value.strip():
                        return value.strip()

                message = data.get("message")

                if isinstance(message, dict):
                    content = message.get("content")

                    if (
                        isinstance(content, str)
                        and content.strip()
                    ):
                        return content.strip()

        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        return text.strip()

    # ------------------------------------------------------------------
    # Safe result fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_present(
        top_results: list[dict],
    ) -> str:
        """
        Deterministic presentation fallback.

        This is acceptable because it is NOT making an intent decision.

        It simply reports actual catalogue results when the response
        generation model is unavailable.
        """

        products = []

        for result in top_results[:3]:
            name = str(
                result.get("name") or "item"
            ).strip()

            price = result.get("price")

            if price is not None:
                products.append(
                    f"{name} — {price} UGX"
                )
            else:
                products.append(name)

        if not products:
            return ""

        if len(products) == 1:
            return (
                f"I found {products[0]} for you. "
                "Would you like to know more about it?"
            )

        return (
            "I found these options for you: "
            + ", ".join(products)
            + ". Let me know which one you like."
        )

    # ------------------------------------------------------------------
    # Redis state
    # ------------------------------------------------------------------

    @staticmethod
    def _history_key(
        shop_id: int | str,
        conversation_id: str,
    ) -> str:
        return _HISTORY_KEY.format(
            shop_id=shop_id,
            conversation_id=conversation_id,
        )

    @staticmethod
    def _state_key(
        shop_id: int | str,
        conversation_id: str,
    ) -> str:
        return _STATE_KEY.format(
            shop_id=shop_id,
            conversation_id=conversation_id,
        )

    async def _load_history(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
    ) -> list[dict]:
        try:
            raw = await redis.get(
                self._history_key(
                    shop_id=shop_id,
                    conversation_id=conversation_id,
                )
            )

        except Exception:
            logger.exception(
                "Failed to read Lisa conversation history"
            )
            return []

        if not raw:
            return []

        try:
            entries = json.loads(raw)

        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning(
                "Invalid Lisa conversation history in Redis"
            )
            return []

        return entries if isinstance(entries, list) else []

    async def _load_state(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
    ) -> dict[str, Any]:
        try:
            raw = await redis.get(
                self._state_key(
                    shop_id=shop_id,
                    conversation_id=conversation_id,
                )
            )

        except Exception:
            logger.exception(
                "Failed to read Lisa conversation state"
            )
            return {}

        if not raw:
            return {}

        try:
            state = json.loads(raw)

        except (json.JSONDecodeError, ValueError, TypeError):
            return {}

        return state if isinstance(state, dict) else {}

    async def _set_state(
        self,
        redis,
        conversation_id: str,
        shop_id: int | str,
        state: dict[str, Any],
    ) -> None:
        try:
            await redis.set(
                self._state_key(
                    shop_id=shop_id,
                    conversation_id=conversation_id,
                ),
                json.dumps(
                    state,
                    ensure_ascii=False,
                ),
            )

        except Exception:
            logger.exception(
                "Failed to save Lisa conversation state"
            )

