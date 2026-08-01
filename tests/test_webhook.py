import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.webhook import router
from src.core.dependencies import get_redis


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _make_webhook_body(messages=None):
    if messages is None:
        messages = []
    return json.dumps({
        "entry": [{
            "changes": [{
                "value": {
                    "messages": messages,
                }
            }]
        }]
    }).encode("utf-8")


def _make_message(mid="msg_001", sender="256700000000", msg_type="text", text_body="hello"):
    msg = {"id": mid, "from": sender, "type": msg_type, "timestamp": "1234567890"}
    if msg_type == "text":
        msg["text"] = {"body": text_body}
    return msg


class TestVerifyWebhook:
    def test_verify_success(self):
        app = _make_app()
        client = TestClient(app)
        response = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 200
        assert response.json() == 12345

    def test_verify_wrong_mode(self):
        app = _make_app()
        client = TestClient(app)
        response = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 403

    def test_verify_wrong_token(self):
        app = _make_app()
        client = TestClient(app)
        response = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 403

    def test_verify_missing_params(self):
        app = _make_app()
        client = TestClient(app)
        response = client.get("/webhook/whatsapp")
        assert response.status_code == 422


class TestHandleWebhook:
    def test_invalid_signature_returns_403(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        with patch("src.gateway.webhook.verify_whatsapp_signature", return_value=False):
            body = _make_webhook_body()
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=bad"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Invalid signature"

    def test_valid_signature_empty_entries(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        with patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True):
            body = _make_webhook_body(messages=[])
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=valid"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_processes_single_message(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        msg = _make_message(mid="msg_100")
        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False) as mock_dedupe,
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=valid"},
            )

        assert response.status_code == 200
        mock_dedupe.assert_awaited_once_with(mock_redis, "msg_100")
        mock_enqueue.assert_awaited_once()
        enqueued_payload = mock_enqueue.call_args[0][0]
        assert enqueued_payload["message_id"] == "msg_100"
        assert enqueued_payload["from"] == "256700000000"
        assert enqueued_payload["type"] == "text"

    def test_skips_duplicate_message(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        msg = _make_message(mid="msg_dup")
        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=True),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=valid"},
            )

        assert response.status_code == 200
        mock_enqueue.assert_not_awaited()

    def test_processes_multiple_messages(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        messages = [
            _make_message(mid="msg_a", sender="111"),
            _make_message(mid="msg_b", sender="222"),
            _make_message(mid="msg_c", sender="333"),
        ]
        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=messages)
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=valid"},
            )

        assert response.status_code == 200
        assert mock_enqueue.await_count == 3

    def test_skips_message_without_id(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        msg_no_id = {"from": "123", "type": "text", "timestamp": "123"}
        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock) as mock_dedupe,
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg_no_id])
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=valid"},
            )

        assert response.status_code == 200
        mock_dedupe.assert_not_awaited()
        mock_enqueue.assert_not_awaited()

    def test_no_signature_header_returns_403(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        with patch("src.gateway.webhook.verify_whatsapp_signature", return_value=False):
            body = _make_webhook_body()
            response = client.post("/webhook/whatsapp", content=body)

        assert response.status_code == 403

    def test_empty_body_invalid_signature(self):
        app = _make_app()
        mock_redis = AsyncMock()

        async def override_redis():
            return mock_redis

        app.dependency_overrides[get_redis] = override_redis
        client = TestClient(app)

        with patch("src.gateway.webhook.verify_whatsapp_signature", return_value=False):
            response = client.post(
                "/webhook/whatsapp",
                content=b"",
                headers={"X-Hub-Signature-256": "sha256=abc"},
            )

        assert response.status_code == 403
