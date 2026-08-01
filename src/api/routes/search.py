from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.dependencies import get_db, get_redis
from src.domain.models import Product
from src.auth.dependencies import require_client
from src.workers.search_pipeline import SearchPipeline
from src.workers.nlu_router import extract_nlu, execute_intent_searches, _build_search_text, _price_range_from_entities
from src.services.llm_nlu import SearchIntent
from src.services.qdrant_service import QdrantService

router = APIRouter(prefix="/api/search", tags=["search"])

search_pipeline = SearchPipeline()
qdrant_service = QdrantService()

SEARCH_HISTORY_PREFIX = "search_history:"


def _format_results(reranked_results, db_products: dict[int, Product]) -> list[dict]:
    items = []
    for r in reranked_results:
        product = db_products.get(r.product_id)
        images = []
        merchant = None

        if product:
            merchant = product.merchant
            images = [
                {"url": img.storage_url, "is_primary": img.is_primary}
                for img in product.images
            ]

        items.append({
            "product_id": r.product_id,
            "name": product.name if product else f"Product #{r.product_id}",
            "price": product.price if product else 0,
            "currency": product.currency if product else "UGX",
            "category": product.category if product else "",
            "merchant": {
                "id": merchant.id,
                "business_name": merchant.business_name,
                "phone_number": merchant.phone_number,
                "category": merchant.category,
                "location_lat": merchant.location_lat,
                "location_lng": merchant.location_lng,
            } if merchant else None,
            "score": round(r.score, 4),
            "match_label": r.match_label,
            "images": images,
        })

    return items


async def _load_products(product_ids: list[int], db: AsyncSession) -> dict[int, Product]:
    if not product_ids:
        return {}
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.images),
            selectinload(Product.merchant),
        )
        .where(Product.id.in_(product_ids))
    )
    return {p.id: p for p in result.scalars().all()}


async def _record_search(redis, phone: str, query_text: str) -> None:
    import json
    import time

    key = f"{SEARCH_HISTORY_PREFIX}{phone}"
    entry = json.dumps({"query": query_text, "ts": int(time.time())})
    await redis.lpush(key, entry)
    await redis.ltrim(key, 0, 19)
    await redis.expire(key, 86400)


@router.post("/image")
async def search_by_image(
    file: UploadFile = File(...),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    price_min: float | None = Query(None),
    price_max: float | None = Query(None),
    user=Depends(require_client),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    buyer_location = (lat, lng) if lat is not None and lng is not None else None
    price_range = (price_min, price_max) if price_min is not None and price_max is not None else None

    reranked = await search_pipeline.search_by_image(
        image_bytes=content,
        buyer_location=buyer_location,
        price_range=price_range,
    )

    product_ids = [r.product_id for r in reranked]
    db_products = await _load_products(product_ids, db)
    results = _format_results(reranked, db_products)

    await _record_search(redis, user.phone_number, "[image search]")

    return {"results": results, "total": len(results)}


@router.post("/text")
async def search_by_text(
    query: str,
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    price_min: float | None = Query(None),
    price_max: float | None = Query(None),
    user=Depends(require_client),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query text is required")

    buyer_location = (lat, lng) if lat is not None and lng is not None else None
    price_range = (price_min, price_max) if price_min is not None and price_max is not None else None

    reranked = await search_pipeline.search_by_text(
        text=query,
        buyer_location=buyer_location,
        price_range=price_range,
    )

    product_ids = [r.product_id for r in reranked]
    db_products = await _load_products(product_ids, db)
    results = _format_results(reranked, db_products)

    await _record_search(redis, user.phone_number, query)

    return {"results": results, "total": len(results)}


@router.post("/describe")
async def search_by_description(
    description: str = Form(""),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    price_min: float | None = Query(None),
    price_max: float | None = Query(None),
    user=Depends(require_client),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    if not description or not description.strip():
        raise HTTPException(status_code=400, detail="Description is required")

    buyer_location = (lat, lng) if lat is not None and lng is not None else None
    price_range = (price_min, price_max) if price_min is not None and price_max is not None else None

    # Run NLU to extract intents and entities
    nlu_result = await extract_nlu(description, has_image=False)

    # Find product_search intent
    product_intents = [si for si in nlu_result.search_intents if si.type == "product_search"]

    if product_intents:
        intent = product_intents[0]
        search_text = _build_search_text(intent.entities, description)
        if price_range is None:
            price_range = _price_range_from_entities(intent.entities)
    else:
        search_text = description

    reranked = await search_pipeline.search_by_text(
        text=search_text,
        buyer_location=buyer_location,
        price_range=price_range,
    )

    product_ids = [r.product_id for r in reranked]
    db_products = await _load_products(product_ids, db)
    results = _format_results(reranked, db_products)

    await _record_search(redis, user.phone_number, description)

    return {"query": description, "results": results, "total": len(results)}


@router.get("/nearby")
async def search_nearby(
    lat: float = Query(...),
    lng: float = Query(...),
    km: float = Query(10.0),
    user=Depends(require_client),
    db: AsyncSession = Depends(get_db),
):
    from src.services.postgres_service import get_nearby_products

    raw_results = await get_nearby_products(lat, lng, km, limit=20)

    results = []
    for row in raw_results:
        product_id = row.get("product_id")
        product_result = await db.execute(
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id == product_id)
        )
        product = product_result.scalar_one_or_none()

        results.append({
            "product_id": product_id,
            "name": row.get("product_name", ""),
            "price": row.get("price", 0),
            "currency": row.get("currency", "UGX"),
            "category": row.get("category", ""),
            "merchant_name": row.get("business_name", ""),
            "distance_km": row.get("distance_km"),
            "score": 1.0,
            "match_label": "Nearby",
            "images": [
                {"url": img.storage_url, "is_primary": img.is_primary}
                for img in (product.images if product else [])
            ],
        })

    return {"results": results, "total": len(results)}


@router.post("/batch")
async def search_batch(
    files: list[UploadFile] | None = File(None),
    query: str = Form(""),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    price_min: float | None = Query(None),
    price_max: float | None = Query(None),
    user=Depends(require_client),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    image_bytes_list: list[bytes] = []
    if files:
        for f in files:
            content = await f.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {f.filename} exceeds 10MB limit")
            image_bytes_list.append(content)

    if not image_bytes_list and not query.strip():
        raise HTTPException(status_code=400, detail="At least one image or a text query is required")

    buyer_location = (lat, lng) if lat is not None and lng is not None else None
    price_range = (price_min, price_max) if price_min is not None and price_max is not None else None

    intents: list[SearchIntent] = []
    for i in range(len(image_bytes_list)):
        caption = files[i].filename or f"Image {i + 1}"
        intents.append(SearchIntent(type="visual_search", description=caption))

    if query and query.strip():
        nlu_result = await extract_nlu(query, has_image=False)
        for si in nlu_result.search_intents:
            if si.type in ("product_search", "general_question", "chat"):
                intents.append(si)

    search_intents = [si for si in intents if si.type in ("visual_search", "product_search")]
    if not search_intents:
        raise HTTPException(status_code=400, detail="No searchable intent found")

    results = await execute_intent_searches(
        search_intents,
        images_bytes=image_bytes_list,
    )

    sections = []
    for desc, reranked in results:
        product_ids = [r.product_id for r in reranked]
        db_products = await _load_products(product_ids, db)
        formatted = _format_results(reranked, db_products)
        sections.append({
            "label": desc,
            "total": len(formatted),
            "results": formatted,
        })

    combined_text = f"[batch] {query}" if query else "[batch]"
    await _record_search(redis, user.phone_number, combined_text)

    return {"sections": sections}
