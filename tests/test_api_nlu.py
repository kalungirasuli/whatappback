from unittest.mock import AsyncMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import require_client

from src.services.llm_nlu import SearchIntent
from src.workers.nlu_router import NLUResult


def _make_client_user():
    from src.domain.models import User
    from src.domain.enums import UserRole
    import datetime
    u = User(phone_number="256700000000", name="Buyer", role=UserRole.client, is_verified=True, is_banned=False,
             created_at=datetime.datetime.now(datetime.timezone.utc), last_active_at=datetime.datetime.now(datetime.timezone.utc))
    u.id = 1
    return u


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestExtractNLU:
    async def test_extract_text_only(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        with patch("src.api.routes.nlu.extract_nlu", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = NLUResult(
                intent="product_search",
                entities={"product_name": "red shoes"},
                confidence=0.85,
                is_multi_intent=False,
                search_intents=[
                    SearchIntent(type="product_search", description="red shoes", entities={"product_name": "red shoes"}),
                ],
            )

            resp = await client.post("/api/nlu/extract", params={"text": "red shoes"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"] == "product_search"
        assert data["confidence"] == 0.85
        assert not data["is_multi_intent"]
        assert len(data["intents"]) == 1
        assert data["intents"][0]["type"] == "product_search"

    async def test_extract_multi_intent(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        nlu_result = NLUResult(
            intent="visual_search",
            entities={},
            confidence=0.85,
            is_multi_intent=True,
            search_intents=[
                SearchIntent(type="visual_search", description="User uploaded an image"),
                SearchIntent(type="product_search", description="blue shirt", entities={"product_name": "blue shirt", "color": "blue"}),
            ],
        )

        with patch("src.api.routes.nlu.extract_nlu", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = nlu_result
            resp = await client.post("/api/nlu/extract", params={"text": "find this and also blue shirt", "has_image": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_multi_intent"]
        assert len(data["intents"]) == 2

    async def test_extract_greeting(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        with patch("src.api.routes.nlu.extract_nlu", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = NLUResult(
                intent="greeting",
                entities={},
                confidence=0.95,
                is_multi_intent=False,
                search_intents=[SearchIntent(type="greeting")],
            )
            resp = await client.post("/api/nlu/extract", params={"text": "hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"] == "greeting"

    async def test_extract_no_text(self, client):
        user = _make_client_user()
        app.dependency_overrides[require_client] = lambda: user

        with patch("src.api.routes.nlu.extract_nlu", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = NLUResult(
                intent="unknown", entities={}, confidence=0.0, is_multi_intent=False, search_intents=[]
            )
            resp = await client.post("/api/nlu/extract", params={"text": ""})

        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_intent"] == "unknown"

    async def test_requires_auth(self, client):
        resp = await client.post("/api/nlu/extract", params={"text": "test"})
        assert resp.status_code == 401
