import json
import asyncio
from collections.abc import Callable, Awaitable

from src.core.config import settings

_handler: dict[str, list[Callable[..., Awaitable[None]]]] = {}
_memory_queue: asyncio.Queue = asyncio.Queue()


def register_handler(job_type: str, handler: Callable[..., Awaitable[None]]) -> None:
    _handler.setdefault(job_type, []).append(handler)


async def enqueue_message(payload: dict) -> None:
    if settings.queue_type == "memory":
        await _memory_queue.put(payload)
    elif settings.queue_type == "sqs":
        pass
    elif settings.queue_type == "rabbitmq":
        pass
    elif settings.queue_type == "bullmq":
        pass


async def process_queue() -> None:
    while True:
        payload = await _memory_queue.get()
        job_type = payload.get("type", "incoming_message")
        handlers = _handler.get(job_type, [])
        for handler in handlers:
            try:
                await handler(payload)
            except Exception:
                pass
        _memory_queue.task_done()
