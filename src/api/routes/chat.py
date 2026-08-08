import math
import re
import time
from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db, get_redis
from src.auth.dependencies import get_current_user, get_optional_current_user
from src.domain.models import ChatInteraction
from src.workers.nlu_router import (
    execute_intent_searches,
    detect_product_category,
    RegexNLURouter,
)
from src.workers.search_pipeline import SearchPipeline
from src.services.llm_nlu import SearchIntent
from src.services.categories import family_for_category
from src.services.detector import ObjectDetector
from src.services.lisa_agent import LisaAgent
from src.services.result_code_service import ResultCodeService
from src.services.chat_log_service import ChatLogService
from src.services.object_storage import upload_image
from src.shared.correlation import get_correlation_id
from src.shared.reqlog import (
    file_meta,
    log_chat_input,
    log_chat_output,
    log_chat_turn,
)
from src.api.routes.search import _load_products, _format_results, _record_search

router = APIRouter(prefix="/api/chat", tags=["chat"])
_result_code_service = ResultCodeService()
_chat_log = ChatLogService()
_regex_nlu = RegexNLURouter()
_lisa = LisaAgent()

_GREETING_TEXT = (
    "Hello! I'm Lisa 👋 Welcome to whatAppSeller.\n\n"
    "Tell me what you're looking for, or upload a photo, "
    "and I'll find matching products from local sellers!"
)

_RECALL_CODE_RE = re.compile(r"^\s*RS-[A-Z0-9]+\s*$", re.IGNORECASE)
_RECALL_TEXT_RE = re.compile(
    r"\b(last|previous|before|earlier|old|saved)\b.*\b(search|result|code)\b"
    r"|\b(search|result|code)\b.*\b(last|previous|before|earlier|old|saved)\b",
    re.IGNORECASE,
)

_detector = ObjectDetector()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)


def _build_response_text(sections: list[dict], has_location: bool) -> str:
    total = sum(s["total"] for s in sections)
    labels = [s["label"] for s in sections]
    if not labels:
        return ""

    top_label = labels[0]
    top_total = sections[0]["total"]

    if has_location and sections[0]["results"]:
        closest = min(
            (
                r for r in sections[0]["results"]
                if r.get("distance_km") is not None
            ),
            key=lambda r: r["distance_km"],
            default=None,
        )
        if closest:
            name = closest["name"]
            dist = closest["distance_km"]
            merchant = closest.get("merchant", {}) or {}
            shop = merchant.get("business_name", "a seller")
            return (
                f"I found {total} items matching what you're looking for! "
                f"The closest is **{name}** at {shop}, just {dist}km from you. "
                f"Here are the best matches:"
            )

    all_names = [s["results"][0]["name"] for s in sections if s["results"]]
    if all_names:
        return (
            f"I found {total} matching products for you! "
            f"Top picks: {', '.join(all_names[:3])}. "
            f"Check them out below:"
        )

    return f"I found {total} matching products for you. Here they are:"


def _build_follow_up(
    text_topic: str | None,
    text_family: str | None,
    image_family: str | None,
) -> dict | None:
    """The customer-relations officer: if the caption asks for something different
    from what the photo shows, never drop the request — ask for the missing detail."""
    if not text_family or not image_family or text_family == image_family:
        return None
    topic = text_topic or text_family
    return {
        "type": "clarify",
        "topic": topic,
        "image_family": image_family,
        "prompt": (
            f"You also mentioned you're looking for *{topic}* — I don't want you to miss out! "
            f"Please upload a photo of the {topic} you want, or describe its type, brand, colour "
            f"and budget (e.g. \"white Nike running shoes under 200k\") and I'll find the right match for you."
        ),
    }


NOISY_LABELS = {"person", "full_image", "object", "tie", "clock", "vase", "umbrella", "baseball glove", "skateboard", "sports ball", "frisbee"}


async def _describe_image(image_bytes: bytes) -> str:
    try:
        crops = await _detector.detect_and_crop(image_bytes)
    except Exception:
        crops = None
    if crops:
        labels = [c.label for c in crops if c.label and c.label.lower() not in NOISY_LABELS]
        confs = [c.confidence for c in crops if c.label and c.label.lower() not in NOISY_LABELS]
        best_conf = max(confs) if confs else 0
        if best_conf >= 0.60 and labels:
            return "I see " + ", ".join(labels[:3]) + " in your image"
    return "Products matching your image"


async def _handle_recall(code: str, db: AsyncSession, user) -> dict:
    lookup = await _result_code_service.lookup(db, code)
    if not lookup:
        return {
            "reply_type": "text",
            "text": f"I couldn't find any results for code *{code.upper()}*. Double-check the code and try again."
        }
    return {
        "reply_type": "recall",
        "result_code": lookup["code"],
        "search_query": lookup["search_query"],
        "image_description": lookup["image_description"],
        "category": lookup["category"],
        "price_min": lookup["price_min"],
        "price_max": lookup["price_max"],
        "product_count": lookup["product_count"],
        "sample_products": lookup["sample_products"],
        "text": (
            f"Here's what you were looking for earlier! "
            f"{'You searched for: ' + lookup['search_query'] if lookup['search_query'] else ''}"
            f"{'You shared an image of: ' + lookup['image_description'] if lookup['image_description'] else ''}"
            f"{' in category: ' + lookup['category'] if lookup['category'] else ''}"
            f". We found {lookup['product_count']} matching products."
        ),
    }


async def _handle_recall_from_text(db: AsyncSession, user) -> dict:
    codes = await _result_code_service.get_by_user(db, user.id, limit=1)
    if not codes:
        return {
            "reply_type": "text",
            "text": "You don't have any recent searches saved. Try searching for something first!"
        }
    code = codes[0]
    return await _handle_recall(code.code, db, user)


async def _log_and_return(
    db: AsyncSession,
    user,
    meta: dict,
    reply: dict,
    start: float,
) -> dict:
    thread_messages = _build_thread_messages(meta, reply)
    meta["thread_messages"] = thread_messages
    try:
        await _chat_log.log(
            db=db,
            user_id=meta["user_id"],
            phone_number=meta["phone_number"],
            correlation_id=meta["correlation_id"],
            user_message_type=meta["user_message_type"],
            user_text=meta["user_text"],
            image_count=meta["image_count"],
            image_urls=meta["image_urls"],
            image_description=meta["image_description"],
            nlu_intents=meta["intents"],
            text_topic=meta["text_topic"],
            text_family=meta["text_family"],
            image_family=meta["image_family"],
            reply=reply,
            thread_messages=thread_messages,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to log chat interaction")
    try:
        log_chat_output(reply)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to log chat output")
    return reply


def _build_top_summary(sections: list[dict]) -> list[dict]:
    summary: list[dict] = []
    for section in sections:
        for item in section.get("results", [])[:3]:
            summary.append({
                "name": item.get("name"),
                "price": item.get("price"),
                "merchant_name": (item.get("merchant") or {}).get("business_name", "a local seller"),
            })
    return summary


def _build_thread_messages(meta: dict, reply: dict) -> list[dict]:
    """Persist the same structured messages rendered by the frontend."""
    timestamp = time.strftime("%H:%M")
    messages: list[dict] = []
    if meta.get("user_text") or meta.get("image_count"):
        image_urls = meta.get("image_urls") or []
        messages.append({
            "id": f"user-{meta.get('correlation_id') or time.time_ns()}",
            "sender": "user",
            "text": meta.get("user_text"),
            "imageUrl": image_urls[0] if image_urls else None,
            "imageUrls": image_urls,
            "imageCaption": meta.get("user_text") if meta.get("image_count") else None,
            "timestamp": timestamp,
            "status": "read",
        })

    server_messages = list(reply.get("messages") or [])
    follow_up = reply.get("follow_up")
    if follow_up:
        prompt = follow_up.get("prompt", "").strip()
        server_messages = [
            message for message in server_messages
            if message.get("text", "").strip() != prompt
        ]

    response_text = (reply.get("response_text") or "").strip()
    first_results_index = next(
        (index for index, message in enumerate(server_messages)
         if message.get("type") == "search_results"),
        len(server_messages),
    )
    if response_text and not any(
        message.get("text", "").strip() == response_text for message in server_messages
    ):
        server_messages.insert(first_results_index, {"type": "text", "text": response_text})

    last_results_index = max(
        (index for index, message in enumerate(server_messages)
         if message.get("type") == "search_results"),
        default=-1,
    )
    for index, message in enumerate(server_messages):
        is_results = message.get("type") == "search_results"
        messages.append({
            "id": f"assistant-{meta.get('correlation_id') or time.time_ns()}-{index}",
            "sender": "ai",
            "text": message.get("text") if not is_results else None,
            "products": [{
                "label": message.get("label", ""),
                "total": message.get("total", 0),
                "results": message.get("results", []),
            }] if is_results else None,
            "resultCode": reply.get("result_code") if index == last_results_index else None,
            "followUp": follow_up if index == last_results_index else None,
            "timestamp": timestamp,
        })

    if not server_messages:
        fallback = reply.get("text") or reply.get("response_text")
        if fallback:
            messages.append({
                "id": f"assistant-{meta.get('correlation_id') or time.time_ns()}",
                "sender": "ai",
                "text": fallback,
                "timestamp": timestamp,
            })
    return messages


@router.post("")
async def chat(
    text: str = Form(""),
    files: list[UploadFile] | None = File(None),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    user=Depends(get_optional_current_user),
    guest_id: str | None = Header(None, alias="X-Guest-ID"),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    start = time.perf_counter()
    image_bytes_list: list[bytes] = []
    image_urls: list[str] = []
    if files:
        for f in files:
            content = await f.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {f.filename} exceeds 10MB limit")
            image_bytes_list.append(content)
            try:
                image_urls.append(await upload_image(content, f.content_type or "image/jpeg"))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Failed to persist chat image")

    has_text = bool(text.strip())
    has_images = bool(image_bytes_list)
    buyer_location = (lat, lng) if lat is not None and lng is not None else None
    actor_phone = user.phone_number if user else (guest_id or "guest-anonymous")[:20]
    actor_key = user.id if user else actor_phone

    log_chat_input(
        user=user,
        message_type=(
            "both" if has_text and has_images
            else "image" if has_images
            else "text" if has_text
            else "empty"
        ),
        text=text if has_text else None,
        files=[file_meta(f.filename or f"file{i}", image_bytes_list[i]) for i, f in enumerate(files or [])],
        location=buyer_location,
    )

    if has_text and has_images:
        user_message_type = "both"
    elif has_images:
        user_message_type = "image"
    elif has_text:
        user_message_type = "text"
    else:
        user_message_type = "empty"

    meta: dict = {
        "user_id": user.id if user else None,
        "phone_number": actor_phone,
        "correlation_id": get_correlation_id() or None,
        "user_message_type": user_message_type,
        "user_text": text if has_text else None,
        "image_count": len(image_bytes_list),
        "image_urls": image_urls,
        "image_description": None,
        "intents": [],
        "text_topic": None,
        "text_family": None,
        "image_family": None,
    }

    if not has_text and not has_images:
        return await _log_and_return(db, user, meta, {"reply_type": "text", "text": _GREETING_TEXT}, start)

    # Recall by RS- code
    if has_text and _RECALL_CODE_RE.match(text) and user:
        return await _log_and_return(
            db, user, meta, await _handle_recall(text.strip(), db, user), start
        )

    image_desc = None
    if has_images:
        image_desc = await _describe_image(image_bytes_list[0])
        meta["image_description"] = image_desc

    # Lisa reads the full message + history and decides: chat or search.
    turn = await _lisa.decide(redis, actor_key, text, has_images, image_note=image_desc)
    log_chat_turn(action=turn.action, search_text=turn.search_text, reply=turn.reply)

    # A photo ALWAYS means search — never reply without searching the image.
    if turn.action != "search" and not has_images:
        reply = {"reply_type": "text", "text": turn.reply}
        await _lisa.record_turn(
            redis, actor_key, _lisa.user_turn_text(text, has_images, image_desc), turn.reply, "gathering"
        )
        return await _log_and_return(db, user, meta, reply, start)

    # ---- search path ----------------------------------------------------
    intents: list[SearchIntent] = []
    for _ in image_bytes_list:
        intents.append(SearchIntent(
            type="visual_search",
            description=image_desc or "Products matching your image",
        ))
    if has_text:
        search_text = (turn.search_text or text).strip()
        recovered = _regex_nlu.build_product_search_intent(search_text)
        if recovered:
            intents.append(recovered)
        else:
            intents.append(SearchIntent(type="product_search", description=search_text))

    search_intents = [si for si in intents if si.type in ("visual_search", "product_search")]
    meta["intents"] = list(search_intents)

    if not search_intents:
        reply = {"reply_type": "text", "text": "What would you like me to look for? Describe it or send a photo."}
        await _lisa.record_turn(
            redis, actor_key, _lisa.user_turn_text(text, has_images, image_desc), reply["text"], "gathering"
        )
        return await _log_and_return(db, user, meta, reply, start)

    results = await execute_intent_searches(
        search_intents,
        images_bytes=image_bytes_list,
        buyer_location=buyer_location,
    )

    if not any(reranked for _, reranked in results):
        reply = {"reply_type": "text", "text": "Sorry, I searched but couldn't find matching products right now. Try a different description or check back later!"}
        await _lisa.record_turn(
            redis, actor_key, _lisa.user_turn_text(text, has_images, image_desc), reply["text"], "gathering"
        )
        return await _log_and_return(db, user, meta, reply, start)

    # Multi-object exact match search: each detected object searched independently
    if has_images:
        try:
            multi_pipeline = SearchPipeline()
            for img_bytes in image_bytes_list:
                exact_matches = await multi_pipeline.search_all_objects(
                    image_bytes=img_bytes,
                    buyer_location=buyer_location,
                )
                for label, match in exact_matches:
                    results.append((f"Exact match: {label}", [match]))
        except Exception:
            pass

    # Build sections with distance info
    sections = []
    all_product_ids: list[int] = []
    all_reranked: list = []
    all_db_products: dict = {}
    for desc, reranked in results:
        if not reranked:
            continue
        product_ids = [r.product_id for r in reranked]
        all_product_ids.extend(product_ids)
        all_reranked.extend(reranked)
        db_products = await _load_products(product_ids, db)
        all_db_products.update(db_products)
        formatted = _format_results(reranked, db_products)

        if buyer_location:
            for item in formatted:
                merchant = item.get("merchant") or {}
                mlat = merchant.get("location_lat")
                mlng = merchant.get("location_lng")
                if mlat is not None and mlng is not None:
                    item["distance_km"] = _haversine_km(
                        buyer_location[0], buyer_location[1], mlat, mlng
                    )

        sections.append({
            "label": desc,
            "total": len(formatted),
            "results": formatted,
        })

        # Override label with actual category when YOLO mislabeled
        if formatted and desc.lower().startswith("i see"):
            top_cat = (formatted[0].get("category") or "").lower()
            if top_cat:
                sections[-1]["label"] = f"Matching {top_cat}"

    combined_text = f"[chat] {text}" if text else "[chat image]"
    await _record_search(redis, actor_phone, combined_text)

    # Customer-relations follow-up when caption and image disagree
    text_topic, text_family = detect_product_category(text) if has_text else (None, None)
    meta["text_topic"] = text_topic
    meta["text_family"] = text_family
    if has_images and sections and sections[0]["results"]:
        meta["image_family"] = family_for_category(
            (sections[0]["results"][0].get("category") or "").lower()
        )
    follow_up = _build_follow_up(text_topic, text_family, meta["image_family"])

    # Lisa writes the natural summary of what was found
    lisa_text = await _lisa.present_results(redis, actor_key, _build_top_summary(sections))

    # Lisa's opening message acknowledging the image
    lisa_opening = ""
    if has_images and image_desc:
        lisa_opening = await _lisa.compose_opening(image_desc, text if has_text else "")

    # Generate result code
    result_code = await _result_code_service.generate(db)
    first_section = sections[0] if sections else None
    first_intent = search_intents[0] if search_intents else None
    await _result_code_service.store(
        db=db,
        code=result_code,
        user_id=user.id if user else None,
        search_query=text if has_text else None,
        image_description=first_intent.description if first_intent and first_intent.type == "visual_search" else None,
        category=first_section["results"][0].get("category") if first_section and first_section["results"] else None,
        product_ids=all_product_ids,
        sample_products=ResultCodeService.build_sample_products(all_reranked, all_db_products),
    )

    final_text = lisa_text or (
        "Here's what I found for you! Which option should we explore, or would you like me "
        "to refine by price, style, or location?"
    )

    # Build multi-message conversation reply
    messages: list[dict] = []
    if lisa_opening:
        messages.append({"type": "text", "text": lisa_opening})
    for section in sections:
        messages.append({
            "type": "search_results",
            "label": section["label"],
            "total": section["total"],
            "results": section["results"],
        })

    reply: dict = {
        "reply_type": "conversation",
        "result_code": result_code,
        "image_urls": image_urls,
        "messages": messages,
        "response_text": final_text,
        "sections": sections,
    }
    if follow_up:
        reply["follow_up"] = follow_up
        messages.append({"type": "text", "text": follow_up["prompt"]})

    await _lisa.record_turn(
        redis, actor_key, _lisa.user_turn_text(text, has_images, image_desc), final_text, "post_results"
    )
    return await _log_and_return(db, user, meta, reply, start)


@router.get("/conversations")
async def list_conversations(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatInteraction)
        .where(ChatInteraction.phone_number == user.phone_number)
        .order_by(ChatInteraction.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    convos: dict[str, dict] = {}
    for row in rows:
        key = row.phone_number
        if key not in convos:
            convos[key] = {
                "id": key,
                "title": "Lisa",
                "avatar": "/79fd36db-6d51-44a5-af73-bc63277d2b95.jpg",
                "updated_at": str(row.created_at),
                "last_message": (row.user_text or "")[:80],
            }
    return {"conversations": list(convos.values())}


@router.get("/conversations/messages")
async def get_conversation_messages(
    user=Depends(get_optional_current_user),
    guest_id: str | None = Header(None, alias="X-Guest-ID"),
    db: AsyncSession = Depends(get_db),
):
    actor_phone = user.phone_number if user else (guest_id or "guest-anonymous")[:20]
    result = await db.execute(
        select(ChatInteraction)
        .where(ChatInteraction.phone_number == actor_phone)
        .order_by(ChatInteraction.created_at.asc())
        .limit(100)
    )
    rows = result.scalars().all()
    messages = []
    for row in rows:
        if row.thread_messages:
            messages.extend(row.thread_messages)
            continue
        if row.user_text or row.image_count:
            messages.append({
                "id": f"user-{row.id}",
                "sender": "user",
                "text": row.user_text,
                "imageUrl": (row.image_urls or [None])[0],
                "imageCaption": row.user_text if row.image_count else None,
                "timestamp": row.created_at.strftime("%H:%M"),
            })
        if row.response_text:
            messages.append({
                "id": f"assistant-{row.id}",
                "sender": "ai",
                "text": row.response_text,
                "resultCode": row.result_code,
                "timestamp": row.created_at.strftime("%H:%M"),
            })
    return {"messages": messages}
