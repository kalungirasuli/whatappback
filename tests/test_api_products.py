import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import get_current_user
from src.core.dependencies import get_db
from src.domain.models import User, Merchant, Product, ProductImage
from src.domain.enums import UserRole, ProductStatus


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


def _make_client_user(user_id=2, phone="256700111111"):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = User(
        phone_number=phone,
        name="Buyer Jane",
        role=UserRole.client,
        is_verified=True,
        is_banned=False,
        created_at=now,
        last_active_at=now,
    )
    user.id = user_id
    return user


def _mock_merchant(merchant_id=1, phone="256700000000"):
    m = MagicMock()
    m.id = merchant_id
    m.phone_number = phone
    m.business_name = "Test Shop"
    m.category = "Electronics"
    return m


def _mock_product(product_id=1, merchant_id=1, name="Shirt"):
    p = MagicMock()
    p.id = product_id
    p.merchant_id = merchant_id
    p.name = name
    p.brand = "BrandX"
    p.category = "Clothing"
    p.price = 50000.0
    p.currency = "UGX"
    p.stock_qty = 10
    p.status = MagicMock()
    p.status.value = "active"
    p.qdrant_point_id = None
    p.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    p.updated_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    p.images = []
    return p


def _mock_result(scalar_value=None, scalars_list=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar_value
    r.scalar.return_value = scalar_value if scalar_value is not None else (len(scalars_list) if scalars_list is not None else 0)
    if scalars_list is not None:
        r.scalars.return_value.all.return_value = scalars_list
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


class TestCreateProduct:
    async def test_create_product_as_shop_owner(self, client):
        merchant_user = _make_merchant_user()
        db_merchant = _mock_merchant()

        app.dependency_overrides[get_current_user] = lambda: merchant_user

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(),
        ]

        async def fake_refresh(obj):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 42
            if hasattr(obj, "created_at"):
                obj.created_at = datetime.datetime(
                    2024, 1, 1, tzinfo=datetime.timezone.utc
                )

        mock_session.refresh = AsyncMock(side_effect=fake_refresh)
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.post(
            "/api/products",
            params={"name": "Shirt", "category": "Clothing", "price": 50000},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Shirt"
        assert data["category"] == "Clothing"
        assert data["price"] == 50000
        assert data["status"] == "pending_moderation"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited()

    async def test_create_product_without_shop_not_found(self, client):
        client_user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: client_user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=None),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.post(
            "/api/products",
            params={"name": "Shirt", "category": "Clothing", "price": 50000},
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestListMerchantProducts:
    async def test_list_merchant_products(self, client):
        merchant_user = _make_merchant_user()
        db_merchant = _mock_merchant()
        product = _mock_product()

        app.dependency_overrides[get_current_user] = lambda: merchant_user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalars_list=[product]),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/products")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Shirt"
        assert data[0]["price"] == 50000


class TestGetProductDetail:
    async def test_get_product_detail_public(self, client):
        product = _mock_product()
        product.merchant = _mock_merchant()
        product.images = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = _mock_result(scalar_value=product)
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/products/1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["name"] == "Shirt"
        assert data["merchant"]["business_name"] == "Test Shop"


class TestUpdateProduct:
    async def test_update_product_owner(self, client):
        merchant_user = _make_merchant_user()
        db_merchant = _mock_merchant()
        product = _mock_product()

        app.dependency_overrides[get_current_user] = lambda: merchant_user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalar_value=product),
        ]
        mock_session.refresh = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.put(
            "/api/products/1",
            params={"name": "Updated Shirt", "price": 75000},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Shirt"
        assert data["price"] == 75000
        mock_session.commit.assert_awaited()

    async def test_update_product_not_owner_forbidden(self, client):
        merchant_user = _make_merchant_user(user_id=1, phone="256700000000")
        db_merchant = _mock_merchant(merchant_id=1)

        app.dependency_overrides[get_current_user] = lambda: merchant_user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalar_value=None),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.put(
            "/api/products/999",
            params={"name": "Hacked"},
        )

        assert resp.status_code == 404
        assert "not owned" in resp.json()["detail"].lower()


class TestDeleteProduct:
    async def test_delete_product(self, client):
        merchant_user = _make_merchant_user()
        db_merchant = _mock_merchant()
        product = _mock_product()
        product.qdrant_point_id = None

        app.dependency_overrides[get_current_user] = lambda: merchant_user

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalar_value=db_merchant),
            _mock_result(scalar_value=product),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.delete("/api/products/1")

        assert resp.status_code == 200
        assert "deleted" in resp.json()["message"].lower()
        mock_session.delete.assert_called_once()
        mock_session.commit.assert_awaited()


class TestPublicEndpoints:
    async def test_latest_products_public(self, client):
        product = _mock_product()
        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalars_list=[product]),
            _mock_result(scalar_value=1),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/products/public/latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Shirt"

    async def test_products_by_category(self, client):
        product = _mock_product()
        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            _mock_result(scalars_list=[product]),
            _mock_result(scalar_value=1),
        ]
        app.dependency_overrides[get_db] = lambda: mock_session

        resp = await client.get("/api/products/public/category/Clothing")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "Clothing"
