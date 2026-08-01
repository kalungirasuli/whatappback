import json
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.webhook import router, _buffer, _reset_buffer_for_testing


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


def _make_msg(mid, sender, msg_type, **kw):
    msg = {"id": mid, "from": sender, "type": msg_type, "timestamp": "1234567890"}
    if msg_type == "text":
        msg["text"] = {"body": kw.get("body", "hello")}
    elif msg_type == "image":
        msg["image"] = {"id": kw.get("media_id", "media_1"), "caption": kw.get("caption", "")}
    return msg


class TestImageBuffering:
    def setup_method(self):
        _reset_buffer_for_testing(max_batch=3)
        import src.gateway.webhook as wh
        self.mock_flush = AsyncMock()
        wh._buffer.set_on_flush(self.mock_flush)

    def _reset_wh(self):
        _reset_buffer_for_testing(max_batch=3)
        import src.gateway.webhook as wh
        wh._buffer.set_on_flush(self.mock_flush)

    def test_single_image_buffered_not_enqueued(self):
        app = _make_app()
        client = TestClient(app)
        msg = _make_msg("img_1", "+256700000001", "image", media_id="media_1")

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        # Image alone should buffer, not enqueue directly
        mock_enqueue.assert_not_awaited()

    def test_multiple_images_from_same_sender_batch_once(self):
        # max_batch=3 from setup_method — 3 images triggers immediate flush
        import src.gateway.webhook as wh
        app = _make_app()
        client = TestClient(app)
        messages = [
            _make_msg("img_1", "+256700000001", "image", media_id="m1"),
            _make_msg("img_2", "+256700000001", "image", media_id="m2"),
            _make_msg("img_3", "+256700000001", "image", media_id="m3"),
        ]

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock),
        ):
            body = _make_webhook_body(messages=messages)
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        # Max batch (3) reached, should flush
        self.mock_flush.assert_awaited_once()
        args = self.mock_flush.call_args[0]
        assert args[0] == "+256700000001"
        assert len(args[1]) == 3

    def test_images_from_different_senders_independent(self):
        self._reset_wh()
        import src.gateway.webhook as wh
        app = _make_app()
        client = TestClient(app)
        messages = [
            _make_msg("img_1", "+256700000001", "image", media_id="m1"),
            _make_msg("img_2", "+256700000002", "image", media_id="m2"),
        ]

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock),
        ):
            body = _make_webhook_body(messages=messages)
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        # No flush yet (2 images < max_batch=3, timers pending)
        self.mock_flush.assert_not_awaited()

    def test_solo_text_enqueued_directly(self):
        app = _make_app()
        client = TestClient(app)
        msg = _make_msg("txt_1", "+256700000001", "text", body="hello")

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        mock_enqueue.assert_awaited_once()
        payload = mock_enqueue.call_args[0][0]
        assert payload["type"] == "text"
        assert payload["text"]["body"] == "hello"

    def test_skip_empty_text_body(self):
        app = _make_app()
        client = TestClient(app)
        msg = _make_msg("txt_e", "+256700000001", "text", body="")

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        mock_enqueue.assert_not_awaited()

    def test_skip_non_text_non_image_type(self):
        app = _make_app()
        client = TestClient(app)
        msg = {"id": "loc_1", "from": "+256700000001", "type": "location", "timestamp": "123"}

        with (
            patch("src.gateway.webhook.verify_whatsapp_signature", return_value=True),
            patch("src.gateway.webhook.check_and_mark", new_callable=AsyncMock, return_value=False),
            patch("src.gateway.webhook.enqueue_message", new_callable=AsyncMock) as mock_enqueue,
        ):
            body = _make_webhook_body(messages=[msg])
            client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=v"})

        mock_enqueue.assert_not_awaited()
