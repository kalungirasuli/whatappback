import json
import datetime

from redis.asyncio import Redis

SESSION_PREFIX = "session:"
FILTER_PREFIX = "filters:"
WIZARD_PREFIX = "wizard:"
DEDUP_PREFIX = "dedup:"
RATE_LIMIT_PREFIX = "ratelimit:"

SEARCH_SESSION_TTL = 1800
MERCHANT_SESSION_TTL = 86400
WIZARD_TTL = 3600
DEDUP_TTL = 86400


async def get_session(redis: Redis, phone: str) -> dict | None:
    data = await redis.get(f"{SESSION_PREFIX}{phone}")
    if data:
        return json.loads(data)
    return None


async def set_session(redis: Redis, phone: str, data: dict, ttl: int = SEARCH_SESSION_TTL) -> None:
    await redis.setex(f"{SESSION_PREFIX}{phone}", ttl, json.dumps(data))


async def clear_session(redis: Redis, phone: str) -> None:
    await redis.delete(f"{SESSION_PREFIX}{phone}")


async def set_wizard_step(redis: Redis, phone: str, step: str, data: dict | None = None) -> None:
    payload = {"step": step, "data": data or {}}
    await redis.setex(f"{WIZARD_PREFIX}{phone}", WIZARD_TTL, json.dumps(payload))


async def get_wizard_step(redis: Redis, phone: str) -> dict | None:
    data = await redis.get(f"{WIZARD_PREFIX}{phone}")
    if data:
        return json.loads(data)
    return None


async def clear_wizard(redis: Redis, phone: str) -> None:
    await redis.delete(f"{WIZARD_PREFIX}{phone}")


async def is_duplicate(redis: Redis, message_id: str) -> bool:
    return bool(await redis.get(f"{DEDUP_PREFIX}{message_id}"))


async def mark_processed(redis: Redis, message_id: str) -> None:
    await redis.setex(f"{DEDUP_PREFIX}{message_id}", DEDUP_TTL, "1")
