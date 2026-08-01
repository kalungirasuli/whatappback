import httpx

from src.core.config import settings

WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0"
WHATSAPP_MEDIA_BASE = "https://graph.facebook.com/v21.0"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }


async def send_text(to: str, text: str) -> dict | None:
    if not settings.whatsapp_access_token:
        return None

    url = f"{WHATSAPP_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()


async def send_interactive(
    to: str,
    body_text: str,
    buttons: list[dict],
) -> dict | None:
    if not settings.whatsapp_access_token:
        return None

    url = f"{WHATSAPP_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": buttons},
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()


async def send_template(
    to: str,
    template_name: str,
    language_code: str = "en",
    components: list[dict] | None = None,
) -> dict | None:
    if not settings.whatsapp_access_token:
        return None

    url = f"{WHATSAPP_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()


async def download_media(media_id: str) -> bytes | None:
    if not settings.whatsapp_access_token:
        return b"fake_image_data_for_testing"

    url = f"{WHATSAPP_MEDIA_BASE}/{media_id}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers())
        if resp.status_code != 200:
            return None
        data = resp.json()
        download_url = data.get("url")
        if not download_url:
            return None
        img_resp = await client.get(download_url, headers=_headers())
        if img_resp.status_code != 200:
            return None
        return img_resp.content
