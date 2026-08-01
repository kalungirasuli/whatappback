import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.auth.jwt import JWTService, REFRESH_TOKEN_PREFIX


class TestCreateAccessToken:
    async def test_create_access_token_contains_correct_claims(self):
        service = JWTService()
        token = service.create_access_token(
            user_id=42, phone="+256700000000", role="client"
        )

        payload = service.decode_token(token)
        assert payload["sub"] == "42"
        assert payload["phone"] == "+256700000000"
        assert payload["role"] == "client"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload
        assert payload["exp"] > payload["iat"]


class TestCreateRefreshToken:
    async def test_create_refresh_token_contains_correct_claims(self):
        service = JWTService()
        token = service.create_refresh_token(
            user_id=7, phone="+256700111111", role="merchant"
        )

        payload = service.decode_token(token)
        assert payload["sub"] == "7"
        assert payload["phone"] == "+256700111111"
        assert payload["role"] == "merchant"
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload


class TestDecodeToken:
    async def test_decode_valid_token(self):
        service = JWTService()
        token = service.create_access_token(
            user_id=1, phone="+256700000000", role="client"
        )

        payload = service.decode_token(token)
        assert payload["sub"] == "1"
        assert payload["type"] == "access"

    async def test_decode_expired_token(self):
        from jose import jwt as jose_jwt
        from src.core.config import settings

        service = JWTService()
        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "sub": "1",
            "phone": "+256700000000",
            "role": "client",
            "type": "access",
            "exp": now - datetime.timedelta(seconds=10),
            "iat": now - datetime.timedelta(minutes=20),
        }
        token = jose_jwt.encode(
            payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )

        with pytest.raises(HTTPException) as exc_info:
            service.decode_token(token)
        assert exc_info.value.status_code == 401

    async def test_decode_invalid_token(self):
        service = JWTService()

        with pytest.raises(HTTPException) as exc_info:
            service.decode_token("definitely.not.a.valid.jwt")
        assert exc_info.value.status_code == 401


class TestRefreshTokenStorage:
    async def test_store_and_revoke_refresh_token(self):
        service = JWTService()
        redis = AsyncMock()

        await service.store_refresh_token(redis, user_id=1, token="tok_abc")
        redis.setex.assert_awaited_once()
        call_args = redis.setex.call_args
        assert call_args[0][0] == f"{REFRESH_TOKEN_PREFIX}1"
        assert call_args[0][2] == "tok_abc"

        await service.revoke_refresh_token(redis, user_id=1)
        redis.delete.assert_awaited_once()
        assert redis.delete.call_args[0][0] == f"{REFRESH_TOKEN_PREFIX}1"

    async def test_refresh_token_valid_check(self):
        service = JWTService()
        redis = AsyncMock()

        redis.get.return_value = "valid_token_123"
        result = await service.is_refresh_token_valid(
            redis, user_id=5, token="valid_token_123"
        )
        assert result is True
        redis.get.assert_awaited_once_with(f"{REFRESH_TOKEN_PREFIX}5")

        redis.get.return_value = "different_token"
        result = await service.is_refresh_token_valid(
            redis, user_id=5, token="valid_token_123"
        )
        assert result is False

        redis.get.return_value = None
        result = await service.is_refresh_token_valid(
            redis, user_id=5, token="valid_token_123"
        )
        assert result is False
