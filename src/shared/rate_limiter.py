import time

from fastapi import Request, HTTPException, Depends
from redis.asyncio import Redis

from src.core.config import settings
from src.core.dependencies import get_redis

PHONE_RATE_KEY = "rl:phone:{phone}"
IP_RATE_KEY = "rl:ip:{ip}"
REGISTER_RATE_KEY = "rl:register:{phone}"


async def check_rate_limit(redis: Redis, key: str, max_count: int, window: int) -> bool:
    now = int(time.time())
    window_start = now - window
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window)
    results = await pipe.execute()
    count = results[1]
    return count >= max_count


REGISTER_WINDOW = 86400


async def check_register_rate_limit(redis: Redis, phone: str) -> bool:
    return await check_rate_limit(
        redis,
        REGISTER_RATE_KEY.format(phone=phone),
        settings.register_rate_limit_per_number,
        settings.register_rate_limit_window_hours * REGISTER_WINDOW,
    )


async def rate_limit_middleware(request: Request, redis: Redis = Depends(get_redis)):
    phone = request.headers.get("X-Phone-Number") or ""
    ip = request.client.host if request.client else "unknown"

    if phone:
        limited = await check_rate_limit(
            redis, PHONE_RATE_KEY.format(phone=phone),
            settings.rate_limit_per_phone, settings.rate_limit_window_seconds,
        )
        if limited:
            raise HTTPException(status_code=429, detail="Rate limit exceeded for this phone number")

    limited = await check_rate_limit(
        redis, IP_RATE_KEY.format(ip=ip),
        settings.rate_limit_per_ip, settings.rate_limit_window_seconds,
    )
    if limited:
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this IP")
