import json

from fastapi import APIRouter, Request, HTTPException, Query, Depends
from redis.asyncio import Redis

from src.core.config import settings
from src.core.dependencies import get_redis
from src.gateway.signature import verify_whatsapp_signature
from src.gateway.dedupe import check_and_mark
from src.workers.queue import enqueue_message
from src.workers.message_buffer import MessageBuffer

router = APIRouter()

_buffer = MessageBuffer()


async def _on_flush(from_number: str, batch: list[dict]) -> None:
    images = [m["image"] for m in batch if m["type"] == "image" and m.get("image")]
    texts = [m["text"] for m in batch if m["type"] == "text" and m.get("text")]
    captions = [
        m["image"].get("caption", "")
        for m in batch
        if m["type"] == "image" and m.get("image", {}).get("caption")
    ]

    all_text_parts = [c for c in captions if c] + [t for t in texts if t]
    combined = " ".join(all_text_parts).strip()

    payload = {
        "type": "batch",
        "from": from_number,
        "images": images,
        "text": combined,
    }
    await enqueue_message(payload)


_buffer.set_on_flush(_on_flush)


def _reset_buffer_for_testing(**kwargs):
    """Only used in tests — not for production use."""
    global _buffer
    _buffer = MessageBuffer(**kwargs)
    _buffer.set_on_flush(_on_flush)


@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_webhook_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook/whatsapp")
async def handle_webhook(request: Request, redis: Redis = Depends(get_redis)):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_whatsapp_signature(body, signature, settings.whatsapp_app_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = json.loads(body)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                message_id = msg.get("id")
                if not message_id:
                    continue
                if await check_and_mark(redis, message_id):
                    continue

                msg_type = msg.get("type")
                if msg_type == "text":
                    text_body = msg.get("text", {}).get("body", "").strip()
                    if not text_body:
                        continue

                    has_pending = await _buffer.has_pending_for(msg["from"])
                    if not has_pending:
                        # Solo text — enqueue directly (preserves original format)
                        await enqueue_message({
                            "message_id": message_id,
                            "from": msg.get("from"),
                            "type": "text",
                            "text": msg.get("text", {}),
                        })
                    else:
                        # Text after images — flush batch immediately
                        await _buffer.add(
                            msg["from"],
                            {"type": "text", "text": text_body},
                        )
                        await _buffer.flush_sender(msg["from"])

                elif msg_type == "image":
                    await _buffer.add(
                        msg["from"],
                        {"type": "image", "image": msg.get("image", {})},
                    )

    return {"status": "ok"}
