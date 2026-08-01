from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.admin.routes.merchants import router
from src.core.dependencies import get_db
from src.admin.auth import get_current_admin
from src.domain.enums import MerchantStatus


def _make_merchant(mid=1, phone="+256700000000", name="Test Shop", category="Electronics",
                   status=MerchantStatus.approved, created_at=None):
    m = MagicMock()
    m.id = mid
    m.phone_number = phone
    m.business_name = name
    m.category = category
    m.status = status
    m.created_at = created_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return m


def _mock_admin():
    admin = MagicMock()
    admin.id = 1
    admin.email = "admin@test.com"
    admin.role = MagicMock(value="superadmin")
    admin.is_active = True
    return admin


def _mock_result(scalar_value=None, scalars_list=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    if scalars_list is not None:
        result.scalars.return_value.all.return_value = scalars_list
    return result


def _build_app(mock_db):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    async def override_admin():
        return _mock_admin()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_admin] = override_admin
    return app


class TestListMerchants:
    def test_list_all_merchants(self):
        merchants = [
            _make_merchant(mid=1, name="Shop A"),
            _make_merchant(mid=2, name="Shop B"),
        ]
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=merchants)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants")

        assert response.status_code == 200
        data = response.json()
        assert len(data["merchants"]) == 2
        assert data["merchants"][0]["business_name"] == "Shop A"
        assert data["page"] == 1
        assert data["size"] == 20

    def test_list_merchants_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants")

        assert response.status_code == 200
        assert response.json()["merchants"] == []

    def test_list_merchants_with_status_filter(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants", params={"status": "suspended"})

        assert response.status_code == 200
        mock_db.execute.assert_awaited_once()

    def test_list_merchants_pagination(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants", params={"page": 2, "size": 5})

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["size"] == 5


class TestGetMerchant:
    def test_get_merchant_found(self):
        m = _make_merchant(mid=42, name="Big Shop")
        mock_db = AsyncMock()

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=m)
            return _mock_result(scalars_list=[])

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants/42")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 42
        assert data["business_name"] == "Big Shop"
        assert data["status"] == "approved"

    def test_get_merchant_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants/999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_merchant_includes_products(self):
        m = _make_merchant(mid=1)
        product = MagicMock()
        product.id = 10
        product.name = "Widget"
        product.price = 25000.0
        product.currency = "UGX"
        product.stock_qty = 15
        product.status = MagicMock(value="active")

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=m)
            return _mock_result(scalars_list=[product])

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/merchants/1")

        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) == 1
        assert data["products"][0]["name"] == "Widget"


class TestSuspendMerchant:
    def test_suspend_success(self):
        m = _make_merchant(mid=10, name="Bad Shop")
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=m)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/10/suspend")

        assert response.status_code == 200
        assert response.json()["status"] == "suspended"
        assert "Bad Shop" in response.json()["message"]
        mock_db.commit.assert_awaited_once()

    def test_suspend_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/999/suspend")

        assert response.status_code == 404

    def test_suspend_sets_status(self):
        m = _make_merchant(mid=5, status=MerchantStatus.approved)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=m)
        app = _build_app(mock_db)
        client = TestClient(app)

        client.post("/admin/merchants/5/suspend")

        assert m.status == MerchantStatus.suspended


class TestReactivateMerchant:
    def test_reactivate_success(self):
        m = _make_merchant(mid=11, name="Suspended Shop", status=MerchantStatus.suspended)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=m)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/11/reactivate")

        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        mock_db.commit.assert_awaited_once()

    def test_reactivate_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/999/reactivate")

        assert response.status_code == 404

    def test_reactivate_sets_approved(self):
        m = _make_merchant(mid=6, status=MerchantStatus.suspended)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=m)
        app = _build_app(mock_db)
        client = TestClient(app)

        client.post("/admin/merchants/6/reactivate")

        assert m.status == MerchantStatus.approved


class TestBanMerchant:
    def test_ban_success(self):
        m = _make_merchant(mid=12, name="Banned Shop")
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=m)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/12/ban")

        assert response.status_code == 200
        assert response.json()["status"] == "banned"
        assert "deactivated" in response.json()["message"].lower()

    def test_ban_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/999/ban")

        assert response.status_code == 404

    def test_ban_sets_status(self):
        m = _make_merchant(mid=7, status=MerchantStatus.approved)
        mock_db = AsyncMock()

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=m)
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        client.post("/admin/merchants/7/ban")

        assert m.status == MerchantStatus.banned

    def test_ban_deactivates_products(self):
        m = _make_merchant(mid=8)
        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=m)
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/merchants/8/ban")

        assert response.status_code == 200
        assert mock_db.execute.await_count == 2
