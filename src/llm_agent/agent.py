import logging
from typing import Any

import httpx

from src.core.config import settings
from src.llm_agent.prompts import (
    BUYER_SYSTEM_PROMPT,
    MERCHANT_HELP_DESK_PROMPT,
    BUYER_FALLBACK_REPLY,
    MERCHANT_FALLBACK_REPLY,
)
from src.llm_agent.context_builder import ContextBuilder

logger = logging.getLogger(__name__)

_context_builder = ContextBuilder()

LLM_TIMEOUT_SECONDS = 30


def _get_llm_config() -> tuple[str, str, str]:
    return (
        settings.llm_api_url if hasattr(settings, "llm_api_url") else "",
        settings.llm_api_key if hasattr(settings, "llm_api_key") else "",
        settings.llm_model if hasattr(settings, "llm_model") else "claude-3-haiku-20240307",
    )


def _format_buyer_message(nlu_result, context: str) -> list[dict[str, str]]:
    user_content = f"Context about this buyer interaction:\n\n{context}\n\nPlease compose a helpful reply to this buyer."

    if nlu_result.entities:
        entity_str = ", ".join(f"{k}={v}" for k, v in nlu_result.entities.items())
        user_content += f"\n\nKey entities extracted: {entity_str}"

    if nlu_result.intent:
        user_content += f"\nDetected intent: {nlu_result.intent}"

    return [{"role": "user", "content": user_content}]


def _format_merchant_message(context: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"Context about this merchant interaction:\n\n{context}"}]


async def _call_llm(system_prompt: str, messages: list[dict[str, str]]) -> str | None:
    api_url, api_key, model = _get_llm_config()

    if not api_url or not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            if "anthropic" in api_url.lower() or model.startswith("claude"):
                response = await _call_anthropic(client, api_url, api_key, model, system_prompt, messages)
            else:
                response = await _call_openai_compatible(client, api_url, api_key, model, system_prompt, messages)
            return response
    except httpx.TimeoutException:
        logger.warning("LLM API request timed out")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("LLM API returned error %d: %s", e.response.status_code, e.response.text[:200])
        return None
    except Exception as e:
        logger.error("Unexpected error calling LLM API: %s", e)
        return None


async def _call_anthropic(
    client: httpx.AsyncClient,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str | None:
    url = f"{api_url}/v1/messages" if not api_url.endswith("/v1/messages") else api_url
    if not url.endswith("/messages"):
        url = f"{api_url}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": 300,
        "system": system_prompt,
        "messages": messages,
    }

    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()

    content_blocks = data.get("content", [])
    text_parts = [block["text"] for block in content_blocks if block.get("type") == "text"]
    return "\n".join(text_parts) if text_parts else None


async def _call_openai_compatible(
    client: httpx.AsyncClient,
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str | None:
    url = f"{api_url}/v1/chat/completions" if not api_url.endswith("/chat/completions") else api_url

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    payload = {
        "model": model,
        "max_tokens": 300,
        "messages": full_messages,
    }

    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content")
    return None


class SalesAgent:
    def __init__(self):
        self._context_builder = _context_builder

    async def compose_reply(
        self,
        nlu_result,
        buyer_phone: str,
        conversation_history: list[dict] = None,
        search_results: list = None,
        shop_context: dict | None = None,
        summary: str | None = None,
        memory: dict | None = None,
    ) -> str:
        context = await self._context_builder.build_buyer_context(
            nlu_result=nlu_result,
            buyer_phone=buyer_phone,
            search_results=search_results,
            history=conversation_history,
            shop_context=shop_context,
            summary=summary,
            memory=memory,
        )

        messages = _format_buyer_message(nlu_result, context)
        llm_reply = await _call_llm(BUYER_SYSTEM_PROMPT, messages)

        if llm_reply:
            return self._clean_reply(llm_reply)

        return self._compose_fallback_reply(nlu_result, search_results)

    async def compose_merchant_reply(
        self,
        message_text: str,
        merchant_phone: str,
        conversation_history: list[dict] = None,
    ) -> str:
        context = await self._context_builder.build_merchant_context(
            message_text=message_text,
            merchant_phone=merchant_phone,
            history=conversation_history,
        )

        messages = _format_merchant_message(context)
        llm_reply = await _call_llm(MERCHANT_HELP_DESK_PROMPT, messages)

        if llm_reply:
            return self._clean_reply(llm_reply)

        return MERCHANT_FALLBACK_REPLY

    def _compose_fallback_reply(self, nlu_result, search_results: list = None) -> str:
        intent = nlu_result.intent if nlu_result else "unknown"

        if intent == "greeting":
            return (
                "Hello! Welcome to whatAppseller. I'm here to help you find products.\n\n"
                "Tell me what you're looking for, or send a photo of a product you want!"
            )

        if intent == "help":
            return (
                "Here's what I can do:\n\n"
                "1. Send a photo of a product you want\n"
                "2. Describe what you need - e.g. 'red shoes under 100000'\n"
                "3. I'll show matching products from nearby sellers"
            )

        if intent == "search_product" and search_results:
            return (
                f"I found some products matching what you're looking for!\n\n"
                "Check out the results above. Tap on a product to express interest, "
                "or send me more details for a better match."
            )

        if intent == "show_interest":
            if search_results and len(search_results) > 0:
                first = search_results[0]
                product_name = getattr(first, "product_id", "the product")
                return (
                    f"Great choice! I can help you connect with the seller.\n\n"
                    "Would you like me to send your interest to the merchant? "
                    "Just say 'yes' or 'interested'!"
                )
            return (
                "I'd be happy to help you with that! Could you tell me more about "
                "what you're looking for? A photo works great too!"
            )

        return BUYER_FALLBACK_REPLY

    @staticmethod
    def _clean_reply(text: str) -> str:
        cleaned = text.strip()
        if len(cleaned) > 1000:
            cleaned = cleaned[:997] + "..."
        return cleaned
