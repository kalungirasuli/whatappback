from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import require_client
from src.core.dependencies import get_db, get_redis
from src.services.reranker import RerankedResult


def _make_client_user():
    from src.domain.models import User
    from src.domain.enums import UserRole
    import datetime
    u = User(phone_number="256700000000", name="Buyer", role=UserRole.client, is_verified=True, is_banned=False,
             created_at=datetime.datetime.now(datetime.timezone.utc), last_active_at=datetime.datetime.now(datetime.timezone.utc))
    u.id = 1
    return u


def _mock_product(pid):
    p = MagicMock()
    p.id = pid
    p.name = f"Product {pid}"
    p.price = 50000.0
    p.currency = "UGX"
    p.category = "Clothing"
    p.images = []
    p.merchant = MagicMock()
    p.merchant.business_name = "Test Shop"
    return p


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestSearchBatch:
    async def test_single_image_no_text(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_mock_product(1)])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.search.execute_intent_searches", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = [
                ("photo.png", [RerankedResult(product_id=1, score=0.9, rank=1, match_label="Match", metadata={"product_name": "Shirt"})]),
            ]

            fake_img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            resp = await client.post(
                "/api/search/batch",
                files={"files": ("photo.png", fake_img, "image/png")},
                data={"query": ""},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert len(data["sections"]) == 1
        assert data["sections"][0]["label"] == "photo.png"
        assert data["sections"][0]["total"] == 1

    async def test_multiple_images(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_mock_product(1), _mock_product(2)])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.search.execute_intent_searches", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = [
                ("img1.png", [RerankedResult(product_id=1, score=0.9, rank=1, match_label="Match")]),
                ("img2.png", [RerankedResult(product_id=2, score=0.8, rank=1, match_label="Match")]),
            ]

            fake = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            resp = await client.post(
                "/api/search/batch",
                files=[
                    ("files", ("img1.png", fake, "image/png")),
                    ("files", ("img2.png", fake, "image/png")),
                ],
                data={"query": ""},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sections"]) == 2

    async def test_no_images_text_only(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_mock_product(5)])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        from src.workers.nlu_router import NLUResult
        from src.services.llm_nlu import SearchIntent

        with (
            patch("src.api.routes.search.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.search.extract_nlu", new_callable=AsyncMock) as mock_nlu,
        ):
            mock_nlu.return_value = NLUResult(
                intent="product_search",
                entities={"product_name": "laptop"},
                confidence=0.8,
                is_multi_intent=False,
                search_intents=[SearchIntent(type="product_search", description="laptop", entities={"product_name": "laptop"})],
            )
            mock_exec.return_value = [
                ("laptop", [RerankedResult(product_id=5, score=0.85, rank=1, match_label="Exact")]),
            ]

            resp = await client.post(
                "/api/search/batch",
                data={"query": "laptop under 500000"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sections"]) == 1
        assert data["sections"][0]["results"][0]["product_id"] == 5

    async def test_no_images_no_text_returns_400(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        resp = await client.post("/api/search/batch", data={"query": ""})
        assert resp.status_code == 400
        assert "At least one image or a text query is required" in resp.json()["detail"]

    async def test_requires_auth(self, client):
        resp = await client.post("/api/search/batch", data={"query": "test"})
        assert resp.status_code == 401

    async def test_file_too_large(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        huge = b"x" * (11 * 1024 * 1024)
        resp = await client.post(
            "/api/search/batch",
            files={"files": ("big.png", huge, "image/png")},
            data={"query": ""},
        )
        assert resp.status_code == 400
        assert "exceeds 10MB" in resp.json()["detail"]
