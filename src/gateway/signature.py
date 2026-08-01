import hmac
import hashlib


def verify_whatsapp_signature(payload: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header or not app_secret:
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    expected_prefix = f"sha256={expected}"
    return hmac.compare_digest(expected_prefix, signature_header)
