import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import require_merchant
from src.core.dependencies import get_db
from src.domain.models import User
from src.domain.enums import UserRole


def _make_merchant_user(user_id=1, phone="256700000000"):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = User(
        phone_number=phone,
        name="Merchant Joe",
        role=UserRole.merchant,
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
    r.scalar.return_value = 0
    if scalars_list is not None:
        r.scalars.return_value.all.return_value = scalars_list
    else:
        r.scalars.return_value.all.return_value = []
    return r


def _mock_merchant(merchant_id=1):
    m = MagicMock()
    m.id = merchant_id
    m.phone_number = "256700000000"
    m.business_name = "Test Shop"
    m.category = "Electronics"
    m.location_lat = 0.3476
    m.location_lng = 32.5825
    m.status = MagicMock()
    m.status.value = "approved"
    m.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    return m


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


class TestDashboard:
    async def test_dashboard_stats(self, client):
        user = _make_merchant_user()
        db_merchant = _mock_merchant()

        mock_sub = MagicMock()
        mock_sub.plan = MagicMock()
        mock_sub.plan.name = "Growth"

        app.dependency_overrides[require_merchant] = lambda: user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            MagicMock(scalar=MagicMock(return_value=12)),
            MagicMock(scalar=MagicMock(return_value=8)),
            MagicMock(scalar=MagicMock(return_value=25)),
            MagicMock(scalar=MagicMock(return_value=7)),
            _mock_result(scalar_value=mock_sub),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/merchants/me/dashboard")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_products"] == 12
        assert data["active_products"] == 8
        assert data["total_interests"] == 25
        assert data["interests_this_week"] == 7
        assert data["plan_name"] == "Growth"


class TestSubscription:
    async def test_get_subscription(self, client):
        user = _make_merchant_user()
        db_merchant = _mock_merchant()

        mock_plan = MagicMock()
        mock_plan.id = 2
        mock_plan.name = "Growth"
        mock_plan.slug = MagicMock()
        mock_plan.slug.value = "growth"
        mock_plan.price = 50000.0
        mock_plan.currency = "UGX"
        mock_plan.max_products = 50
        mock_plan.max_images_per_product = 3
        mock_plan.features = "[]"

        mock_sub = MagicMock()
        mock_sub.plan = mock_plan
        mock_sub.started_at = datetime.datetime(
            2024, 6, 1, tzinfo=datetime.timezone.utc
        )
        mock_sub.expires_at = datetime.datetime(
            2024, 12, 31, tzinfo=datetime.timezone.utc
        )

        app.dependency_overrides[require_merchant] = lambda: user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalar_value=mock_sub),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/merchants/me/subscription")

        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["plan"]["name"] == "Growth"
        assert data["plan"]["slug"] == "growth"
        assert data["plan"]["price"] == 50000.0
        assert data["started_at"] is not None

    async def test_change_subscription(self, client):
        user = _make_merchant_user()
        db_merchant = _mock_merchant()

        new_plan = MagicMock()
        new_plan.id = 3
        new_plan.name = "Pro"
        new_plan.slug = MagicMock()
        new_plan.slug.value = "pro"
        new_plan.price = 150000.0
        new_plan.is_active = True

        existing_sub = MagicMock()
        existing_sub.status = "active"

        app.dependency_overrides[require_merchant] = lambda: user

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalar_value=new_plan),
            _mock_result(scalar_value=existing_sub),
        ]

        from src.domain.enums import SubscriptionStatus

        async def fake_refresh(obj):
            if hasattr(obj, "status") and isinstance(obj.status, str):
                obj.status = SubscriptionStatus(obj.status)
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 100
            if hasattr(obj, "started_at") and obj.started_at is None:
                obj.started_at = datetime.datetime.now(datetime.timezone.utc)

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.post(
            "/api/merchants/me/subscription",
            params={"plan_id": 3},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"]["name"] == "Pro"
        assert data["plan"]["price"] == 150000.0
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited()


class TestMerchantProfile:
    async def test_update_merchant_profile(self, client):
        user = _make_merchant_user()
        db_merchant = _mock_merchant()

        app.dependency_overrides[require_merchant] = lambda: user

        mock_session = AsyncMock()
        mock_session.execute.return_value = _mock_result(scalar_value=db_merchant)
        mock_session.refresh = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.put(
            "/api/merchants/me/profile",
            params={
                "business_name": "New Shop Name",
                "category": "Fashion",
                "location_lat": 0.5,
                "location_lng": 32.7,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["business_name"] == "New Shop Name"
        assert data["category"] == "Fashion"
        assert data["location_lat"] == 0.5
        assert data["location_lng"] == 32.7
        mock_session.commit.assert_awaited()
