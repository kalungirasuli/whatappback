from redis.asyncio import Redis

from src.services.redis_service import is_duplicate, mark_processed


async def check_and_mark(redis: Redis, message_id: str) -> bool:
    if await is_duplicate(redis, message_id):
        return True
    await mark_processed(redis, message_id)
    return False
