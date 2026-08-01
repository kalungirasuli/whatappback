import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import require_client
from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole
from src.services.reranker import RerankedResult


def _make_client_user(user_id=1, phone="256700000000"):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = User(
        phone_number=phone,
        name="Buyer",
        role=UserRole.client,
        is_verified=True,
        is_banned=False,
        created_at=now,
        last_active_at=now,
    )
    user.id = user_id
    return user


def _mock_product(product_id=1):
    p = MagicMock()
    p.id = product_id
    p.name = "Shirt"
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
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


class TestSearchByText:
    async def test_search_by_text(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_product = _mock_product()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_product])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        reranked = [RerankedResult(product_id=1, score=0.95, rank=1, match_label="Exact")]

        with patch(
            "src.api.routes.search.search_pipeline"
        ) as mock_pipeline:
            mock_pipeline.search_by_text = AsyncMock(return_value=reranked)
            resp = await client.post(
                "/api/search/text",
                params={"query": "blue shirt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["product_id"] == 1
        assert data["results"][0]["score"] == 0.95
        assert data["results"][0]["match_label"] == "Exact"
        mock_pipeline.search_by_text.assert_awaited_once()


class TestSearchByImage:
    async def test_search_by_image(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        reranked = [RerankedResult(product_id=5, score=0.88, rank=1, match_label="Visual")]

        with patch(
            "src.api.routes.search.search_pipeline"
        ) as mock_pipeline:
            mock_pipeline.search_by_image = AsyncMock(return_value=reranked)

            fake_image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            resp = await client.post(
                "/api/search/image",
                files={"file": ("photo.png", fake_image, "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["product_id"] == 5
        mock_pipeline.search_by_image.assert_awaited_once()


class TestSearchByDescription:
    async def test_search_by_description_with_nlu(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_product = _mock_product()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_product])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        reranked = [RerankedResult(product_id=1, score=0.92, rank=1, match_label="Exact")]

        from src.workers.nlu_router import SearchIntent

        with (
            patch("src.api.routes.search.search_pipeline") as mock_pipeline,
            patch("src.api.routes.search.extract_nlu", new_callable=AsyncMock) as mock_nlu,
        ):
            mock_nlu.return_value = MagicMock(
                search_intents=[
                    SearchIntent(
                        type="product_search",
                        description="I need red shoes under 100k",
                        entities={"product_name": "shoes", "color": "red", "category": "shoes", "price_max": 100000},
                    )
                ]
            )
            mock_pipeline.search_by_text = AsyncMock(return_value=reranked)

            resp = await client.post(
                "/api/search/describe",
                data={"description": "I need red shoes under 100k"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "I need red shoes under 100k"
        assert data["total"] == 1
        assert data["results"][0]["product_id"] == 1
        assert data["results"][0]["score"] == 0.92
        mock_pipeline.search_by_text.assert_awaited_once()

    async def test_search_by_description_fallback_to_raw_text(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.search.search_pipeline") as mock_pipeline,
            patch("src.api.routes.search.extract_nlu", new_callable=AsyncMock) as mock_nlu,
        ):
            mock_nlu.return_value = MagicMock(
                search_intents=[MagicMock(type="greeting", spec=["type"])]
            )
            mock_pipeline.search_by_text = AsyncMock(return_value=[])

            resp = await client.post(
                "/api/search/describe",
                data={"description": "hello there"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        call_kwargs = mock_pipeline.search_by_text.call_args.kwargs
        assert call_kwargs["text"] == "hello there"

    async def test_search_by_description_no_text_returns_400(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        resp = await client.post(
            "/api/search/describe",
            data={"description": ""},
        )

        assert resp.status_code == 400

    async def test_search_by_description_with_query_price_filters(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.search.search_pipeline") as mock_pipeline,
            patch("src.api.routes.search.extract_nlu", new_callable=AsyncMock) as mock_nlu,
        ):
            mock_nlu.return_value = MagicMock(
                search_intents=[MagicMock(type="product_search", entities={}, spec=["type", "entities"])]
            )
            mock_pipeline.search_by_text = AsyncMock(return_value=[])

            resp = await client.post(
                "/api/search/describe",
                data={"description": "blue shirt"},
                params={"price_min": 10000, "price_max": 50000},
            )

        assert resp.status_code == 200
        call_kwargs = mock_pipeline.search_by_text.call_args.kwargs
        assert call_kwargs["price_range"] == (10000, 50000)


class TestSearchNearby:
    async def test_search_nearby(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        raw_results = [
            {
                "product_id": 3,
                "product_name": "Sneakers",
                "price": 120000.0,
                "currency": "UGX",
                "category": "Shoes",
                "business_name": "Shoe Hub",
                "distance_km": 2.5,
            }
        ]

        with patch(
            "src.services.postgres_service.get_nearby_products",
            new_callable=AsyncMock,
        ) as mock_nearby:
            mock_nearby.return_value = raw_results
            resp = await client.get(
                "/api/search/nearby",
                params={"lat": 0.3476, "lng": 32.5825, "km": 10},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["results"][0]["product_id"] == 3
        assert data["results"][0]["distance_km"] == 2.5
        assert data["results"][0]["match_label"] == "Nearby"
