import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from src.api.main import app
from src.auth.dependencies import get_optional_current_user
from src.core.dependencies import get_db, get_redis
from src.domain.models import User
from src.domain.enums import UserRole
from src.services.reranker import RerankedResult
from src.services.llm_nlu import SearchIntent
from src.services.lisa_agent import AgentTurn
from src.workers.nlu_router import NLUResult


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


@pytest.fixture(autouse=True)
def mock_conversation_context():
    """The chat route wires durable conversation context (Redis+Postgres);

    unit tests here mock the service so they exercise chat.py only."""
    from src.api.routes import chat as chat_module

    with (
        patch.object(
            chat_module._conversation_context, "ensure_conversation", new_callable=AsyncMock
        ) as mock_ensure,
        patch.object(
            chat_module._conversation_context, "load_context", new_callable=AsyncMock
        ) as mock_load,
        patch.object(
            chat_module._conversation_context, "append", new_callable=AsyncMock
        ) as mock_append,
        patch.object(
            chat_module, "extract_nlu", new_callable=AsyncMock
        ) as mock_nlu,
        patch.object(chat_module._lisa, "_load_history", new_callable=AsyncMock) as mock_story,
        patch.object(chat_module._lisa, "seed_history", new_callable=AsyncMock) as mock_seed,
    ):
        mock_ensure.return_value = SimpleNamespace(id=1)
        mock_load.return_value = {"messages": []}
        mock_story.return_value = []
        mock_nlu.return_value = NLUResult(intent="product_search")
        yield {
            "ensure": mock_ensure,
            "load": mock_load,
            "append": mock_append,
            "seed": mock_seed,
            "extract_nlu": mock_nlu,
        }


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
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = AgentTurn(
                action="chat", reply="Hello! I'm Lisa 👋 How can I help you today?"
            )

            resp = await client.post("/api/chat", data={"text": "hello"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Hello" in data["text"]

    async def test_chat_help(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide:
            mock_decide.return_value = AgentTurn(
                action="chat",
                reply="Here's what I can do: tell me what you want or send a photo!",
            )

            resp = await client.post("/api/chat", data={"text": "help"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Here's what I can do" in data["text"]

    async def test_chat_product_search(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

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
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._lisa.present_results", new_callable=AsyncMock) as mock_present,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="red shoes")
            mock_present.return_value = ""
            mock_exec.return_value = [("red shoes", reranked)]
            mock_gen.return_value = "RS-TEST"

            resp = await client.post("/api/chat", data={"text": "I need red shoes"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] in ("search_results", "conversation")
        assert data["result_code"] == "RS-TEST"
        assert len(data["sections"]) == 1
        assert data["sections"][0]["label"] == "red shoes"
        assert data["sections"][0]["results"][0]["product_id"] == 1
        assert data["sections"][0]["results"][0]["score"] == 0.92

    async def test_chat_empty_message_returns_greeting(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

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
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch(
                "src.api.routes.chat.compose_no_match_reply",
                new_callable=AsyncMock,
                return_value="Sorry, I couldn't find anything for that yet. Try other words or send a photo!",
            ) as mock_no_match,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="xyz")
            mock_exec.return_value = [("xyz", [])]

            resp = await client.post("/api/chat", data={"text": "xyz"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "Sorry" in data["text"]
        mock_no_match.assert_awaited_once_with("xyz")

    async def test_chat_uses_literal_words_as_search_query(self, client):
        """The search query is the customer's own words, never an assumed
        category. E.g. 'find me blackskys' must search 'black sky', not shoes."""
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        recovered = SearchIntent(type="product_search", description="black sky")
        with (
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat.extract_nlu", new_callable=AsyncMock) as mock_nlu,
            patch(
                "src.api.routes.chat._regex_nlu.build_product_search_intent",
                return_value=recovered,
            ),
            patch(
                "src.api.routes.chat.compose_no_match_reply",
                new_callable=AsyncMock,
                return_value="no match",
            ),
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="black sky")
            mock_nlu.return_value = NLUResult(intent="chat", search_intents=[SearchIntent(type="chat")])
            mock_exec.return_value = []

            resp = await client.post("/api/chat", data={"text": "find me blackskys"})

        assert resp.status_code == 200
        intents = mock_exec.call_args.args[0]
        product = next(si for si in intents if si.type == "product_search")
        assert product.query == "black sky"

    async def test_chat_requires_auth(self, client):
        resp = await client.post("/api/chat", data={"text": "hello"})
        assert resp.status_code == 200

    async def _post_image_chat(self, client, mock_db, mock_redis, files, text):
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user
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
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._lisa.present_results", new_callable=AsyncMock) as mock_present,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._regex_nlu.build_product_search_intent") as mock_recover,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="I want shoes")
            mock_present.return_value = ""
            mock_desc.return_value = "I see a car in your image"
            mock_recover.return_value = None
            mock_exec.return_value = [("I see a car in your image", reranked)]
            mock_gen.return_value = "RS-CAR1"

            files = {"files": ("car.jpg", b"fakejpg", "image/jpeg")}
            resp = await self._post_image_chat(client, mock_db, mock_redis, files, "I want shoes")

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] in ("search_results", "conversation")
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
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._lisa.present_results", new_callable=AsyncMock) as mock_present,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="car")
            mock_present.return_value = ""
            mock_desc.return_value = "I see a car in your image"
            mock_exec.return_value = [("I see a car in your image", reranked)]
            mock_gen.return_value = "RS-CAR2"

            files = {"files": ("car.jpg", b"fakejpg", "image/jpeg")}
            resp = await self._post_image_chat(client, mock_db, mock_redis, files, "I want a car")

        assert resp.status_code == 200
        data = resp.json()
        assert "follow_up" not in data

    async def test_chat_search_builds_caption_and_visual_intents(self, client):
        """When Lisa decides to search, the caption request AND the photo are both
        searched so no customer request is ever lost."""
        mock_redis = AsyncMock()
        mock_db = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        with (
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._lisa.present_results", new_callable=AsyncMock) as mock_present,
            patch("src.api.routes.chat._describe_image", new_callable=AsyncMock) as mock_desc,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._regex_nlu.build_product_search_intent") as mock_recover,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="I want shoes")
            mock_present.return_value = ""
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
        app.dependency_overrides[get_optional_current_user] = lambda: user

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
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._lisa.present_results", new_callable=AsyncMock) as mock_present,
            patch("src.api.routes.chat.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.api.routes.chat._result_code_service.generate", new_callable=AsyncMock) as mock_gen,
            patch("src.api.routes.chat._result_code_service.store", new_callable=AsyncMock) as mock_store,
            patch("src.api.routes.chat._chat_log.log", new_callable=AsyncMock) as mock_log,
        ):
            mock_decide.return_value = AgentTurn(action="search", search_text="red shoes")
            mock_present.return_value = ""
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
        assert kwargs["reply"]["reply_type"] in ("search_results", "conversation")
        assert kwargs["reply"]["result_code"] == "RS-LOG1"
        assert kwargs["text_family"] == "shoes"
        assert kwargs["text_topic"] == "shoes"
        assert kwargs["image_family"] is None
        assert kwargs["latency_ms"] is not None

    async def test_chat_logs_greeting_turn(self, client):
        """Even a plain greeting is persisted."""
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("src.api.routes.chat._lisa.decide", new_callable=AsyncMock) as mock_decide,
            patch("src.api.routes.chat._chat_log.log", new_callable=AsyncMock) as mock_log,
        ):
            mock_decide.return_value = AgentTurn(
                action="chat", reply="Hello! I'm Lisa 👋 How can I help you today?"
            )

            resp = await client.post("/api/chat", data={"text": "hello"})

        assert resp.status_code == 200
        assert mock_log.await_count == 1
        kwargs = mock_log.await_args.kwargs
        assert kwargs["reply"]["reply_type"] == "text"
        assert kwargs["image_count"] == 0


class TestRecall:
    async def _recall_db(self, products):
        """db mock: interest query returns [], product query returns `products`."""
        mock_db = AsyncMock()
        product_result = MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=products))
            )
        )
        mock_db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # liked ids
            product_result,
        ]
        return mock_db

    async def test_recall_returns_full_product_sections(self, client):
        """Pasting an RS- code returns sections with images so the frontend
        renders product cards (and the closest match image) for the recall."""
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_product = _mock_product(product_id=7)
        mock_product.images = [
            MagicMock(storage_url="https://cdn/shoes.jpg", is_primary=True)
        ]
        mock_db = await self._recall_db([mock_product])
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "src.api.routes.chat._result_code_service.lookup",
            new_callable=AsyncMock,
        ) as mock_lookup:
            mock_lookup.return_value = {
                "code": "RS-ABC1",
                "search_query": "black sky",
                "image_description": None,
                "category": "skies",
                "price_min": None,
                "price_max": None,
                "product_count": 1,
                "product_ids": [7],
                "sample_products": [{"name": "black sky", "price": 1500}],
                "created_at": "2026-01-01T00:00:00+00:00",
            }

            resp = await client.post("/api/chat", data={"text": "RS-ABC1"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "recall"
        assert data["result_code"] == "RS-ABC1"
        assert len(data["sections"]) == 1
        section = data["sections"][0]
        assert section["results"][0]["product_id"] == 7
        assert section["results"][0]["name"] == "Shirt"
        assert section["results"][0]["images"][0]["url"] == "https://cdn/shoes.jpg"
        assert section["results"][0]["images"][0]["is_primary"] is True
        assert section["results"][0]["match_label"] == "Exact match"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["type"] == "search_results"

    async def test_recall_drops_unliked_related_but_keeps_closest(self, client):
        """On recall, only the closest match and liked related products are
        returned; unliked related items are dropped."""
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        closest = _mock_product(product_id=1)
        liked_related = _mock_product(product_id=2)
        unliked_related = _mock_product(product_id=3)
        mock_db = await self._recall_db([closest, liked_related, unliked_related])
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch(
                "src.api.routes.chat._result_code_service.lookup",
                new_callable=AsyncMock,
            ) as mock_lookup,
            patch(
                "src.api.routes.chat._liked_product_ids",
                new_callable=AsyncMock,
            ) as mock_liked,
        ):
            mock_lookup.return_value = {
                "code": "RS-LIKE1",
                "search_query": "shoes",
                "image_description": None,
                "category": "shoes",
                "price_min": None,
                "price_max": None,
                "product_count": 3,
                "product_ids": [1, 2, 3],
                "sample_products": [],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            mock_liked.return_value = {2}

            resp = await client.post("/api/chat", data={"text": "RS-LIKE1"})

        assert resp.status_code == 200
        data = resp.json()
        section = data["sections"][0]
        returned_ids = [r["product_id"] for r in section["results"]]
        assert returned_ids == [1, 2]
        assert section["results"][0]["match_label"] == "Exact match"
        assert section["results"][1]["match_label"] == "Related"

    async def test_recall_unknown_code_returns_text(self, client):
        user = _make_client_user()
        app.dependency_overrides[get_optional_current_user] = lambda: user

        mock_redis = AsyncMock()
        app.dependency_overrides[get_redis] = lambda: mock_redis

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "src.api.routes.chat._result_code_service.lookup",
            new_callable=AsyncMock,
        ) as mock_lookup:
            mock_lookup.return_value = None

            resp = await client.post("/api/chat", data={"text": "RS-NOPE"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply_type"] == "text"
        assert "couldn't find" in data["text"]
