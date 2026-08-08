import json
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.config import settings
from src.domain.models import Conversation
from src.services.conversation_context import (
    ConversationContext,
    REDIS_PREFIX,
    SUMMARY_INTERVAL,
    TTL_SECONDS,
)


def _result(first=None, rows=None):
    scalars = MagicMock()
    scalars.first.return_value = first
    if rows is not None:
        scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _conv(conversation_id=1, phone="256700000000", merchant_id=None, summary=None):
    conv = MagicMock(spec=Conversation)
    conv.id = conversation_id
    conv.phone_number = phone
    conv.merchant_id = merchant_id
    conv.customer_id = None
    conv.public_id = f"chat_{conversation_id}"
    conv.summary = summary
    conv.last_message_at = None
    return conv


def _msg(role="user", content="hi"):
    return SimpleNamespace(role=role, content=content)


def _mock_db():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_result(first=None, rows=[]))
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestEnsureConversation:
    async def test_returns_existing_conversation(self):
        db = _mock_db()
        conv = _conv()
        db.execute.return_value = _result(first=conv)
        cc = ConversationContext()
        result = await cc.ensure_conversation(db, "256700000000", "buyer")
        assert result is conv
        db.commit.assert_awaited()
        assert conv.last_message_at is not None
        db.add.assert_not_called()

    async def test_creates_new_conversation(self):
        db = _mock_db()
        db.execute.return_value = _result(first=None)
        cc = ConversationContext()
        result = await cc.ensure_conversation(db, "256700000000", "buyer")
        assert result.public_id.startswith("chat_")
        assert db.add.call_args[0][0].phone_number == "256700000000"
        db.commit.assert_awaited()
        db.refresh.assert_awaited()

    async def test_creates_new_conversation_with_backfill(self):
        db = _mock_db()
        db.execute.return_value = _result(first=None)
        cc = ConversationContext()
        with patch("src.services.conversation_context.ConversationContext._backfill_from_chat_log", new_callable=AsyncMock) as mock_backfill:
            await cc.ensure_conversation(db, "256700000000", "buyer", backfill=True)
        mock_backfill.assert_awaited_once()

    async def test_scopes_by_role_and_merchant(self):
        db = _mock_db()
        db.execute.return_value = _result(first=None)
        cc = ConversationContext()
        await cc.ensure_conversation(db, "256700000000", "merchant", merchant_id=7)
        call = db.execute.call_args[0][0]
        sql = str(call)
        assert "merchant_id" in sql
        assert "phone_number" in sql


class TestLoadContext:
    async def test_loads_from_redis_hit(self):
        db = _mock_db()
        conv = _conv()
        db.get = AsyncMock(return_value=conv)
        redis = AsyncMock()
        redis.lrange.return_value = [
            json.dumps({"role": "user", "content": "hi"}),
            json.dumps({"role": "assistant", "content": "hello"}),
        ]
        cc = ConversationContext()
        ctx = await cc.load_context(db, redis, 1)
        assert len(ctx["messages"]) == 2
        ctx["messages"][0]["content"] == "hi"
        redis.rpush.assert_not_awaited()

    async def test_falls_back_to_db_and_seeds_redis(self):
        db = _mock_db()
        conv = _conv()
        db.get = AsyncMock(return_value=conv)
        db.execute.side_effect = [_result(rows=[_msg("user", "older")])]
        redis = AsyncMock()
        redis.lrange.return_value = []
        cc = ConversationContext()
        ctx = await cc.load_context(db, redis, 1)
        assert ctx["messages"] == [{"role": "user", "content": "older"}]
        redis.rpush.assert_awaited()
        redis.ltrim.assert_awaited()
        redis.expire.assert_awaited_once_with(f"{REDIS_PREFIX}1", TTL_SECONDS)

    async def test_includes_summary_memory_shop(self):
        db = _mock_db()
        conv = _conv(merchant_id=3, summary="Wants black shoes")
        db.get = AsyncMock(return_value=conv)
        db.execute.side_effect = [
            _result(first=SimpleNamespace(memory={"budget": "80 USD"})),
            _result(rows=[_msg()]),
        ]
        redis = AsyncMock()
        redis.lrange.return_value = [
            json.dumps({"role": "user", "content": "black shoes"}),
        ]
        cc = ConversationContext()
        ctx = await cc.load_context(db, redis, 1)
        assert ctx["summary"] == "Wants black shoes"
        assert ctx["memory"] == {"budget": "80 USD"}


class TestAppend:
    async def test_appends_to_redis_and_db(self):
        db = _mock_db()
        conv = _conv()
        db.get = AsyncMock(return_value=conv)
        db.execute.return_value = _result(first=None)
        redis = AsyncMock()
        redis.llen.return_value = 0
        cc = ConversationContext()
        await cc.append(db, redis, 1, "user", "hello there")
        redis.rpush.assert_awaited_once()
        key = redis.rpush.call_args[0][0]
        assert key == f"{REDIS_PREFIX}1"
        saved = json.loads(redis.rpush.call_args[0][1])
        assert saved == {"role": "user", "content": "hello there"}
        redis.ltrim.assert_awaited()
        inserted = db.add.call_args[0][0]
        assert inserted.conversation_id == 1
        db.commit.assert_awaited()

    async def test_appends_empty_content(self):
        redis = AsyncMock()
        db = _mock_db()
        cc = ConversationContext()
        await cc.append(db, redis, 1, "user", None)
        saved = json.loads(redis.rpush.call_args[0][1])
        assert saved["content"] == ""


class TestMaybeRefreshSummary:
    async def test_triggers_at_interval(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.llen.return_value = SUMMARY_INTERVAL
        cc = ConversationContext()
        with patch.object(cc, "_refresh_summary", new_callable=AsyncMock) as mock_refresh:
            await cc.maybe_refresh_summary(db, redis, 1)
        mock_refresh.assert_awaited_once_with(db, redis, 1)

    async def test_skips_when_not_multiple(self):
        db = _mock_db()
        redis = AsyncMock()
        redis.llen.return_value = SUMMARY_INTERVAL - 1
        cc = ConversationContext()
        with patch.object(cc, "_refresh_summary", new_callable=AsyncMock) as mock_refresh:
            await cc.maybe_refresh_summary(db, redis, 1)
        mock_refresh.assert_not_awaited()

    async def test_skips_when_redis_unavailable(self):
        db = _mock_db()
        cc = ConversationContext()
        with patch.object(cc, "_refresh_summary", new_callable=AsyncMock) as mock_refresh:
            await cc.maybe_refresh_summary(db, None, 1)
        mock_refresh.assert_not_awaited()


class TestRefreshSummary:
    async def test_updates_summary_and_memory(self):
        db = _mock_db()
        conv = _conv(summary=None)
        db.get = AsyncMock(return_value=conv)
        db.execute.return_value = _result(first=None, rows=[])
        redis = AsyncMock()
        redis.lrange.return_value = [
            json.dumps({"role": "user", "content": "I want red shoes under 100k"}),
        ]
        cc = ConversationContext()
        with (
            patch.object(
                cc,
                "_call_summary_llm",
                new_callable=AsyncMock,
                return_value={"summary": "Wants red shoes.", "memory": {"budget": "100k"}},
            ),
            patch.object(cc, "_save_memory", new_callable=AsyncMock) as mock_save,
        ):
            await cc._refresh_summary(db, redis, 1)
        assert conv.summary == "Wants red shoes."
        db.commit.assert_awaited()
        mock_save.assert_awaited_once_with(db, "256700000000", {"budget": "100k"})

    async def test_keeps_summary_when_llm_fails(self):
        db = _mock_db()
        conv = _conv(summary="existing")
        db.get = AsyncMock(return_value=conv)
        redis = AsyncMock()
        redis.lrange.return_value = []
        cc = ConversationContext()
        with (
            patch.object(cc, "_call_summary_llm", new_callable=AsyncMock, return_value=None),
            patch.object(cc, "_save_memory", new_callable=AsyncMock),
        ):
            await cc._refresh_summary(db, redis, 1)
        assert conv.summary == "existing"


class TestBackfillFromChatLog:
    async def test_backfills_thread_messages(self):
        db = _mock_db()
        row1 = MagicMock()
        row1.thread_messages = [{"sender": "user", "text": "hello"}, {"sender": "ai", "text": "hi!"}]
        row1.user_text = None
        row1.response_text = None
        db.execute.return_value = _result(rows=[row1])
        cc = ConversationContext()
        await cc._backfill_from_chat_log(db, _conv())
        added = [c.args[0] for c in db.add.call_args_list]
        assert len(added) == 2
        assert added[0].role == "user"
        assert added[0].content == "hello"
        assert added[1].role == "assistant"
        assert added[1].content == "hi!"


class TestLoadMessagesRedis:
    async def test_skips_corrupt_entries(self):
        redis = AsyncMock()
        redis.lrange.return_value = ["not-json", json.dumps({"role": "user", "content": "ok"})]
        cc = ConversationContext()
        messages = await cc._load_messages_redis(redis, 1, 20)
        assert len(messages) == 1
        assert messages[0]["content"] == "ok"

    async def test_returns_empty_without_redis(self):
        cc = ConversationContext()
        messages = await cc._load_messages_redis(None, 1, 20)
        assert messages == []