import asyncio
from unittest.mock import AsyncMock

import pytest

from src.workers.message_buffer import MessageBuffer


@pytest.fixture
def buffer():
    b = MessageBuffer(flush_timeout=0.5, max_batch=3)
    b.set_on_flush(AsyncMock())
    yield b


class TestMessageBuffer:
    async def test_add_single_message_does_not_flush_immediately(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        assert buffer._on_flush.await_count == 0

    async def test_add_reaches_max_batch_flushes_immediately(self, buffer):
        for i in range(3):
            await buffer.add("+256700000001", {"type": "image", "image": {"id": f"img_{i}"}})
        buffer._on_flush.assert_awaited_once()
        assert buffer._on_flush.call_args[0][0] == "+256700000001"
        assert len(buffer._on_flush.call_args[0][1]) == 3

    async def test_add_below_max_batch_does_not_flush(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_2"}})
        buffer._on_flush.assert_not_awaited()

    async def test_timer_flushes_after_timeout(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await asyncio.sleep(0.6)
        buffer._on_flush.assert_awaited_once()
        args = buffer._on_flush.call_args[0]
        assert args[0] == "+256700000001"
        assert len(args[1]) == 1

    async def test_flush_sender_flushes_immediately(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.flush_sender("+256700000001")
        buffer._on_flush.assert_awaited_once()

    async def test_has_pending_for_true_after_add(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        result = await buffer.has_pending_for("+256700000001")
        assert result

    async def test_has_pending_for_false_after_flush(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.flush_sender("+256700000001")
        result = await buffer.has_pending_for("+256700000001")
        assert not result

    async def test_has_pending_for_no_sender(self, buffer):
        result = await buffer.has_pending_for("+256999999999")
        assert not result

    async def test_multiple_senders_independent(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.add("+256700000002", {"type": "image", "image": {"id": "img_2"}})
        result = await buffer.has_pending_for("+256700000001")
        assert result
        await buffer.flush_sender("+256700000001")
        assert buffer._on_flush.await_count == 1
        result = await buffer.has_pending_for("+256700000001")
        assert not result
        result = await buffer.has_pending_for("+256700000002")
        assert result

    async def test_flush_with_no_pending_is_noop(self, buffer):
        await buffer.flush_sender("+256000000000")
        buffer._on_flush.assert_not_awaited()

    async def test_has_pending_property(self, buffer):
        assert not buffer.has_pending
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        assert buffer.has_pending
        await buffer.flush_sender("+256700000001")
        assert not buffer.has_pending

    async def test_clear_removes_all(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.add("+256700000002", {"type": "image", "image": {"id": "img_2"}})
        await buffer.clear()
        assert not buffer.has_pending
        assert await buffer.has_pending_for("+256700000001") is False
        assert await buffer.has_pending_for("+256700000002") is False

    async def test_on_flush_passes_correct_batch(self, buffer):
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_a"}})
        await buffer.add("+256700000001", {"type": "text", "text": "red shoes"})
        await buffer.flush_sender("+256700000001")
        buffer._on_flush.assert_awaited_once()
        args = buffer._on_flush.call_args[0]
        assert args[0] == "+256700000001"
        assert len(args[1]) == 2
        assert args[1][0]["type"] == "image"
        assert args[1][1]["type"] == "text"

    async def test_flush_callback_error_logged(self, buffer):
        buffer.set_on_flush(AsyncMock(side_effect=ValueError("oops")))
        await buffer.add("+256700000001", {"type": "image", "image": {"id": "img_1"}})
        await buffer.flush_sender("+256700000001")
        buffer._on_flush.assert_awaited_once()
