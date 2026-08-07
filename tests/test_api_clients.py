import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import get_current_user
from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole


def _make_client_user(user_id=3, phone="256700123456"):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = User(
        phone_number=phone,
        name="Jane Buyer",
        role=UserRole.client,
        is_verified=True,
        is_banned=False,
        created_at=now,
        last_active_at=now,
    )
    user.id = user_id
    return user


def _mock_result(scalar_value=None, scalars_list=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar_value
    if scalars_list is not None:
        r.scalars.return_value.all.return_value = scalars_list
    else:
        r.scalars.return_value.all.return_value = []
    return r


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


class TestGetProfile:
    async def test_get_profile(self, client):
        user = _make_client_user(user_id=7, phone="256700999999")
        app.dependency_overrides[get_current_user] = lambda: user

        resp = await client.get("/api/clients/me/profile")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 7
        assert data["phone"] == "256700999999"
        assert data["name"] == "Jane Buyer"
        assert data["role"] == "client"


class TestUpdateProfile:
    async def test_update_profile(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_session = AsyncMock()
        mock_session.refresh = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.put(
            "/api/clients/me/profile",
            params={"name": "New Name"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["phone"] == "256700123456"
        mock_session.commit.assert_awaited()


class TestInterests:
    async def test_list_interests(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_interest = MagicMock()
        mock_interest.id = 50
        mock_interest.product_id = 10
        mock_interest.merchant_id = 5
        mock_interest.status.value = "sent"
        mock_interest.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)

        mock_product = MagicMock()
        mock_product.id = 10
        mock_product.name = "Test Product"
        mock_product.price = 25000.0
        mock_product.currency = "UGX"
        mock_product.category = "Electronics"
        mock_interest.product = mock_product

        mock_img = MagicMock()
        mock_img.storage_url = "https://storage.example.com/img1.jpg"
        mock_img.is_primary = True
        mock_product.images = [mock_img]
        mock_product.merchant.business_name = "Test Shop"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_interest]
        mock_session.execute.return_value = mock_result
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/clients/me/interests")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 50
        assert data[0]["status"] == "sent"
        assert data[0]["product"]["id"] == 10
        assert data[0]["product"]["name"] == "Test Product"

    async def test_express_interest(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        product = MagicMock()
        product.id = 10
        product.name = "Test Product"
        product.price = 100000
        product.currency = "UGX"
        product.category = "shoes"
        product.brand = "Nike"
        product.stock_qty = 5
        product.merchant_id = 5
        product.merchant = MagicMock()
        product.merchant.id = 5
        product.merchant.business_name = "Test Shop"
        product.merchant.phone_number = "+256700000000"
        product.merchant.category = "shoes"
        product.merchant.location_lat = 0.3
        product.merchant.location_lng = 32.5
        product.images = [MagicMock()]

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=product),
            _mock_result(scalar_value=None),
        ]

        from src.domain.enums import InterestStatus

        async def fake_refresh(obj):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 50
            if hasattr(obj, "created_at"):
                obj.created_at = datetime.datetime(
                    2024, 1, 1, tzinfo=datetime.timezone.utc
                )
            if hasattr(obj, "status") and (obj.status is None or isinstance(obj.status, str)):
                obj.status = InterestStatus.sent

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.post("/api/clients/me/interests/10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["product"]["id"] == 10
        assert data["status"] == "sent"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited()

    async def test_remove_interest(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        interest = MagicMock()
        interest.id = 50

        mock_session = AsyncMock()
        mock_session.execute.return_value = _mock_result(scalar_value=interest)
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.delete("/api/clients/me/interests/10")

        assert resp.status_code == 200
        assert "removed" in resp.json()["message"].lower()
        mock_session.delete.assert_called_once()
        mock_session.commit.assert_awaited()
