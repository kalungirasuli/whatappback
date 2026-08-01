import math
import re
import time
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db, get_redis
from src.auth.dependencies import get_current_user
from src.workers.nlu_router import (
    extract_nlu,
    execute_intent_searches,
    detect_product_category,
    RegexNLURouter,
    NLUResult,
)
from src.services.llm_nlu import SearchIntent
from src.services.detector import ObjectDetector
from src.services.result_code_service import ResultCodeService
from src.services.chat_log_service import ChatLogService
from src.shared.correlation import get_correlation_id
from src.api.routes.search import _load_products, _format_results, _record_search

router = APIRouter(prefix="/api/chat", tags=["chat"])
_result_code_service = ResultCodeService()
_chat_log = ChatLogService()
_regex_nlu = RegexNLURouter()

_HELP_TEXT = (
    "Here's what I can do:\n\n"
    "1. Describe what you want — e.g. 'I need red shoes under 100k'\n"
    "2. Upload a photo — I'll find similar products\n"
    "3. I'll show matching products with images and prices\n\n"
    "You can also:\n"
    "- Filter by color: 'blue shirt'\n"
    "- Filter by price: 'phone under 500000'\n"
    "- Filter by category: 'electronics', 'clothing', 'shoes'"
)

_GREETING_TEXT = (
    "Hello! Welcome to whatAppseller.\n\n"
    "Tell me what you're looking for, or upload a photo, "
    "and I'll find matching products from local sellers!"
)

_GENERAL_ANSWER = (
    "I'm here to help you find products from local sellers!\n\n"
    "You can:\n"
    "- Tell me what you need — e.g. 'I want a phone under 500k'\n"
    "- Upload a photo — I'll find similar items\n"
    "- Ask me to find something nearby\n\n"
    "All our merchants accept Mobile Money (MTN, Airtel) and cash on delivery."
)

_RECALL_CODE_RE = re.compile(r"^\s*RS-[A-Z0-9]+\s*$", re.IGNORECASE)
_RECALL_TEXT_RE = re.compile(
    r"\b(last|previous|before|earlier|old|saved)\b.*\b(search|result|code)\b"
    r"|\b(search|result|code)\b.*\b(last|previous|before|earlier|old|saved)\b",
    re.IGNORECASE,
)

# Product/catalog category -> broad family used to cross-check image vs. caption.
_PRODUCT_FAMILY = {
    "cars": "vehicles",
    "automotive": "vehicles",
    "vehicles": "vehicles",
    "phone": "electronics",
    "phones": "electronics",
    "electronics": "electronics",
    "shoes": "shoes",
    "footwear": "shoes",
    "clothing": "clothing",
    "furniture": "furniture",
    "beauty": "beauty",
    "food": "food",
    "accessories": "accessories",
    "groceries": "groceries",
}

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


async def _describe_image(image_bytes: bytes) -> str:
    try:
        crops = await _detector.detect_and_crop(image_bytes)
    except Exception:
        crops = None
    if crops:
        labels = list(dict.fromkeys(c.label for c in crops if c.label))
        if labels:
            return "I see a " + ", ".join(labels) + " in your image"
    return "I can see an item in your image"


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
    try:
        await _chat_log.log(
            db=db,
            user_id=meta["user_id"],
            phone_number=meta["phone_number"],
            correlation_id=meta["correlation_id"],
            user_message_type=meta["user_message_type"],
            user_text=meta["user_text"],
            image_count=meta["image_count"],
            image_description=meta["image_description"],
            nlu_intents=meta["intents"],
            text_topic=meta["text_topic"],
            text_family=meta["text_family"],
            image_family=meta["image_family"],
            reply=reply,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to log chat interaction")
    return reply


@router.post("")
async def chat(
    text: str = Form(""),
    files: list[UploadFile] | None = File(None),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    start = time.perf_counter()
    image_bytes_list: list[bytes] = []
    if files:
        for f in files:
            content = await f.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {f.filename} exceeds 10MB limit")
            image_bytes_list.append(content)

    has_text = bool(text.strip())
    has_images = bool(image_bytes_list)
    buyer_location = (lat, lng) if lat is not None and lng is not None else None

    if has_text and has_images:
        user_message_type = "both"
    elif has_images:
        user_message_type = "image"
    elif has_text:
        user_message_type = "text"
    else:
        user_message_type = "empty"

    meta: dict = {
        "user_id": user.id,
        "phone_number": user.phone_number,
        "correlation_id": get_correlation_id() or None,
        "user_message_type": user_message_type,
        "user_text": text if has_text else None,
        "image_count": len(image_bytes_list),
        "image_description": None,
        "intents": [],
        "text_topic": None,
        "text_family": None,
        "image_family": None,
    }

    if not has_text and not has_images:
        return await _log_and_return(db, user, meta, {"reply_type": "text", "text": _GREETING_TEXT}, start)

    # Recall by RS- code
    if has_text and _RECALL_CODE_RE.match(text):
        return await _log_and_return(
            db, user, meta, await _handle_recall(text.strip(), db, user), start
        )

    # Run NLU on text
    nlu_result = await extract_nlu(text, has_image=has_images) if has_text else NLUResult()
    search_intents_from_nlu = nlu_result.search_intents or []
    meta["intents"] = list(search_intents_from_nlu)

    # Handle non-search intents
    has_recall = bool(_RECALL_TEXT_RE.search(text)) if has_text else False
    has_greeting = any(si.type == "greeting" for si in search_intents_from_nlu)
    has_help = any(si.type == "help" for si in search_intents_from_nlu)
    has_general = any(si.type == "general_question" for si in search_intents_from_nlu)
    has_text_search = any(si.type == "product_search" for si in search_intents_from_nlu)

    if has_recall and not has_text_search and not has_images:
        return await _log_and_return(
            db, user, meta, await _handle_recall_from_text(db, user), start
        )

    if has_help:
        return await _log_and_return(db, user, meta, {"reply_type": "text", "text": _HELP_TEXT}, start)

    if has_general and not has_text_search and not has_images:
        return await _log_and_return(db, user, meta, {"reply_type": "text", "text": _GENERAL_ANSWER}, start)

    if has_greeting and not has_text_search and not has_images:
        return await _log_and_return(db, user, meta, {"reply_type": "text", "text": _GREETING_TEXT}, start)

    # Build search intents
    intents: list[SearchIntent] = []
    image_descriptions: list[str] = []
    for i in range(len(image_bytes_list)):
        img_desc = await _describe_image(image_bytes_list[i])
        image_descriptions.append(img_desc)
        intents.append(SearchIntent(type="visual_search", description=img_desc))
    if image_descriptions:
        meta["image_description"] = ", ".join(image_descriptions)

    for si in search_intents_from_nlu:
        if si.type in ("product_search", "general_question", "chat", "unknown", "Product Search Intent", "Visual Search Intent", "General Question"):
            intents.append(si)

    # Customer-relations guard: if an image is present and the NLU dropped the
    # caption's product request, recover it so the customer's request is never lost.
    if has_images and has_text and not any(si.type == "product_search" for si in intents):
        recovered = _regex_nlu.build_product_search_intent(text)
        if recovered:
            intents.append(recovered)
            meta["intents"] = meta["intents"] + [recovered]

    search_intents = [si for si in intents if si.type in ("visual_search", "product_search")]

    if not search_intents:
        return await _log_and_return(
            db,
            user,
            meta,
            {
                "reply_type": "text",
                "text": "I'm sorry, I didn't quite understand what you're looking for. Could you describe it differently?",
            },
            start,
        )

    # Execute searches with location
    results = await execute_intent_searches(
        search_intents,
        images_bytes=image_bytes_list,
        buyer_location=buyer_location,
    )

    if not any(reranked for _, reranked in results):
        return await _log_and_return(
            db,
            user,
            meta,
            {
                "reply_type": "text",
                "text": "Sorry, I searched but couldn't find matching products right now. Try a different description or check back later!",
            },
            start,
        )

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

    combined_text = f"[chat] {text}" if text else "[chat image]"
    await _record_search(redis, user.phone_number, combined_text)

    response_text = _build_response_text(sections, buyer_location is not None)

    # Customer-relations follow-up when caption and image disagree
    text_topic, text_family = detect_product_category(text) if has_text else (None, None)
    meta["text_topic"] = text_topic
    meta["text_family"] = text_family
    visual_section = next(
        (s for s in sections if s["label"].lower().startswith("i see")), None
    )
    if visual_section and visual_section["results"]:
        meta["image_family"] = _PRODUCT_FAMILY.get(
            (visual_section["results"][0].get("category") or "").lower()
        )
    follow_up = _build_follow_up(text_topic, text_family, meta["image_family"])

    # Generate result code
    result_code = await _result_code_service.generate(db)
    first_section = sections[0] if sections else None
    first_intent = search_intents[0] if search_intents else None
    await _result_code_service.store(
        db=db,
        code=result_code,
        user_id=user.id,
        search_query=text if has_text else None,
        image_description=first_intent.description if first_intent and first_intent.type == "visual_search" else None,
        category=first_section["results"][0].get("category") if first_section and first_section["results"] else None,
        product_ids=all_product_ids,
        sample_products=ResultCodeService.build_sample_products(all_reranked, all_db_products),
    )

    reply: dict = {
        "reply_type": "search_results",
        "result_code": result_code,
        "response_text": f"{response_text}\n\nShare code *{result_code}* with a merchant so they know what you're looking for!",
        "sections": sections,
    }
    if follow_up:
        reply["follow_up"] = follow_up
        reply["response_text"] += f"\n\n{follow_up['prompt']}"

    return await _log_and_return(db, user, meta, reply, start)
