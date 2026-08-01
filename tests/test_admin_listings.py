from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.admin.routes.listings import router
from src.core.dependencies import get_db
from src.admin.auth import get_current_admin
from src.domain.enums import ProductStatus


def _make_product(pid=1, merchant_id=1, name="Widget", brand=None, category="Electronics",
                  price=25000.0, currency="UGX", stock_qty=10, status=ProductStatus.active,
                  created_at=None):
    p = MagicMock()
    p.id = pid
    p.merchant_id = merchant_id
    p.name = name
    p.brand = brand
    p.category = category
    p.price = price
    p.currency = currency
    p.stock_qty = stock_qty
    p.status = status
    p.created_at = created_at or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return p


def _make_image(img_id=1, product_id=1, storage_url="https://cdn.test/img.jpg", is_primary=True):
    img = MagicMock()
    img.id = img_id
    img.product_id = product_id
    img.storage_url = storage_url
    img.is_primary = is_primary
    return img


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


class TestListProducts:
    def test_list_all_products(self):
        products = [
            _make_product(pid=1, name="Widget A"),
            _make_product(pid=2, name="Widget B"),
        ]
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=products)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings")

        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) == 2
        assert data["products"][0]["name"] == "Widget A"
        assert data["page"] == 1
        assert data["size"] == 20

    def test_list_products_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings")

        assert response.status_code == 200
        assert response.json()["products"] == []

    def test_list_products_filter_status(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings", params={"status": "active"})

        assert response.status_code == 200
        mock_db.execute.assert_awaited_once()

    def test_list_products_filter_merchant(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings", params={"merchant_id": 5})

        assert response.status_code == 200

    def test_list_products_pagination(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings", params={"page": 3, "size": 10})

        data = response.json()
        assert data["page"] == 3
        assert data["size"] == 10

    def test_list_products_includes_fields(self):
        p = _make_product(pid=10, brand="BrandX", price=99000.0)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalars_list=[p])
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings")

        data = response.json()["products"][0]
        assert data["id"] == 10
        assert data["brand"] == "BrandX"
        assert data["price"] == 99000.0
        assert data["currency"] == "UGX"
        assert data["status"] == "active"


class TestGetProduct:
    def test_get_product_found(self):
        p = _make_product(pid=7, name="Gadget")
        mock_db = AsyncMock()

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=p)
            return _mock_result(scalars_list=[])

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings/7")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 7
        assert data["name"] == "Gadget"
        assert data["images"] == []

    def test_get_product_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings/999")

        assert response.status_code == 404

    def test_get_product_with_images(self):
        p = _make_product(pid=3)
        img1 = _make_image(img_id=10, product_id=3, is_primary=True)
        img2 = _make_image(img_id=11, product_id=3, is_primary=False)

        mock_db = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_result(scalar_value=p)
            return _mock_result(scalars_list=[img1, img2])

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/listings/3")

        assert response.status_code == 200
        data = response.json()
        assert len(data["images"]) == 2
        assert data["images"][0]["is_primary"] is True
        assert data["images"][1]["is_primary"] is False


class TestDeactivateProduct:
    def test_deactivate_success(self):
        p = _make_product(pid=5, name="Active Product")
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=p)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/listings/5/deactivate")

        assert response.status_code == 200
        assert response.json()["status"] == "inactive"
        assert "Active Product" in response.json()["message"]
        mock_db.commit.assert_awaited_once()

    def test_deactivate_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/listings/999/deactivate")

        assert response.status_code == 404

    def test_deactivate_sets_status(self):
        p = _make_product(pid=8, status=ProductStatus.active)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=p)
        app = _build_app(mock_db)
        client = TestClient(app)

        client.post("/admin/listings/8/deactivate")

        assert p.status == ProductStatus.inactive


class TestReactivateProduct:
    def test_reactivate_success(self):
        p = _make_product(pid=6, name="Inactive Product", status=ProductStatus.inactive)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=p)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/listings/6/reactivate")

        assert response.status_code == 200
        assert response.json()["status"] == "active"
        mock_db.commit.assert_awaited_once()

    def test_reactivate_not_found(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=None)
        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.post("/admin/listings/999/reactivate")

        assert response.status_code == 404

    def test_reactivate_sets_active(self):
        p = _make_product(pid=9, status=ProductStatus.inactive)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_result(scalar_value=p)
        app = _build_app(mock_db)
        client = TestClient(app)

        client.post("/admin/listings/9/reactivate")

        assert p.status == ProductStatus.active
