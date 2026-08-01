import hashlib
import hmac

from src.gateway.signature import verify_whatsapp_signature


APP_SECRET = "my_test_secret_key"


def _make_signature(payload: bytes, secret: str) -> str:
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={expected}"


class TestVerifyWhatsappSignature:
    def test_valid_signature(self):
        payload = b'{"entry": []}'
        signature = _make_signature(payload, APP_SECRET)
        assert verify_whatsapp_signature(payload, signature, APP_SECRET) is True

    def test_invalid_signature_wrong_hash(self):
        payload = b'{"entry": []}'
        bad_signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        assert verify_whatsapp_signature(payload, bad_signature, APP_SECRET) is False

    def test_invalid_signature_tampered_payload(self):
        payload = b'{"entry": []}'
        signature = _make_signature(payload, APP_SECRET)
        tampered = b'{"entry": [{"id": 1}]}'
        assert verify_whatsapp_signature(tampered, signature, APP_SECRET) is False

    def test_missing_signature_header(self):
        payload = b'{"entry": []}'
        assert verify_whatsapp_signature(payload, None, APP_SECRET) is False

    def test_empty_signature_header(self):
        payload = b'{"entry": []}'
        assert verify_whatsapp_signature(payload, "", APP_SECRET) is False

    def test_empty_app_secret(self):
        payload = b'{"entry": []}'
        assert verify_whatsapp_signature(payload, "sha256=abc", "") is False

    def test_none_app_secret(self):
        payload = b'{"entry": []}'
        assert verify_whatsapp_signature(payload, "sha256=abc", None) is False

    def test_both_missing(self):
        assert verify_whatsapp_signature(b"data", None, None) is False

    def test_empty_payload(self):
        payload = b""
        signature = _make_signature(payload, APP_SECRET)
        assert verify_whatsapp_signature(payload, signature, APP_SECRET) is True

    def test_signature_without_prefix(self):
        payload = b'{"key": "value"}'
        raw_hex = hmac.new(APP_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        assert verify_whatsapp_signature(payload, raw_hex, APP_SECRET) is False

    def test_wrong_secret(self):
        payload = b'{"entry": []}'
        signature = _make_signature(payload, APP_SECRET)
        assert verify_whatsapp_signature(payload, signature, "wrong_secret") is False

    def test_large_payload(self):
        payload = b"x" * 100_000
        signature = _make_signature(payload, APP_SECRET)
        assert verify_whatsapp_signature(payload, signature, APP_SECRET) is True

    def test_unicode_payload(self):
        payload = '{"name": "caf\u00e9"}'.encode("utf-8")
        signature = _make_signature(payload, APP_SECRET)
        assert verify_whatsapp_signature(payload, signature, APP_SECRET) is True
