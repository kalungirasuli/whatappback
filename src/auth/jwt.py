import datetime

from fastapi import HTTPException
from jose import jwt, JWTError
from redis.asyncio import Redis

from src.core.config import settings

REFRESH_TOKEN_PREFIX = "refresh:"


class JWTService:
    def create_access_token(self, user_id: int, phone: str, role: str) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        expire = now + datetime.timedelta(minutes=settings.jwt_access_expire_minutes)
        payload = {
            "sub": str(user_id),
            "phone": phone,
            "role": role,
            "type": "access",
            "exp": expire,
            "iat": now,
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def create_refresh_token(self, user_id: int, phone: str, role: str) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        expire = now + datetime.timedelta(days=settings.jwt_refresh_expire_days)
        payload = {
            "sub": str(user_id),
            "phone": phone,
            "role": role,
            "type": "refresh",
            "exp": expire,
            "iat": now,
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    def decode_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            return payload
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    async def store_refresh_token(
        self, redis: Redis, user_id: int, token: str
    ) -> None:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        ttl = settings.jwt_refresh_expire_days * 86400
        await redis.setex(key, ttl, token)

    async def revoke_refresh_token(self, redis: Redis, user_id: int) -> None:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        await redis.delete(key)

    async def is_refresh_token_valid(
        self, redis: Redis, user_id: int, token: str
    ) -> bool:
        key = f"{REFRESH_TOKEN_PREFIX}{user_id}"
        stored = await redis.get(key)
        return stored is not None and stored == token
