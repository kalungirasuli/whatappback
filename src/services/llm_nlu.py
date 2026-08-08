
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.core.config import settings


logger = logging.getLogger(__name__)

OLLAMA_GENERATE_URL = f"{settings.ollama_url}/api/generate"


VALID_INTENTS = {
    "visual_search",
    "product_search",
    "general_question",
    "greeting",
    "help",
    "chat",
}


@dataclass
class SearchIntent:
    """
    Semantic interpretation of the user's current message.

    The NLU is responsible for understanding what the customer means.
    It should NOT be used as a collection of keyword/rule-based decisions.
    """

    type: str
    description: str = ""
    entities: dict[str, Any] = field(default_factory=dict)

    # Whether this interpretation requires the product/visual search pipeline.
    needs_search: bool = False

    # Short semantic explanation useful for debugging/observability.
    interpretation: str = ""

    # References resolved from previous conversation turns.
    references: list[str] = field(default_factory=list)

    # Literal text to send to the search engine verbatim. When set, it is the
    # authoritative search query (the customer's own words) and the search is
    # NOT rebuilt from extracted entities.
    query: str = ""


@dataclass
class LLMNLUResult:
    intents: list[SearchIntent] = field(default_factory=list)
    raw_response: str = ""


NLU_SYSTEM_PROMPT = """
You are the semantic understanding layer for WhatAppSeller, an AI marketplace
assistant.

Your job is NOT to classify messages using keywords or fixed rules.

Your job is to understand what the customer means by considering:

1. The current message.
2. The entire available conversation.
3. The current conversational state.
4. Earlier conversation summaries.
5. Durable customer memory.
6. Shop/business context.
7. Any attached image.

Think like a human sales assistant who has been following the conversation.

==================================================
CORE PRINCIPLE
==================================================

Interpret meaning, not words.

Words such as:

"want"
"need"
"looking"
"find"
"show"
"get"
"buy"

DO NOT automatically mean product_search.

Likewise, words such as:

"how"
"what"
"which"
"can"
"do"

DO NOT automatically mean general_question.

The surrounding conversation determines the meaning.

Examples are illustrative only. They are NOT rules.

==================================================
CONVERSATIONAL STATE
==================================================

Always determine what the customer is doing NOW.

A message can:

- start a new product request
- refine an existing product request
- continue discussing a previously identified product
- ask a question about a product already being discussed
- acknowledge or react
- change the subject
- ask for help
- greet
- contain multiple independent requests

Do not treat every message as a new task.

For example:

Customer:
"I need black sneakers under 150k."

Assistant:
"Here are some options."

Customer:
"Show me more."

The second message is a product_search because it continues/refines the
existing shopping task.

But:

Customer:
"How much is the first one?"

This is a general_question because the customer is asking about an already
identified product rather than requesting a new product search.

And:

Customer:
"Okay, I like that one."

This is chat unless the customer explicitly asks for another action.

==================================================
REFERENCE RESOLUTION
==================================================

Customers frequently use references instead of repeating information.

Resolve expressions such as:

- "that one"
- "this one"
- "the first one"
- "the second one"
- "the black one"
- "same one"
- "same but blue"
- "another one"
- "more like this"
- "those"
- "them"
- "it"
- "the cheaper one"
- "the other one"

Use the conversation to determine what they refer to.

If the reference can be resolved confidently, carry the relevant information
forward into entities.

Do NOT invent information.

If the reference cannot be resolved confidently, preserve the ambiguity
instead of hallucinating a product.

==================================================
INTENT DEFINITIONS
==================================================

Use one or more of these intent types:

"product_search"
"visual_search"
"general_question"
"greeting"
"help"
"chat"

--------------------------------------------------
product_search
--------------------------------------------------

Use when the customer currently wants the system to find, recommend, filter,
compare, or retrieve products.

This includes:

- new product requests
- refinements of an existing product search
- "show me more"
- "anything cheaper?"
- "same thing in blue"
- "do you have this in size 42?"
- "what other options do you have?"
- requests containing multiple products

The important question is:

"Does fulfilling this message require searching the product catalogue?"

If yes, product_search is usually appropriate.

--------------------------------------------------
visual_search
--------------------------------------------------

Use when an image is part of the customer's request and the meaning of the
request requires visual/product matching.

An image existing by itself does NOT automatically mean visual_search.

Consider the text and image together.

For example:

[image]
"Do you have something similar?"

=> visual_search

[image]
"What color is this?"

=> general_question

[image]
"Thanks"

=> chat

If an image is attached but the customer does not ask for anything related to
the image, do not invent a visual search intent.

--------------------------------------------------
general_question
--------------------------------------------------

Use when the customer wants information rather than a new product retrieval.

Examples include:

- product price
- product details
- availability
- delivery
- payment methods
- warranty
- return policy
- shop information
- questions about a product already identified

The question may still refer to a product from earlier conversation.

--------------------------------------------------
chat
--------------------------------------------------

Use for conversational turns that do not require a business/search action.

Examples:

- acknowledgement
- reaction
- thanks
- confirmation
- casual conversation
- "okay"
- "nice"
- "sure"
- "that works"

Do not turn conversational acknowledgements into searches.

--------------------------------------------------
greeting
--------------------------------------------------

Use when the primary purpose is greeting the assistant.

--------------------------------------------------
help
--------------------------------------------------

Use when the customer is asking how to use the service or what the assistant
can do.

==================================================
MULTIPLE INTENTS
==================================================

A single message can contain multiple independent intents.

For example:

"I like the shoes. How much are they, and show me similar ones."

This contains:

1. general_question
2. product_search

Do not force multiple intents into one classification if the customer is
clearly asking for multiple actions.

==================================================
PRODUCT ENTITY EXTRACTION
==================================================

When product_search or visual_search is appropriate, extract information
that is actually supported by the conversation.

Use this structure where applicable:

{
    "product_name": "",
    "item_type": "",
    "brand": "",
    "model": "",
    "color": "",
    "gender": "",
    "size": "",
    "material": "",
    "style": "",
    "condition": "",
    "occasion": "",
    "attributes": {},
    "specifications": {},
    "price_min": null,
    "price_max": null,
    "location": "",
    "normalized_query": ""
}

The schema is intentionally generic.

Do not restrict products to predefined categories.

Preserve unknown product names, brands, models, specifications, and attributes
when the customer provides them.

Never invent missing values.

If the customer says:

"same one but blue"

and the previous product was:

"18-inch human hair wig"

then carry forward:

- item_type = wig
- length/specification = 18-inch
- material = human hair
- color = blue

Only carry information that is genuinely established by the conversation.

==================================================
PRICE INTERPRETATION
==================================================

Convert explicit prices into numbers when the currency/context is known.

For example:

"under 100k"
=> price_max = 100000

"between 100k and 200k"
=> price_min = 100000
=> price_max = 200000

Do not invent a currency or price when it is not supported by the context.

==================================================
CONTEXT PRIORITY
==================================================

When resolving meaning, use this priority:

1. Current message
2. Most recent relevant conversation turns
3. Current conversation state
4. Earlier conversation summary
5. Durable customer memory
6. Shop context

Recent relevant conversation should generally matter more than unrelated
older conversation.

Do not allow an old topic to override an explicit new request.

For example:

Earlier:
"I want black shoes."

Later:
"Actually, forget the shoes. I need a red dress."

The current request is about a red dress.

==================================================
NO RULE-BASED FALLBACK
==================================================

Do not create an intent merely because a word appears in the message.

Do not use keyword matching.

Do not assume that short messages are chat.

Use conversation context to interpret short messages.

For example:

After:
"Here are three phones."

"the second one"

=> general_question or product_search depending on what the customer is asking.

After:
"Here are three phones."

"show me more like the second one"

=> product_search.

After:
"Here are three phones."

"how much is the second one?"

=> general_question.

==================================================
OUTPUT
==================================================

Return valid JSON only.

The response MUST have this structure:

{
    "intents": [
        {
            "type": "product_search",
            "description": "What the customer is trying to accomplish",
            "interpretation": "Short explanation of how the current message relates to the conversation",
            "needs_search": true,
            "references": [],
            "entities": {
                "product_name": "",
                "item_type": "",
                "brand": "",
                "model": "",
                "color": "",
                "gender": "",
                "size": "",
                "material": "",
                "style": "",
                "condition": "",
                "occasion": "",
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

The "needs_search" field means:

true:
The application needs to retrieve/search products to satisfy this intent.

false:
The application can satisfy this intent without product retrieval.

The "interpretation" field is for semantic observability and debugging.
Keep it concise.

The "references" field should contain important references resolved from the
conversation, such as:

["previous product", "second result", "previous budget"]

Do not expose hidden chain-of-thought or detailed internal reasoning.
Provide only a concise semantic interpretation.

Return [] only when the message cannot reasonably be interpreted.

Do not add fields outside the defined structure.
"""


class LLMNLUService:
    async def extract(
        self,
        text: str,
        has_image: bool = False,
        history: list[dict] | None = None,
        context: dict | None = None,
    ) -> LLMNLUResult:
        """
        Interpret the current customer message using the conversation as state.

        This method deliberately contains no keyword-based intent fallback.
        If the LLM cannot be reached or produces invalid output, the caller
        receives an empty result and can decide how the application should
        handle the failure.
        """

        context = context or {}

        messages = context.get("messages")
        if messages is None:
            messages = history or []

        summary = context.get("summary")
        memory = context.get("memory")
        shop = context.get("shop")

        context_block = self._build_context_block(
            messages=messages,
            summary=summary,
            memory=memory,
            shop=shop,
        )

        user_message = (
            f"{context_block}"
            f"CURRENT CUSTOMER MESSAGE:\n{text}\n\n"
            f"IMAGE ATTACHED: {has_image}"
        )

        payload = {
            "model": settings.ollama_model,
            "prompt": f"{NLU_SYSTEM_PROMPT}\n\n{user_message}",
            "format": "json",
            "stream": False,
            "options": {
                # Low temperature keeps the interpretation consistent while
                # still allowing the model to reason semantically.
                "temperature": 0.15,
                "num_predict": 768,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.ollama_timeout
            ) as client:
                response = await client.post(
                    OLLAMA_GENERATE_URL,
                    json=payload,
                )

                response.raise_for_status()

                data = response.json()
                raw = str(data.get("response", "")).strip()

        except httpx.ConnectError:
            logger.warning(
                "Ollama not reachable at %s",
                settings.ollama_url,
            )
            return LLMNLUResult()

        except httpx.TimeoutException:
            logger.warning(
                "Ollama request timed out after %ss",
                settings.ollama_timeout,
            )
            return LLMNLUResult()

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama returned HTTP %s: %s",
                exc.response.status_code,
                exc.response.text[:500],
            )
            return LLMNLUResult()

        except Exception:
            logger.exception("Ollama NLU request failed")
            return LLMNLUResult()

        parsed = self._parse_response(raw)

        parsed.raw_response = raw

        if not parsed.intents:
            logger.warning(
                "NLU returned no valid intents. Raw response: %s",
                raw[:500],
            )

        return parsed

    @staticmethod
    def _build_context_block(
        messages: list[dict],
        summary: str | None = None,
        memory: dict | None = None,
        shop: dict | None = None,
    ) -> str:
        """
        Build structured context for the model.

        The context is explicitly separated so the model can distinguish:
        conversation state, durable memory, and business information.
        """

        sections: list[str] = []

        if messages:
            turns = []

            for message in messages:
                content = str(message.get("content") or "").strip()

                if not content:
                    continue

                role = message.get("role")

                if role == "user":
                    role = "customer"
                elif role == "assistant":
                    role = "assistant"
                elif not role:
                    role = "unknown"

                turns.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

            if turns:
                sections.append(
                    "CURRENT CONVERSATION HISTORY "
                    "(oldest first):\n"
                    + json.dumps(
                        turns,
                        ensure_ascii=False,
                    )
                )

        if summary:
            sections.append(
                "EARLIER CONVERSATION SUMMARY:\n"
                + str(summary).strip()
            )

        if memory:
            memory_items = []

            for key, value in memory.items():
                if key and value is not None:
                    memory_items.append(
                        {
                            "fact": str(key),
                            "value": value,
                        }
                    )

            if memory_items:
                sections.append(
                    "CUSTOMER MEMORY:\n"
                    + json.dumps(
                        memory_items,
                        ensure_ascii=False,
                    )
                )

        if shop:
            shop_context: dict[str, Any] = {}

            for key in (
                "business_name",
                "category",
            ):
                if shop.get(key):
                    shop_context[key] = shop[key]

            products = shop.get("products") or []

            if products:
                shop_context["products"] = [
                    {
                        "name": product.get("name"),
                        "category": product.get("category"),
                    }
                    for product in products[:10]
                ]

            if shop_context:
                sections.append(
                    "SHOP CONTEXT:\n"
                    + json.dumps(
                        shop_context,
                        ensure_ascii=False,
                    )
                )

        if not sections:
            return "No previous conversation context is available.\n\n"

        return (
            "\n\n".join(sections)
            + "\n\n"
        )

    @staticmethod
    def _parse_response(raw: str) -> LLMNLUResult:
        """
        Parse and structurally validate the model response.

        IMPORTANT:
        This function does not decide what the user's intent is.

        It only validates the model's interpretation.
        """

        if not raw:
            return LLMNLUResult()

        try:
            data = json.loads(raw)

        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse Ollama JSON response: %s",
                raw[:500],
            )
            return LLMNLUResult()

        if not isinstance(data, dict):
            logger.warning("NLU response is not a JSON object")
            return LLMNLUResult()

        raw_intents = data.get("intents")

        if not isinstance(raw_intents, list):
            logger.warning("NLU response does not contain an intents array")
            return LLMNLUResult()

        intents: list[SearchIntent] = []

        for raw_intent in raw_intents:
            if not isinstance(raw_intent, dict):
                continue

            intent_type = str(
                raw_intent.get("type") or ""
            ).strip().lower()

            if intent_type not in VALID_INTENTS:
                logger.warning(
                    "Ignoring unknown NLU intent type: %s",
                    intent_type,
                )
                continue

            entities = raw_intent.get("entities")

            if not isinstance(entities, dict):
                entities = {}

            references = raw_intent.get("references")

            if not isinstance(references, list):
                references = []

            references = [
                str(reference)
                for reference in references
                if reference
            ]

            intents.append(
                SearchIntent(
                    type=intent_type,
                    description=str(
                        raw_intent.get("description") or ""
                    ),
                    entities=entities,
                    needs_search=bool(
                        raw_intent.get("needs_search", False)
                    ),
                    interpretation=str(
                        raw_intent.get("interpretation") or ""
                    ),
                    references=references,
                )
            )

        return LLMNLUResult(intents=intents)

