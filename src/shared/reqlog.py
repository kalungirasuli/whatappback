"""Diagnostic request/response logging for tracing the exact bytes that cross
the frontend <-> backend boundary. Used to detect data corruption in transit
(e.g. an image re-encoded between browser and API, or mangled text)."""

import hashlib
import json
import logging

logger = logging.getLogger("src.shared.reqlog")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def head_hex(data: bytes, n: int = 16) -> str:
    return data[:n].hex()


def file_meta(name: str, content: bytes) -> dict:
    return {
        "name": name,
        "size": len(content),
        "sha256": sha256_hex(content),
        "head": head_hex(content),
    }


def log_frontend_request(
    method: str,
    path: str,
    query: str,
    client: str,
    content_type: str,
    content_length: str,
    status: int,
    duration_ms: int,
) -> None:
    logger.info(
        "[REQ] %s %s%s ct=%s len=%s client=%s -> %d (%dms)",
        method, path, query, content_type, content_length, client, status, duration_ms,
    )


def log_chat_input(
    *,
    user,
    message_type: str,
    text: str | None,
    files: list[dict],
    location: tuple | None,
) -> None:
    details = {
        "user_id": getattr(user, "id", None),
        "phone": getattr(user, "phone_number", None),
        "message_type": message_type,
        "text": text,
        "files": files,
        "location": location,
    }
    logger.info("[CHAT-IN] %s", json.dumps(details, ensure_ascii=False, default=str))


def log_chat_turn(*, action: str, search_text: str = "", reply: str = "") -> None:
    logger.info(
        "[LISA] action=%s search_text=%r reply=%r",
        action, search_text, reply,
    )


def log_chat_output(reply: dict) -> None:
    logger.info(
        "[CHAT-OUT] %s",
        json.dumps(reply, ensure_ascii=False, default=str)[:4000],
    )
