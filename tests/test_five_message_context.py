import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.conversation_context import ConversationContext
from src.services.lisa_agent import LisaAgent
from src.workers import router as router_module
from src.workers.nlu_router import RegexNLURouter
from src.workers.queue import _memory_queue

# A realistic 5-message buyer conversation. Each entry is
# (user_text, expected lisa action, scripted reply, scripted search_text).
SCRIPT = [
    ("hello", "chat", "Hey there! What can I help you find today?", ""),
    ("i need brown shoes under 100k", "search", "On it!", "brown shoes under 100k"),
    ("what about size 42?", "search", "Checking size 42!", "brown shoes size 42"),
    ("is the sole republic shop near kampala?", "chat", "Let me check their location for you.", ""),
    ("ok let's go with the shoes 4", "search", "Great pick!", "Shoes 4"),
]

PHONE = "256700000000"


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeResult:
    def __init__(self, rows):
        self.scalars = MagicMock(return_value=FakeScalars(rows))


class FakeRedis:
    """In-memory Redis double supporting the subset of calls the system uses."""

    def __init__(self):
        self._data: dict = {}
        self._lists: dict[str, list] = {}

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value):
        self._data[key] = value

    async def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    async def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        return items[start:end + 1]

    async def ltrim(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        self._lists[key] = items[start:end + 1]

    async def llen(self, key):
        return len(self._lists.get(key, []))

    async def expire(self, key, ttl):
        pass


class FakeDB:
    """Stores ConversationMessage/CustomerMemory rows and answers the queries
    the context layer makes, without a real database."""

    def __init__(self, conv):
        self.conv = conv
        self.memory_row = None
        self.added: list = []

    async def get(self, model, pk):
        return self.conv

    async def execute(self, statement):
        return FakeResult([self.memory_row] if self.memory_row else [])

    def add(self, obj):
        self.added.append(obj)
        if type(obj).__name__ == "CustomerMemory":
            self.memory_row = obj

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass


def _conv():
    return SimpleNamespace(
        id=1,
        phone_number=PHONE,
        merchant_id=None,
        customer_id=None,
        public_id="chat_test1",
        summary=None,
        last_message_at=None,
    )


async def _run_script(agent, cc, redis, db, conv):
    """Run the same per-turn pipeline the web chat uses:
    decide -> record Lisa history -> persist to durable context."""
    llm_calls: list[list[dict]] = []
    stage_by_turn = []
    reply_by_turn = []

    def scripted_llm(messages, force_json=True):
        llm_calls.append(list(messages))
        turn = len(reply_by_turn)
        action, reply, search_text = (
            SCRIPT[turn][1],
            SCRIPT[turn][2],
            SCRIPT[turn][3],
        )
        return json.dumps(
            {"action": action, "search_text": search_text, "reply": reply}
        )

    with patch.object(agent, "_call_ollama", side_effect=scripted_llm):
        for user_text, _, reply, _ in SCRIPT:
            turn = await agent.decide(redis, 1, user_text, has_image=False)
            stage_by_turn.append(turn.action)
            reply_by_turn.append(turn.reply)
            user_content = agent.user_turn_text(user_text, False, "")
            await agent.record_turn(redis, 1, user_content, turn.reply, stage=turn.action)
            await cc.append(db, redis, conv.id, "user", user_content)
            await cc.append(db, redis, conv.id, "assistant", turn.reply or reply)

    return llm_calls


class TestFiveMessageMemory:
    async def test_five_messages_are_retained_in_context_and_lisa_history(self):
        agent = LisaAgent()
        cc = ConversationContext()
        redis = FakeRedis()
        db = FakeDB(_conv())

        llm_calls = await _run_script(agent, cc, redis, db, _conv())

        # Lisa's fast memory keeps every turn in order.
        history = await agent._load_history(redis, 1)
        assert [h["role"] for h in history] == [
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
        ]
        assert "brown shoes under 100k" in history[2]["content"]
        assert "size 42" in history[4]["content"]

        # The durable conversation context mirrors the same transcript.
        ctx = await cc.load_context(db, redis, 1)
        messages = ctx["messages"]
        assert len(messages) == 10
        assert [m["role"] for m in messages] == [
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
        ]
        assert messages[4]["content"] == "what about size 42?"
        assert messages[5]["content"] == "Checking size 42!"

        # Durable rows were actually persisted.
        assert len(db.added) == 10

    async def test_fifth_message_decision_sees_earlier_context(self):
        agent = LisaAgent()
        cc = ConversationContext()
        redis = FakeRedis()
        db = FakeDB(_conv())

        llm_calls = await _run_script(agent, cc, redis, db, _conv())

        # When Lisa processes message 5 she must see the whole thread,
        # not just the latest line — that is the memory she talks from.
        fifth_prompt = llm_calls[4]
        prompt_text = "\n".join(m.get("content", "") for m in fifth_prompt)
        assert "brown shoes under 100k" in prompt_text
        assert "size 42" in prompt_text
        assert "sole republic" in prompt_text
        assert SCRIPT[4][0] in prompt_text

    async def test_compaction_writes_summary_and_customer_memory(self):
        agent = LisaAgent()
        cc = ConversationContext()
        redis = FakeRedis()
        db = FakeDB(_conv())

        await _run_script(agent, cc, redis, db, _conv())

        with (
            patch.object(
                cc,
                "_call_summary_llm",
                new_callable=AsyncMock,
                return_value={
                    "update": "Wants brown shoes, size 42, budget under 100k.",
                    "memory": {"product": "brown shoes", "size": "42", "budget": "100k"},
                },
            ),
        ):
            await cc._compact_old_messages(db, redis, 1, 4)

        assert db.conv.summary == "Wants brown shoes, size 42, budget under 100k."
        memory = await cc._load_memory(db, PHONE)
        assert memory["product"] == "brown shoes"
        assert memory["size"] == "42"
        assert memory["budget"] == "100k"

    async def test_load_context_returns_summary_and_memory_together(self):
        agent = LisaAgent()
        cc = ConversationContext()
        redis = FakeRedis()
        db = FakeDB(_conv())

        await _run_script(agent, cc, redis, db, _conv())
        with patch.object(
            cc,
            "_call_summary_llm",
            new_callable=AsyncMock,
            return_value={
                "summary": "Buyer wants brown shoes in size 42.",
                "memory": {"product": "brown shoes", "size": "42"},
            },
        ):
            await cc._compact_old_messages(db, redis, 1, 4)

        ctx = await cc.load_context(db, redis, 1)
        assert ctx["summary"] == "Buyer wants brown shoes in size 42."
        assert ctx["memory"]["product"] == "brown shoes"
        assert ctx["memory"]["size"] == "42"


class _AsyncSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


WHATSAPP_SCRIPT = [
    {"type": "text", "text": {"body": "hello"}},
    {"type": "text", "text": {"body": "i need brown shoes under 100k"}},
    {"type": "text", "text": {"body": "what about size 42?"}},
    {"type": "text", "text": {"body": "is the sole republic shop near kampala?"}},
    {"type": "text", "text": {"body": "ok let's go with the shoes 4"}},
]


class TestFiveMessageWorkerPipeline:
    """Drive the real WhatsApp route_message pipeline over five buyer messages
    and confirm the conversation memory accumulates the whole thread."""

    async def _run_whatsapp_script(self):
        conv = _conv()
        redis = FakeRedis()
        db = FakeDB(conv)
        sent: list[str] = []
        extract_contexts: list[dict] = []

        async def fake_extract(message_text="", has_image=False, history=None, context=None):
            extract_contexts.append(context or {})
            return await RegexNLURouter().extract(
                message_text, has_image=has_image, history=history
            )

        async def fake_send(to, text):
            sent.append(text)

        with (
            patch.object(
                router_module,
                "async_session_factory",
                return_value=_AsyncSessionCtx(db),
            ),
            patch.object(router_module, "get_redis", new=AsyncMock(return_value=redis)),
            patch.object(router_module, "get_merchant_by_phone", new=AsyncMock(return_value=None)),
            patch.object(
                router_module,
                "get_buyer_by_phone",
                new=AsyncMock(return_value=SimpleNamespace(is_banned=False)),
            ),
            patch.object(router_module, "ensure_whatsapp_user", new=AsyncMock()),
            patch.object(router_module, "get_wizard_step", new=AsyncMock(return_value=None)),
            patch.object(router_module, "is_merchant_command", return_value=False),
            patch.object(router_module, "extract_nlu", new=AsyncMock(side_effect=fake_extract)),
            patch.object(router_module, "execute_intent_searches", new=AsyncMock(return_value=[])),
            patch.object(
                router_module,
                "compose_multi_intent_reply",
                new=AsyncMock(return_value="I found some matches for you!"),
            ),
            patch.object(
                router_module._context,
                "ensure_conversation",
                new=AsyncMock(return_value=conv),
            ),
            patch.object(router_module._context, "append", wraps=router_module._context.append),
            patch.object(
                router_module._context,
                "load_context",
                wraps=router_module._context.load_context,
            ),
            patch.object(router_module, "send_text", new=AsyncMock(side_effect=fake_send)),
        ):
            # Clear the queue between tests so a leftover payload never leaks in.
            while not _memory_queue.empty():
                _memory_queue.get_nowait()
            for payload in WHATSAPP_SCRIPT:
                await router_module.route_message(payload)

        return router_module._context, conv, redis, db, sent, extract_contexts

    async def test_five_messages_accumulate_context(self):
        cc, conv, redis, db, sent, _ = await self._run_whatsapp_script()

        assert len(sent) == 5
        ctx = await cc.load_context(db, redis, conv.id)
        messages = ctx["messages"]
        assert len(messages) == 10
        assert [m["role"] for m in messages] == [
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
            "user", "assistant",
        ]
        assert messages[0]["content"] == "hello"
        assert messages[2]["content"] == "i need brown shoes under 100k"
        assert messages[6]["content"] == "is the sole republic shop near kampala?"
        assert messages[8]["content"] == "ok let's go with the shoes 4"

    async def test_fifth_worker_message_sees_prior_context(self):
        cc, conv, redis, db, sent, extract_contexts = await self._run_whatsapp_script()

        # The NLU that processed message 5 must have received the whole thread,
        # not just the latest line.
        fifth_ctx = extract_contexts[4]
        assert fifth_ctx["messages"]
        transcript = " ".join(
            m.get("content", "") for m in fifth_ctx["messages"] if m.get("role") == "user"
        )
        # Context is loaded before the current turn is appended, so message 5's
        # NLU must at minimum have seen all four earlier turns.
        assert "hello" in transcript
        assert "brown shoes under 100k" in transcript
        assert "size 42" in transcript
        assert "sole republic" in transcript

    async def test_worker_flow_persists_durable_rows(self):
        from src.domain.models import ConversationMessage

        cc, conv, redis, db, sent, _ = await self._run_whatsapp_script()
        assert len(db.added) == 10
        assert len([m for m in db.added if isinstance(m, ConversationMessage)]) == 10
