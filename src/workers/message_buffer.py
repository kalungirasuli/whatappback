import asyncio
import logging

logger = logging.getLogger(__name__)


class MessageBuffer:
    """Buffers incoming WhatsApp messages by sender, flushing as a batch
    after a timeout or when a text-only message arrives."""

    def __init__(self, flush_timeout: float = 2.0, max_batch: int = 15):
        self.flush_timeout = flush_timeout
        self.max_batch = max_batch
        self._buffers: dict[str, list[dict]] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._on_flush = None

    def set_on_flush(self, callback):
        self._on_flush = callback

    async def add(self, from_number: str, msg_data: dict) -> None:
        async with self._lock:
            is_new = from_number not in self._buffers
            self._buffers.setdefault(from_number, []).append(msg_data)

            if is_new:
                self._timers[from_number] = asyncio.create_task(
                    self._timer_flush(from_number)
                )

            if len(self._buffers[from_number]) >= self.max_batch:
                await self._flush(from_number)

    async def has_pending_for(self, from_number: str) -> bool:
        async with self._lock:
            return from_number in self._buffers

    async def flush_sender(self, from_number: str) -> None:
        async with self._lock:
            await self._flush(from_number)

    async def _timer_flush(self, from_number: str) -> None:
        await asyncio.sleep(self.flush_timeout)
        async with self._lock:
            await self._flush(from_number)

    async def _flush(self, from_number: str) -> None:
        batch = self._buffers.pop(from_number, None)
        timer = self._timers.pop(from_number, None)
        if timer and not timer.done():
            timer.cancel()

        if not batch:
            return

        if self._on_flush:
            try:
                await self._on_flush(from_number, batch)
            except Exception:
                logger.exception("MessageBuffer flush callback failed for %s", from_number)

    @property
    def has_pending(self) -> bool:
        return bool(self._buffers)

    async def clear(self) -> None:
        async with self._lock:
            for timer in self._timers.values():
                if not timer.done():
                    timer.cancel()
            self._buffers.clear()
            self._timers.clear()
