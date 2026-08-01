import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import get_current_user
from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole
from src.services.reranker import RerankedResult
from src.workers.nlu_router import NLUResult
from src.services.llm_nlu import SearchIntent


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


class TestChat:
    async def test_chat_greeting(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu:
            mock_nlu.return_value = NLUResult(
                intent="greeting",
                search_intents=[SearchIntent(type="greeting")],
            )

            resp = await client.post("/api/chat", data={"text": "hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Hello" in data["text"]

    async def test_chat_help(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu:
            mock_nlu.return_value = NLUResult(
                intent="help",
                search_intents=[SearchIntent(type="help")],
            )

            resp = await client.post("/api/chat", data={"text": "help"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Here's what I can do" in data["text"]

    async def test_chat_product_search(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_product = _mock_product()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_product])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        reranked = [RerankedResult(product_id=1, score=0.92, rank=1, match_label="Exact")]

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
        ):
            mock_nlu.return_value = NLUResult(
                intent="product_search",
                search_intents=[SearchIntent(type="product_search", description="red shoes")],
            )
            mock_exec.return_value = [("red shoes", reranked)]
            mock_gen.return_value = "RS-TEST"

            resp = await client.post("/api/chat", data={"text": "I need red shoes"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "search_results"
        assert data["result_code"] == "RS-TEST"
        assert len(data["sections"]) == 1
        assert data["sections"][0]["label"] == "red shoes"
        assert data["sections"][0]["results"][0]["product_id"] == 1
        assert data["sections"][0]["results"][0]["score"] == 0.92

    async def test_chat_empty_message_returns_greeting(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        resp = await client.post("/api/chat", data={"text": ""})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Hello" in data["text"]

    async def test_chat_no_search_results(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
        ):
            mock_nlu.return_value = NLUResult(
                intent="product_search",
                search_intents=[SearchIntent(type="product_search", description="xyz")],
            )
            mock_exec.return_value = [("xyz", [])]

            resp = await client.post("/api/chat", data={"text": "xyz"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Sorry" in data["text"]

    async def test_chat_requires_auth(self, client):
        resp = await client.post("/api/chat", data={"text": "hello"})
        assert resp.status_code == 401

    async def _post_image_chat(self, client, mock_db, mock_redis, files, text):
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_db] = lambda: mock_db
        resp = await client.post("/api/chat", data={"text": text}, files=files)
        return resp

    async def test_chat_image_caption_mismatch_adds_follow_up(self, client):
        """Car photo + 'I want shoes' must NOT drop the request: keep the car
        results AND ask the customer for the shoes detail."""
        car = _mock_product(product_id=7)
        car.category = "Cars"
        car.name = "Car 3"

        mock_redis = AsyncMock()
        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[car])))
        )

        reranked = [RerankedResult(product_id=7, score=0.95, rank=1, match_label="Exact")]

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._regex_nlu.build_product_search_intent") as mock_recover,
        ):
            mock_nlu.return_value = NLUResult(
                intent="visual_search",
                search_intents=[SearchIntent(type="visual_search", description="I see a car in your image")],
            )
            mock_desc.return_value = "I see a car in your image"
            mock_recover.return_value = None
            mock_exec.return_value = [("I see a car in your image", reranked)]
            mock_gen.return_value = "RS-CAR1"

            files = {"files": ("car.jpg", b"fakejpg", "image/jpeg")}
            resp = await self._post_image_chat(client, mock_db, mock_redis, files, "I want shoes")

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "search_results"
        assert data["result_code"] == "RS-CAR1"
        assert data["sections"][0]["results"][0]["name"] == "Car 3"
        follow_up = data["follow_up"]
        assert follow_up["type"] == "clarify"
        assert follow_up["topic"] == "shoes"
        assert follow_up["image_family"] == "vehicles"
        assert "I don't want you to miss out" in follow_up["prompt"]
        assert "shoes" in follow_up["prompt"]

    async def test_chat_image_caption_match_has_no_follow_up(self, client):
        """Caption matches the photo (car photo + 'I want a car') -> no follow-up."""
        car = _mock_product(product_id=7)
        car.category = "Cars"
        car.name = "Car 3"

        mock_redis = AsyncMock()
        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[car])))
        )

        reranked = [RerankedResult(product_id=7, score=0.95, rank=1, match_label="Exact")]

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
        ):
            mock_nlu.return_value = NLUResult(
                intent="product_search",
                search_intents=[
                    SearchIntent(type="product_search", description="car"),
                    SearchIntent(type="visual_search", description="I see a car in your image"),
                ],
            )
            mock_desc.return_value = "I see a car in your image"
            mock_exec.return_value = [("I see a car in your image", reranked)]
            mock_gen.return_value = "RS-CAR2"

            files = {"files": ("car.jpg", b"fakejpg", "image/jpeg")}
            resp = await self._post_image_chat(client, mock_db, mock_redis, files, "I want a car")

        assert resp.status_code == 200
        data = resp.json()
        assert "follow_up" not in data

    async def test_chat_recovers_dropped_caption_intent(self, client):
        """If the NLU drops the caption's product request when an image is present,
        the regex guard must recover it so no customer request is lost."""
        mock_redis = AsyncMock()
        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._regex_nlu.build_product_search_intent") as mock_recover,
        ):
            mock_nlu.return_value = NLUResult(
                intent="visual_search",
                search_intents=[SearchIntent(type="visual_search", description="I see a car in your image")],
            )
            mock_desc.return_value = "I see a car in your image"
            mock_recover.return_value = SearchIntent(type="product_search", description="shoes")
            mock_exec.return_value = [("I see a car in your image", [])]
            mock_gen.return_value = "RS-CAR3"

            files = {"files": ("car.jpg", b"fakejpg", "image/jpeg")}
            resp = await self._post_image_chat(client, mock_db, mock_redis, files, "I want shoes")

        assert resp.status_code == 200
        intents = mock_exec.call_args.args[0]
        assert any(si.type == "product_search" and si.description == "shoes" for si in intents)
        assert any(si.type == "visual_search" for si in intents)

    async def test_chat_logs_every_interaction(self, client):
        """Every reply goes through ChatLogService.log (single exit point)."""
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        mock_product = _mock_product()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_product])))
        )
        app.dependency_overrides[get_db] = lambda: mock_db

        reranked = [RerankedResult(product_id=1, score=0.92, rank=1, match_label="Exact")]

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._chat_log.log", new_callable=AsyncMock) as mock_log,
        ):
            mock_nlu.return_value = NLUResult(
                intent="product_search",
                search_intents=[SearchIntent(type="product_search", description="red shoes")],
            )
            mock_exec.return_value = [("red shoes", reranked)]
            mock_gen.return_value = "RS-LOG1"

            resp = await client.post("/api/chat", data={"text": "I need red shoes"})

        assert resp.status_code == 200
        assert mock_log.await_count == 1
        kwargs = mock_log.await_args.kwargs
        assert kwargs["phone_number"] == "256700000000"
        assert kwargs["user_message_type"] == "text"
        assert kwargs["user_text"] == "I need red shoes"
        assert kwargs["image_count"] == 0
        assert kwargs["reply"]["reply_type"] == "search_results"
        assert kwargs["reply"]["result_code"] == "RS-LOG1"
        assert kwargs["text_family"] == "shoes"
        assert kwargs["text_topic"] == "shoes"
        assert kwargs["image_family"] is None
        assert kwargs["latency_ms"] is not None

    async def test_chat_logs_greeting_turn(self, client):
        """Even a plain greeting is persisted."""
        user = _make_client_user()
        app.dependency_overrides[get_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch("src.api.routes.chat._chat_log.log", new_callable=AsyncMock) as mock_log,
        ):
            mock_nlu.return_value = NLUResult(
                intent="greeting",
                search_intents=[SearchIntent(type="greeting")],
            )

            resp = await client.post("/api/chat", data={"text": "hello"})

        assert resp.status_code == 200
        assert mock_log.await_count == 1
        kwargs = mock_log.await_args.kwargs
        assert kwargs["reply"]["reply_type"] == "text"
        assert kwargs["image_count"] == 0
