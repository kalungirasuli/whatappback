import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import get_current_user
from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole


def _make_user(
    user_id=1,
    phone="256700000000",
    role=UserRole.client,
    is_banned=False,
    name=None,
):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = User(
        phone_number=phone,
        name=name,
        role=role,
        is_verified=True,
        is_banned=is_banned,
        created_at=now,
        last_active_at=now,
    )
    user.id = user_id
    return user


def _mock_db_session(first_result=None, second_result=None):
    session = AsyncMock()
    results = []
    if first_result is not None:
        results.append(first_result)
    if second_result is not None:
        results.append(second_result)
    if results:
        session.execute.side_effect = results
    else:
        mock_r = MagicMock()
        mock_r.scalar_one_or_none.return_value = None
        mock_r.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_r

    async def fake_refresh(obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = 1

    session.refresh = AsyncMock(side_effect=fake_refresh)
    session.add = MagicMock()
    return session


@pytest.fixture(autouse=True)
def reset_otp_and_overrides():
    import src.auth.main as auth_main

    auth_main.otp_service_instance = None
    yield
    auth_main.otp_service_instance = None
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


class TestRequestOTP:
    async def test_request_otp_success(self, client):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        app.dependency_overrides[get_redis] = lambda: mock_redis

        with patch("src.auth.otp.send_text", new_callable=AsyncMock) as mock_send:
            resp = await client.post(
                "/api/auth/request-otp", json={"phone": "+256700000000"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "OTP sent" in data["message"]
        assert data["expires_in"] == 300
        mock_send.assert_awaited_once()

    async def test_request_otp_invalid_phone(self, client):
        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        resp = await client.post(
            "/api/auth/request-otp", json={"phone": "abc"}
        )

        assert resp.status_code == 400
        assert "Invalid phone" in resp.json()["detail"]


class TestVerifyOTP:
    async def test_verify_otp_creates_new_user(self, client):
        mock_redis = AsyncMock()
        mock_session = _mock_db_session(first_result=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: mock_session

        mock_otp = MagicMock()
        mock_otp.verify = AsyncMock(return_value=True)
        import src.auth.main as auth_main
        auth_main.otp_service_instance = mock_otp

        resp = await client.post(
            "/api/auth/verify-otp",
            json={"phone": "+256700000000", "code": "123456", "role": "client"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["phone"] == "256700000000"
        assert data["user"]["role"] == "client"
        assert data["user"]["is_verified"] is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited()

    async def test_verify_otp_existing_user(self, client):
        existing_user = _make_user(user_id=10, phone="256700000000")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user

        mock_redis = AsyncMock()
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.refresh = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: mock_session

        mock_otp = MagicMock()
        mock_otp.verify = AsyncMock(return_value=True)
        import src.auth.main as auth_main
        auth_main.otp_service_instance = mock_otp

        resp = await client.post(
            "/api/auth/verify-otp",
            json={"phone": "+256700000000", "code": "123456", "role": "client"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["phone"] == "256700000000"
        mock_session.add.assert_not_called()
        mock_session.commit.assert_awaited()

    async def test_verify_otp_wrong_code_returns_401(self, client):
        mock_redis = AsyncMock()
        mock_session = _mock_db_session()
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: mock_session

        mock_otp = MagicMock()
        mock_otp.verify = AsyncMock(return_value=False)
        import src.auth.main as auth_main
        auth_main.otp_service_instance = mock_otp

        resp = await client.post(
            "/api/auth/verify-otp",
            json={"phone": "+256700000000", "code": "000000", "role": "client"},
        )

        assert resp.status_code == 401
        assert "Invalid or expired OTP" in resp.json()["detail"]

    async def test_verify_otp_banned_user_returns_403(self, client):
        banned_user = _make_user(user_id=20, phone="256700000000", is_banned=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = banned_user

        mock_redis = AsyncMock()
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: mock_session

        mock_otp = MagicMock()
        mock_otp.verify = AsyncMock(return_value=True)
        import src.auth.main as auth_main
        auth_main.otp_service_instance = mock_otp

        resp = await client.post(
            "/api/auth/verify-otp",
            json={"phone": "+256700000000", "code": "123456", "role": "client"},
        )

        assert resp.status_code == 403
        assert "banned" in resp.json()["detail"].lower()


class TestRefreshToken:
    async def test_refresh_returns_new_access_token(self, client):
        from src.auth.jwt import JWTService

        jwt_svc = JWTService()
        refresh_token = jwt_svc.create_refresh_token(
            user_id=1, phone="256700000000", role="client"
        )

        mock_redis = AsyncMock()
        mock_redis.get.return_value = refresh_token
        app.dependency_overrides[get_redis] = lambda: mock_redis

        user = _make_user(user_id=1, phone="256700000000")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        decoded = jwt_svc.decode_token(data["access_token"])
        assert decoded["sub"] == "1"
        assert decoded["type"] == "access"

    async def test_refresh_invalid_token_returns_401(self, client):
        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "garbage.token.value"},
        )

        assert resp.status_code == 401


class TestMe:
    async def test_me_returns_current_user(self, client):
        user = _make_user(user_id=5, phone="256700123456", role=UserRole.client)
        app.dependency_overrides[get_current_user] = lambda: user

        resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer fake-token"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 5
        assert data["phone"] == "256700123456"
        assert data["role"] == "client"

    async def test_me_no_token_returns_401(self, client):
        resp = await client.get("/api/auth/me")

        assert resp.status_code in (401, 403)
