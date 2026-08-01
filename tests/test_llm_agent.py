import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from src.llm_agent.agent import (
    SalesAgent,
    _call_llm,
    _format_buyer_message,
    _format_merchant_message,
    _get_llm_config,
    _call_anthropic,
    _call_openai_compatible,
    LLM_TIMEOUT_SECONDS,
)
from src.llm_agent.prompts import (
    BUYER_SYSTEM_PROMPT,
    MERCHANT_HELP_DESK_PROMPT,
    BUYER_FALLBACK_REPLY,
    MERCHANT_FALLBACK_REPLY,
)
from src.llm_agent.context_builder import ContextBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeNLU:
    intent: str = "search_product"
    confidence: float = 0.85
    entities: dict | None = None


class FakeSearchResult:
    def __init__(self, product_id=1, match_label="high"):
        self.product_id = product_id
        self.match_label = match_label


# ---------------------------------------------------------------------------
# _get_llm_config
# ---------------------------------------------------------------------------

class TestGetLLMConfig:
    @patch("src.llm_agent.agent.settings")
    def test_returns_tuple_from_settings(self, mock_settings):
        mock_settings.llm_api_url = "https://api.example.com"
        mock_settings.llm_api_key = "sk-test"
        mock_settings.llm_model = "gpt-4"
        url, key, model = _get_llm_config()
        assert url == "https://api.example.com"
        assert key == "sk-test"
        assert model == "gpt-4"

    @patch("src.llm_agent.agent.settings", spec=[])
    def test_returns_defaults_when_attrs_missing(self, _mock):
        url, key, model = _get_llm_config()
        assert url == ""
        assert key == ""
        assert model == "claude-3-haiku-20240307"


# ---------------------------------------------------------------------------
# _format_buyer_message / _format_merchant_message
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_buyer_message_contains_context(self):
        nlu = FakeNLU(intent="search_product", entities={"product_name": "shoes"})
        messages = _format_buyer_message(nlu, "some context here")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "some context here" in messages[0]["content"]

    def test_buyer_message_includes_entities(self):
        nlu = FakeNLU(entities={"product_name": "shoes", "color": "red"})
        messages = _format_buyer_message(nlu, "ctx")
        assert "product_name=shoes" in messages[0]["content"]

    def test_buyer_message_includes_intent(self):
        nlu = FakeNLU(intent="greeting")
        messages = _format_buyer_message(nlu, "ctx")
        assert "Detected intent: greeting" in messages[0]["content"]

    def test_buyer_message_no_entities_section_when_empty(self):
        nlu = FakeNLU(entities=None)
        messages = _format_buyer_message(nlu, "ctx")
        assert "Key entities" not in messages[0]["content"]

    def test_merchant_message_format(self):
        messages = _format_merchant_message("merchant context")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "merchant context" in messages[0]["content"]


# ---------------------------------------------------------------------------
# _call_llm – routing and error handling
# ---------------------------------------------------------------------------

class TestCallLLM:
    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._get_llm_config", return_value=("", "", "gpt-4"))
    async def test_returns_none_when_no_url(self, _cfg):
        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._get_llm_config", return_value=("https://api.x.com", "", "gpt-4"))
    async def test_returns_none_when_no_key(self, _cfg):
        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_anthropic", new_callable=AsyncMock, return_value="hello from claude")
    @patch("src.llm_agent.agent._get_llm_config", return_value=("https://api.anthropic.com", "sk-key", "claude-3-haiku-20240307"))
    async def test_routes_to_anthropic_when_url_contains_anthropic(self, mock_anthropic, _cfg):
        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result == "hello from claude"
        assert mock_anthropic.call_count == 1

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_openai_compatible", new_callable=AsyncMock, return_value="hello from openai")
    @patch("src.llm_agent.agent._get_llm_config", return_value=("https://api.openai.com", "sk-key", "gpt-4"))
    async def test_routes_to_openai_when_not_anthropic(self, mock_openai, _cfg):
        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result == "hello from openai"
        assert mock_openai.call_count == 1

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent.httpx.AsyncClient")
    @patch("src.llm_agent.agent._get_llm_config", return_value=("https://api.openai.com", "sk-key", "gpt-4"))
    async def test_returns_none_on_timeout(self, _cfg, MockClient):
        import httpx
        instance = AsyncMock()
        instance.post.side_effect = httpx.TimeoutException("timeout")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result is None

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent.httpx.AsyncClient")
    @patch("src.llm_agent.agent._get_llm_config", return_value=("https://api.openai.com", "sk-key", "gpt-4"))
    async def test_returns_none_on_http_error(self, _cfg, MockClient):
        import httpx
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        instance = AsyncMock()
        instance.post.side_effect = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await _call_llm("system", [{"role": "user", "content": "hi"}])
        assert result is None


# ---------------------------------------------------------------------------
# _call_anthropic
# ---------------------------------------------------------------------------

class TestCallAnthropic:
    @pytest.mark.asyncio
    async def test_extracts_text_from_content_blocks(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
                {"type": "image", "source": {}},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        result = await _call_anthropic(
            mock_client, "https://api.anthropic.com", "sk-key", "claude-3-haiku-20240307",
            "system prompt", [{"role": "user", "content": "hi"}],
        )
        assert result == "Line 1\nLine 2"
        call_args = mock_client.post.call_args
        assert "/v1/messages" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_returns_none_when_no_text_blocks(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"content": [{"type": "image"}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        result = await _call_anthropic(
            mock_client, "https://api.anthropic.com", "sk-key", "claude-3-haiku-20240307",
            "system prompt", [{"role": "user", "content": "hi"}],
        )
        assert result is None


# ---------------------------------------------------------------------------
# _call_openai_compatible
# ---------------------------------------------------------------------------

class TestCallOpenAICompatible:
    @pytest.mark.asyncio
    async def test_extracts_content_from_choices(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "OpenAI reply"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        result = await _call_openai_compatible(
            mock_client, "https://api.openai.com", "sk-key", "gpt-4",
            "system prompt", [{"role": "user", "content": "hi"}],
        )
        assert result == "OpenAI reply"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_choices(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": []}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        result = await _call_openai_compatible(
            mock_client, "https://api.openai.com", "sk-key", "gpt-4",
            "system prompt", [{"role": "user", "content": "hi"}],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_sends_system_message_in_full_messages(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        await _call_openai_compatible(
            mock_client, "https://api.openai.com", "sk-key", "gpt-4",
            "system prompt", [{"role": "user", "content": "hello"}],
        )
        payload = mock_client.post.call_args[1]["json"]
        msgs = payload["messages"]
        assert msgs[0] == {"role": "system", "content": "system prompt"}
        assert msgs[1] == {"role": "user", "content": "hello"}


# ---------------------------------------------------------------------------
# SalesAgent._clean_reply
# ---------------------------------------------------------------------------

class TestCleanReply:
    def test_strips_whitespace(self):
        assert SalesAgent._clean_reply("  hello  ") == "hello"

    def test_truncates_long_reply(self):
        long = "a" * 1001
        result = SalesAgent._clean_reply(long)
        assert len(result) == 1000
        assert result.endswith("...")

    def test_short_reply_not_truncated(self):
        short = "a" * 500
        assert SalesAgent._clean_reply(short) == short


# ---------------------------------------------------------------------------
# SalesAgent.compose_reply – with mocked LLM
# ---------------------------------------------------------------------------

class TestSalesAgentComposeReply:
    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value="  LLM reply here  ")
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="built context")
    async def test_returns_cleaned_llm_reply(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU()
        result = await agent.compose_reply(nlu, "+256700000000")
        assert result == "LLM reply here"

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_falls_back_to_template_when_llm_returns_none(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="greeting")
        result = await agent.compose_reply(nlu, "+256700000000")
        assert "whatAppseller" in result

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_greeting(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="greeting")
        result = await agent.compose_reply(nlu, "+256700000000")
        assert "Hello" in result or "Welcome" in result

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_help(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="help")
        result = await agent.compose_reply(nlu, "+256700000000")
        assert "Send a photo" in result

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_search_with_results(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="search_product")
        results = [FakeSearchResult()]
        result = await agent.compose_reply(nlu, "+256700000000", search_results=results)
        assert "matching" in result.lower() or "found" in result.lower()

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_show_interest_with_results(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="show_interest")
        results = [FakeSearchResult(product_id=42)]
        result = await agent.compose_reply(nlu, "+256700000000", search_results=results)
        assert "interest" in result.lower() or "connect" in result.lower()

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_show_interest_no_results(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="show_interest", entities=None)
        result = await agent.compose_reply(nlu, "+256700000000", search_results=None)
        assert "photo" in result.lower() or "tell me" in result.lower()

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_buyer_context", new_callable=AsyncMock, return_value="ctx")
    async def test_fallback_generic_intent(self, _ctx, _llm):
        agent = SalesAgent()
        nlu = FakeNLU(intent="unknown_intent")
        result = await agent.compose_reply(nlu, "+256700000000")
        assert result == BUYER_FALLBACK_REPLY


# ---------------------------------------------------------------------------
# SalesAgent.compose_merchant_reply
# ---------------------------------------------------------------------------

class TestSalesAgentComposeMerchantReply:
    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value="  Merchant LLM reply  ")
    @patch.object(ContextBuilder, "build_merchant_context", new_callable=AsyncMock, return_value="merchant ctx")
    async def test_returns_cleaned_llm_reply(self, _ctx, _llm):
        agent = SalesAgent()
        result = await agent.compose_merchant_reply("@help", "+256700000000")
        assert result == "Merchant LLM reply"

    @pytest.mark.asyncio
    @patch("src.llm_agent.agent._call_llm", new_callable=AsyncMock, return_value=None)
    @patch.object(ContextBuilder, "build_merchant_context", new_callable=AsyncMock, return_value="merchant ctx")
    async def test_falls_back_to_merchant_template(self, _ctx, _llm):
        agent = SalesAgent()
        result = await agent.compose_merchant_reply("@help", "+256700000000")
        assert result == MERCHANT_FALLBACK_REPLY


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------

class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_intent_and_confidence(self):
        builder = ContextBuilder()
        nlu = FakeNLU(intent="search_product", confidence=0.92, entities={"product_name": "shoes"})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "search_product" in ctx
        assert "0.92" in ctx
        assert "Product name: shoes" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_color_list(self):
        builder = ContextBuilder()
        nlu = FakeNLU(entities={"color": ["red", "blue"]})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "Colors: red, blue" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_single_color(self):
        builder = ContextBuilder()
        nlu = FakeNLU(entities={"color": "red"})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "Color: red" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_price_range(self):
        builder = ContextBuilder()
        nlu = FakeNLU(entities={"price_min": 10000, "price_max": 50000})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "10,000 UGX" in ctx
        assert "50,000 UGX" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_location(self):
        builder = ContextBuilder()
        nlu = FakeNLU(entities={"location": "Kampala"})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "Location preference: Kampala" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_category_list(self):
        builder = ContextBuilder()
        nlu = FakeNLU(entities={"category": ["Electronics", "Fashion"]})
        ctx = await builder.build_buyer_context(nlu, "+256700000000")
        assert "Categories: Electronics, Fashion" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_includes_search_results(self):
        builder = ContextBuilder()
        nlu = FakeNLU()
        results = [FakeSearchResult(product_id=10, match_label="exact")]
        ctx = await builder.build_buyer_context(nlu, "+256700000000", search_results=results)
        assert "Product ID 10" in ctx
        assert "Match: exact" in ctx

    @pytest.mark.asyncio
    async def test_build_buyer_context_no_results(self):
        builder = ContextBuilder()
        nlu = FakeNLU()
        ctx = await builder.build_buyer_context(nlu, "+256700000000", search_results=[])
        assert "Search results" not in ctx

    @pytest.mark.asyncio
    async def test_build_merchant_context_masks_phone(self):
        builder = ContextBuilder()
        ctx = await builder.build_merchant_context("@help", "+256700123456")
        assert "Merchant phone:" in ctx
        assert "***" in ctx
        assert "+256700" in ctx
        assert "3456" in ctx

    @pytest.mark.asyncio
    async def test_build_merchant_context_short_phone_not_masked(self):
        builder = ContextBuilder()
        ctx = await builder.build_merchant_context("@help", "12345")
        assert "12345" in ctx

    @pytest.mark.asyncio
    async def test_build_merchant_context_includes_message(self):
        builder = ContextBuilder()
        ctx = await builder.build_merchant_context("@stock 1 10", "+256700000000")
        assert "@stock 1 10" in ctx


# ---------------------------------------------------------------------------
# ContextBuilder – conversation history
# ---------------------------------------------------------------------------

class TestContextBuilderHistory:
    @pytest.mark.asyncio
    async def test_get_conversation_history_returns_empty_when_no_redis(self):
        builder = ContextBuilder()
        result = await builder.get_conversation_history("+256700000000", redis=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_conversation_history_returns_messages(self):
        import json
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [
            json.dumps({"role": "buyer", "content": "hi"}),
            json.dumps({"role": "merchant", "content": "hello"}),
        ]
        builder = ContextBuilder()
        result = await builder.get_conversation_history("+256700000000", redis=mock_redis)
        assert len(result) == 2
        assert result[0]["role"] == "buyer"
        assert result[1]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_get_conversation_history_skips_invalid_json(self):
        import json
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [
            json.dumps({"role": "buyer", "content": "ok"}),
            "not-json",
        ]
        builder = ContextBuilder()
        result = await builder.get_conversation_history("+256700000000", redis=mock_redis)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_conversation_history_returns_empty_on_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.side_effect = Exception("connection lost")
        builder = ContextBuilder()
        result = await builder.get_conversation_history("+256700000000", redis=mock_redis)
        assert result == []

    @pytest.mark.asyncio
    async def test_save_message_to_history(self):
        import json
        mock_redis = AsyncMock()
        await ContextBuilder.save_message_to_history(mock_redis, "+256700000000", "buyer", "hello")
        mock_redis.rpush.assert_awaited_once()
        call_args = mock_redis.rpush.call_args[0]
        assert call_args[0] == "conv_history:+256700000000"
        saved = json.loads(call_args[1])
        assert saved["role"] == "buyer"
        assert saved["content"] == "hello"
        mock_redis.ltrim.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

class TestPromptConstants:
    def test_buyer_prompt_mentions_ugx(self):
        assert "UGX" in BUYER_SYSTEM_PROMPT

    def test_merchant_prompt_mentions_commands(self):
        for cmd in ("@register", "@post", "@edit", "@stock", "@price", "@delete", "@help"):
            assert cmd in MERCHANT_HELP_DESK_PROMPT

    def test_buyer_fallback_is_nonempty_string(self):
        assert len(BUYER_FALLBACK_REPLY) > 0

    def test_merchant_fallback_mentions_help(self):
        assert "@help" in MERCHANT_FALLBACK_REPLY
