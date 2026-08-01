from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.admin.routes.analytics import router
from src.core.dependencies import get_db
from src.admin.auth import get_current_admin


def _mock_admin():
    admin = MagicMock()
    admin.id = 1
    admin.email = "admin@test.com"
    admin.role = MagicMock(value="superadmin")
    admin.is_active = True
    return admin


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _mock_rows(rows):
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
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


class TestGetOverview:
    def test_overview_returns_all_sections(self):
        mock_db = AsyncMock()
        count_values = [10, 8, 1, 1, 25, 20, 50, 2, 100, 30, 500, 250]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")

        assert response.status_code == 200
        data = response.json()
        assert "merchants" in data
        assert "products" in data
        assert "buyers" in data
        assert "interests" in data
        assert "messages" in data

    def test_overview_merchant_counts(self):
        mock_db = AsyncMock()
        count_values = [10, 8, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["merchants"]["total"] == 10
        assert data["merchants"]["active"] == 8
        assert data["merchants"]["suspended"] == 1
        assert data["merchants"]["banned"] == 1

    def test_overview_product_counts(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 25, 20, 0, 0, 0, 0, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["products"]["total"] == 25
        assert data["products"]["active"] == 20

    def test_overview_buyer_counts(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 0, 0, 50, 2, 0, 0, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["buyers"]["total"] == 50
        assert data["buyers"]["banned"] == 2

    def test_overview_interest_counts(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 0, 0, 0, 0, 100, 30, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["interests"]["total"] == 100
        assert data["interests"]["responded"] == 30
        assert data["interests"]["response_rate"] == "30.0%"

    def test_overview_message_counts(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 500, 250]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["messages"]["total"] == 500
        assert data["messages"]["inbound"] == 250

    def test_overview_zero_interests_rate_na(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")
        data = response.json()

        assert data["interests"]["response_rate"] == "N/A"

    def test_overview_all_zeros(self):
        mock_db = AsyncMock()
        count_values = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        results = [_mock_scalar_result(v) for v in count_values]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["merchants"]["total"] == 0
        assert data["products"]["total"] == 0
        assert data["buyers"]["total"] == 0

    def test_overview_none_scalar_treated_as_zero(self):
        mock_db = AsyncMock()
        results = [_mock_scalar_result(None) for _ in range(12)]
        mock_db.execute = AsyncMock(side_effect=results)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["merchants"]["total"] == 0


class TestRecentMerchants:
    def test_recent_merchants_returns_list(self):
        mock_merchants = [
            MagicMock(id=3, business_name="Shop C", phone_number="+2567003",
                       status=MagicMock(value="approved"),
                       created_at=datetime(2025, 3, 1, tzinfo=timezone.utc)),
            MagicMock(id=2, business_name="Shop B", phone_number="+2567002",
                       status=MagicMock(value="suspended"),
                       created_at=datetime(2025, 2, 1, tzinfo=timezone.utc)),
        ]
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows(mock_merchants)

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/recent-merchants")

        assert response.status_code == 200
        data = response.json()
        assert len(data["merchants"]) == 2
        assert data["merchants"][0]["business_name"] == "Shop C"

    def test_recent_merchants_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/recent-merchants")

        assert response.status_code == 200
        assert response.json()["merchants"] == []

    def test_recent_merchants_custom_limit(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/recent-merchants", params={"limit": 5})

        assert response.status_code == 200
        mock_db.execute.assert_awaited_once()

    def test_recent_merchants_serializes_dates(self):
        mock_m = MagicMock(
            id=1,
            business_name="Shop",
            phone_number="+2567001",
            status=MagicMock(value="approved"),
            created_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([mock_m])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/recent-merchants")

        data = response.json()["merchants"][0]
        assert data["created_at"] == "2025-06-15T12:00:00+00:00"


class TestConversationVolume:
    def test_conversation_volume_returns_data(self):
        row1 = MagicMock(day=datetime(2025, 6, 1, tzinfo=timezone.utc), count=15)
        row2 = MagicMock(day=datetime(2025, 6, 2, tzinfo=timezone.utc), count=22)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([row1, row2])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/conversation-volume")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["data"][0]["count"] == 15
        assert data["data"][1]["count"] == 22

    def test_conversation_volume_empty(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/conversation-volume")

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_conversation_volume_custom_days(self):
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/conversation-volume", params={"days": 30})

        assert response.status_code == 200
        mock_db.execute.assert_awaited_once()

    def test_conversation_volume_serializes_dates(self):
        row = MagicMock(
            day=datetime(2025, 7, 4, 0, 0, 0, tzinfo=timezone.utc),
            count=8,
        )
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([row])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/conversation-volume")

        data = response.json()["data"][0]
        assert data["date"] == "2025-07-04T00:00:00+00:00"
        assert data["count"] == 8

    def test_conversation_volume_none_day(self):
        row = MagicMock(day=None, count=5)
        mock_db = AsyncMock()
        mock_db.execute.return_value = _mock_rows([row])

        app = _build_app(mock_db)
        client = TestClient(app)

        response = client.get("/admin/analytics/conversation-volume")

        data = response.json()["data"][0]
        assert data["date"] is None
        assert data["count"] == 5
