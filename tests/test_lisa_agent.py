import json
from unittest.mock import AsyncMock, patch

import pytest

from src.services.lisa_agent import LisaAgent, AgentTurn


@pytest.fixture
def agent():
    return LisaAgent()


@pytest.fixture
def mock_redis():
    return AsyncMock()


class TestParseDecision:
    def test_search_action(self, agent):
        turn = agent._parse_decision(
            '{"action": "search", "search_text": "red nike shoes", "reply": "On it!"}',
            "i want kicks", has_image=False,
        )
        assert turn.action == "search"
        assert turn.search_text == "red nike shoes"
        assert turn.reply == "On it!"

    def test_search_without_text_uses_message(self, agent):
        turn = agent._parse_decision(
            '{"action": "search", "search_text": "", "reply": ""}',
            "looking for a samsung phone", has_image=False,
        )
        assert turn.action == "search"
        assert turn.search_text == "looking for a samsung phone"

    def test_chat_action(self, agent):
        turn = agent._parse_decision(
            '{"action": "chat", "reply": "Hey! What are you after today?"}', "", has_image=False,
        )
        assert turn.action == "chat"
        assert "Hey!" in turn.reply

    def test_invalid_json_falls_back(self, agent):
        turn = agent._parse_decision("not json at all", "hello", has_image=False)
        assert turn.action == "chat"

    def test_empty_raw_falls_back_to_greeting(self, agent):
        turn = agent._parse_decision("", "hello there", has_image=False)
        assert turn.action == "chat"
        assert "Lisa" in turn.reply

    def test_fallback_image_forces_search(self, agent):
        turn = agent._parse_decision("", "what do you have", has_image=True)
        assert turn.action == "search"

    def test_fallback_product_text_searches(self, agent):
        turn = agent._parse_decision("", "i want shoes under 100k", has_image=False)
        assert turn.action == "search"
        assert turn.search_text == "i want shoes under 100k"

    def test_fallback_help(self, agent):
        turn = agent._parse_decision("", "help me", has_image=False)
        assert turn.action == "chat"
        assert "Here's how I can help" in turn.reply


class TestUserTurnText:
    def test_text_only(self, agent):
        assert agent.user_turn_text("red shoes", False) == "red shoes"

    def test_image_only(self, agent):
        text = agent.user_turn_text("", True, image_note="I see a car in your image")
        assert "Customer sent a photo" in text
        assert "car" in text

    def test_image_and_text(self, agent):
        text = agent.user_turn_text("i want shoes", True, image_note="I see a car in your image")
        assert "i want shoes" in text
        assert "car" in text


class TestHistory:
    async def test_record_and_load_roundtrip(self, agent, mock_redis):
        mock_redis.get.return_value = None
        await agent.record_turn(mock_redis, 7, "hello", "hi there!")
        stored = mock_redis.set.await_args.args[1]
        entries = json.loads(stored)
        assert entries[0] == {"role": "user", "content": "hello"}
        assert entries[1] == {"role": "assistant", "content": "hi there!"}
        assert mock_redis.set.await_args.args[0] == "lisa:history:7"

    async def test_load_returns_parsed_history(self, agent, mock_redis):
        mock_redis.get.return_value = json.dumps([
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ])
        history = await agent._load_history(mock_redis, 1)
        assert len(history) == 2

    async def test_load_tolerates_bad_json(self, agent, mock_redis):
        mock_redis.get.return_value = "not-json"
        assert await agent._load_history(mock_redis, 1) == []

    async def test_redis_errors_silent(self, agent, mock_redis):
        mock_redis.get.side_effect = Exception("redis down")
        assert await agent._load_history(mock_redis, 1) == []
        await agent.record_turn(mock_redis, 1, "x", "y")  # must not raise


class TestDecide:
    async def test_decide_uses_history_and_returns_turn(self, agent, mock_redis):
        mock_redis.get.return_value = None
        with patch.object(agent, "_call_ollama", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '{"action": "chat", "reply": "What are you after?"}'
            turn = await agent.decide(mock_redis, 3, "yo watsup", has_image=False)

        assert turn.action == "chat"
        assert turn.reply == "What are you after?"
        # history + system + current user turn
        assert mock_llm.await_args.args[0][0]["role"] == "system"

    async def test_decide_fallback_when_ollama_down(self, agent, mock_redis):
        mock_redis.get.return_value = None
        with patch.object(agent, "_call_ollama", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ""
            turn = await agent.decide(mock_redis, 3, "hi", has_image=False)
        assert turn.action == "chat"
        assert "Lisa" in turn.reply


class TestPresentResults:
    async def test_present_returns_natural_text(self, agent, mock_redis):
        with patch.object(agent, "_call_ollama", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = (
                'These are awesome! The "Red Nike" at 120,000 UGX is my pick '
                "for you — tap I'm interested or tell me to refine."
            )
            text = await agent.present_results(mock_redis, 1, [
                {"name": "Red Nike", "price": 120000, "merchant_name": "Kicks Shop"},
            ])
        assert "Red Nike" in text
        assert "120,000" in text

    async def test_present_empty_results(self, agent, mock_redis):
        assert await agent.present_results(mock_redis, 1, []) == ""

    async def test_present_falls_back_empty_on_llm_failure(self, agent, mock_redis):
        with patch.object(agent, "_call_ollama", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ""
            text = await agent.present_results(mock_redis, 1, [{"name": "X", "price": 1}])
        assert text  # deterministic fallback keeps the assistant talking
        assert "X" in text

    async def test_present_includes_history(self, agent, mock_redis):
        mock_redis.get.return_value = json.dumps([
            {"role": "user", "content": "brown shoes"},
            {"role": "assistant", "content": "On it!"},
        ])
        with patch.object(agent, "_call_ollama", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Found them!"
            text = await agent.present_results(mock_redis, 1, [{"name": "K", "price": 2}])
        assert text == "Found them!"
        assert "brown shoes" in mock_llm.await_args.args[0][1]["content"]

    def test_fallback_present_joins_picks(self, agent):
        summary = "- Shoe A — 100 UGX (Shop 1)\n- Shoe B — 200 UGX (Shop 2)"
        text = LisaAgent._fallback_present(summary)
        assert "Shoe A" in text and "Shoe B" in text

    def test_fallback_present_empty(self, agent):
        assert LisaAgent._fallback_present("") == ""


class TestExtractReplyText:
    def test_plain_text(self, agent):
        assert LisaAgent._extract_reply_text("Found these great picks!") == "Found these great picks!"

    def test_fenced_json(self, agent):
        raw = '```json\n{"reply": "Here you go!"}\n```'
        assert LisaAgent._extract_reply_text(raw) == "Here you go!"

    def test_broken_json_with_unescaped_quotes(self, agent):
        """gemma2 sometimes emits unescaped quotes — we must never leak raw JSON."""
        raw = '{"action": "chat", "reply": "Tap "Im interested" to buy now."}'
        extracted = LisaAgent._extract_reply_text(raw)
        assert '{"action"' not in extracted
        assert extracted.strip()

    def test_json_present_fields(self, agent):
        raw = '{"action": "search", "search_text": "red shoes", "reply": ""}'
        assert LisaAgent._extract_reply_text(raw) == ""

    def test_empty_returns_empty(self, agent):
        assert LisaAgent._extract_reply_text("   ") == ""
