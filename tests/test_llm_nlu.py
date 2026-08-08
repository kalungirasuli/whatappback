import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.services.llm_nlu import LLMNLUService, LLMNLUResult, SearchIntent, NLU_SYSTEM_PROMPT


def test_prompt_judges_tone_not_keyword_hints():
    assert "Do NOT rely on keyword hints" in NLU_SYSTEM_PROMPT
    assert "tone" in NLU_SYSTEM_PROMPT.lower()
    assert '"ok" after seeing results' in NLU_SYSTEM_PROMPT


def _mock_ollama(raw: str):
    resp = MagicMock()
    resp.json.return_value = {"response": raw}
    resp.raise_for_status = MagicMock()
    instance = AsyncMock()
    instance.post.return_value = resp
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=False)
    return instance


class TestBuildContextBlock:
    def test_joins_entire_history_as_one_json_object(self):
        history = [{"role": "user", "content": f"message {i}"} for i in range(20)]
        block = LLMNLUService._build_context_block(history)
        assert "Conversation history (entire chat, oldest first) as one JSON object" in block
        payload = block.split(":\n", 1)[1].split("\n\n", 1)[0]
        turns = json.loads(payload)
        assert len(turns) == 20
        assert turns[0]["content"] == "message 0"
        assert turns[19]["content"] == "message 19"
        assert turns[0]["role"] == "customer"

    def test_map_user_role_to_customer(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        block = LLMNLUService._build_context_block(history)
        turns = json.loads(block.split(":\n", 1)[1].split("\n\n", 1)[0])
        assert turns[0]["role"] == "customer"
        assert turns[1]["role"] == "assistant"

    def test_includes_summary_memory_and_shop(self):
        block = LLMNLUService._build_context_block(
            [],
            summary="Wants black shoes.",
            memory={"name": "Sarah", "budget": "80 USD"},
            shop={
                "business_name": "Test Shop",
                "category": "Clothing",
                "products": [{"name": "Shirt"}, {"name": "Trouser"}],
            },
        )
        assert "Earlier conversation summary" in block
        assert "Wants black shoes." in block
        assert "Customer memory (durable facts)" in block
        assert "- name: Sarah" in block
        assert "Shop context" in block
        assert "business name: Test Shop" in block
        assert "Shirt" in block

    def test_empty_block_without_context(self):
        assert LLMNLUService._build_context_block([]) == ""


class TestExtract:
    async def test_attaches_full_history_and_context_to_request(self):
        instance = _mock_ollama(
            json.dumps({"intents": [{"type": "product_search", "entities": {}}]})
        )
        service = LLMNLUService()
        context = {
            "messages": [{"role": "user", "content": f"turn {i}"} for i in range(25)],
            "summary": "long story",
            "memory": {"name": "Sarah"},
            "shop": {"business_name": "Test Shop", "products": []},
        }
        with patch("src.services.llm_nlu.httpx.AsyncClient", return_value=instance):
            result = await service.extract("under 100k", history=[], context=context)

        assert isinstance(result, LLMNLUResult)
        assert result.intents[0].type == "product_search"
        prompt = instance.post.call_args[1]["json"]["prompt"]
        assert "turn 24" in prompt
        assert "(entire chat, oldest first) as one JSON object" in prompt
        assert "long story" in prompt
        assert "- name: Sarah" in prompt
        assert "business name: Test Shop" in prompt

    async def test_uses_history_when_no_context(self):
        instance = _mock_ollama(
            json.dumps({"intents": [{"type": "chat", "description": ""}]})
        )
        service = LLMNLUService()
        with patch("src.services.llm_nlu.httpx.AsyncClient", return_value=instance):
            result = await service.extract(
                "thanks", history=[{"role": "user", "content": "earlier one"}]
            )
        prompt = instance.post.call_args[1]["json"]["prompt"]
        assert "earlier one" in prompt
        assert result.intents[0].type == "chat"

    async def test_returns_empty_on_connect_error(self):
        instance = AsyncMock()
        instance.post.side_effect = httpx.ConnectError("down")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        service = LLMNLUService()
        with patch("src.services.llm_nlu.httpx.AsyncClient", return_value=instance):
            result = await service.extract("hello")
        assert result.intents == []
        assert result.raw_response == ""

    async def test_returns_empty_on_bad_json(self):
        instance = _mock_ollama("not json at all")
        service = LLMNLUService()
        with patch("src.services.llm_nlu.httpx.AsyncClient", return_value=instance):
            result = await service.extract("hello")
        assert result.intents == []