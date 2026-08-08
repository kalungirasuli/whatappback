"""Merchant-facing business intelligence endpoints.

The first version intentionally computes metrics from the existing event tables
so the dashboard reflects real searches and interests without inventing sales.
"""

import datetime
import json
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.dependencies import get_current_user
from src.core.config import settings
from src.core.dependencies import get_db
from src.domain.enums import SubscriptionStatus
from src.domain.models import (
    ChatInteraction,
    InterestEvent,
    Merchant,
    MerchantSubscription,
    Product,
    SubscriptionPlan,
    User,
)

router = APIRouter(prefix="/api/merchants/me/analytics", tags=["merchant-analytics"])


async def _merchant_for_user(user: User, db: AsyncSession, merchant_id: int | None = None) -> Merchant:
    if merchant_id is not None:
        result = await db.execute(
            select(Merchant).where(
                Merchant.id == merchant_id,
                Merchant.phone_number == user.phone_number,
            )
        )
    else:
        result = await db.execute(
            select(Merchant)
            .where(Merchant.phone_number == user.phone_number)
            .order_by(Merchant.created_at.desc())
        )
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")
    return merchant


async def _require_analytics(user: User, db: AsyncSession, advanced: bool = False, merchant_id: int | None = None) -> Merchant:
    merchant = await _merchant_for_user(user, db, merchant_id)
    if settings.app_mode.lower() == "free":
        return merchant

    result = await db.execute(
        select(MerchantSubscription)
        .options(selectinload(MerchantSubscription.plan))
        .where(
            MerchantSubscription.merchant_id == merchant.id,
            MerchantSubscription.status == SubscriptionStatus.active,
        )
        .order_by(MerchantSubscription.created_at.desc())
    )
    subscription = result.scalars().first()
    features: list[str] = []
    slug = ""
    if subscription and subscription.plan:
        slug = subscription.plan.slug.value
        try:
            features = json.loads(subscription.plan.features or "[]")
        except json.JSONDecodeError:
            features = []

    required = "analytics_advanced" if advanced else "analytics_basic"
    if slug == "enterprise" or required in features or (not advanced and "analytics_advanced" in features):
        return merchant
    raise HTTPException(status_code=403, detail="Upgrade your plan to access this analytics report")


async def _scope(user: User, db: AsyncSession, days: int, merchant_id: int | None = None) -> dict[str, Any]:
    merchant = await _merchant_for_user(user, db, merchant_id)
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

    product_result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.merchant_id == merchant.id)
    )
    products = list(product_result.scalars().all())
    product_map = {product.id: product for product in products}

    interest_result = await db.execute(
        select(InterestEvent)
        .where(
            InterestEvent.merchant_id == merchant.id,
            InterestEvent.created_at >= start,
        )
        .order_by(InterestEvent.created_at.desc())
    )
    interests = list(interest_result.scalars().all())

    interaction_result = await db.execute(
        select(ChatInteraction)
        .where(ChatInteraction.created_at >= start)
        .order_by(ChatInteraction.created_at.asc())
    )
    interactions = list(interaction_result.scalars().all())
    return {
        "merchant": merchant,
        "products": products,
        "product_map": product_map,
        "interests": interests,
        "interactions": interactions,
        "start": start,
        "days": days,
    }


def _result_items(row: ChatInteraction) -> list[dict]:
    return [item for item in (row.top_results or []) if isinstance(item, dict)]


def _entities(row: ChatInteraction) -> list[dict]:
    return [item for item in (row.nlu_intents or []) if isinstance(item, dict)]


def _query_attribute_counts(rows: list[ChatInteraction], category: str | None = None) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        for intent in _entities(row):
            entities = intent.get("entities") or {}
            if category:
                values = [
                    str(entities.get("category", "")).lower(),
                    str(entities.get("item_type", "")).lower(),
                ]
                if category.lower() not in values and str(row.text_family or "").lower() != category.lower():
                    continue
            attrs = entities.get("attributes") if isinstance(entities.get("attributes"), dict) else {}
            merged = {**entities, **attrs}
            for key in ("color", "brand", "gender", "size", "material", "style", "condition", "occasion"):
                value = merged.get(key)
                if isinstance(value, list):
                    for item in value:
                        counts[key][str(item).lower()] += 1
                elif value:
                    counts[key][str(value).lower()] += 1
    return {key: dict(counter.most_common(10)) for key, counter in counts.items()}


def _product_metrics(scope: dict[str, Any]) -> list[dict]:
    product_map = scope["product_map"]
    interest_counts = Counter(item.product_id for item in scope["interests"])
    impressions: dict[int, list[tuple[float, int]]] = defaultdict(list)
    search_counts: Counter = Counter()
    for row in scope["interactions"]:
        ranked = _result_items(row)
        matched = False
        for rank, item in enumerate(ranked, start=1):
            product_id = item.get("product_id")
            if product_id in product_map:
                matched = True
                try:
                    score = float(item.get("score") or 0)
                except (TypeError, ValueError):
                    score = 0.0
                impressions[product_id].append((score, rank))
        if matched:
            search_counts[row.id] += 1

    output = []
    for product in scope["products"]:
        rows = impressions.get(product.id, [])
        interest_count = interest_counts.get(product.id, 0)
        average_score = sum(score for score, _ in rows) / len(rows) if rows else 0.0
        average_rank = sum(rank for _, rank in rows) / len(rows) if rows else None
        impression_count = len(rows)
        output.append({
            "product_id": product.id,
            "name": product.name,
            "category": product.category,
            "brand": product.brand,
            "price": product.price,
            "currency": product.currency,
            "stock_qty": product.stock_qty,
            "image_count": len(product.images),
            "attributes": product.attributes or {},
            "impressions": impression_count,
            "interests": interest_count,
            "conversion_rate": round(100 * interest_count / impression_count, 1) if impression_count else 0.0,
            "average_score": round(average_score, 4),
            "average_rank": round(average_rank, 2) if average_rank is not None else None,
        })
    return sorted(output, key=lambda item: (item["interests"], item["impressions"]), reverse=True)


@router.get("/overview")
async def analytics_overview(
    days: int = Query(30, ge=7, le=90),
    merchant_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _scope(user, db, days, merchant_id)
    await _require_analytics(user, db, merchant_id=merchant_id)
    metrics = _product_metrics(scope)
    interest_counts = Counter(item.product_id for item in scope["interests"])
    impression_total = sum(item["impressions"] for item in metrics)
    interest_total = len(scope["interests"])
    unique_buyers = len({item.buyer_phone for item in scope["interests"]})
    timeline = {
        (scope["start"] + datetime.timedelta(days=offset)).date().isoformat(): {"interests": 0, "impressions": 0}
        for offset in range(scope["days"] + 1)
    }
    for interest in scope["interests"]:
        key = interest.created_at.date().isoformat()
        if key in timeline:
            timeline[key]["interests"] += 1
    for row in scope["interactions"]:
        key = row.created_at.date().isoformat()
        if key in timeline:
            timeline[key]["impressions"] += sum(
                1 for item in _result_items(row) if item.get("product_id") in scope["product_map"]
            )

    return {
        "mode": settings.app_mode,
        "category": scope["merchant"].category,
        "period_days": days,
        "summary": {
            "products": len(scope["products"]),
            "active_products": sum(1 for product in scope["products"] if getattr(product.status, "value", product.status) == "active"),
            "interests": interest_total,
            "unique_buyers": unique_buyers,
            "search_impressions": impression_total,
            "conversion_rate": round(100 * interest_total / impression_total, 1) if impression_total else 0.0,
            "average_match_score": round(
                sum(item["average_score"] for item in metrics if item["impressions"]) /
                max(1, sum(1 for item in metrics if item["impressions"])), 4
            ),
        },
        "timeline": [{"date": date, **values} for date, values in timeline.items()],
        "top_products": metrics[:5],
    }


@router.get("/category/{category}")
async def analytics_category(
    category: str,
    days: int = Query(30, ge=7, le=90),
    merchant_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_analytics(user, db, merchant_id=merchant_id)
    scope = await _scope(user, db, days, merchant_id)
    category = category.lower()
    all_products_result = await db.execute(select(Product).where(Product.category.ilike(category)))
    category_products = list(all_products_result.scalars().all())
    category_ids = {product.id for product in category_products}
    own_ids = set(scope["product_map"])
    demand_rows = [
        row for row in scope["interactions"]
        if any(str(intent.get("entities", {}).get("category", "")).lower() == category for intent in _entities(row))
        or str(row.text_family or "").lower() == category
    ]
    category_impressions = sum(
        1 for row in scope["interactions"]
        for item in _result_items(row)
        if item.get("product_id") in category_ids
    )
    own_impressions = sum(
        1 for row in scope["interactions"]
        for item in _result_items(row)
        if item.get("product_id") in own_ids and item.get("product_id") in category_ids
    )
    return {
        "category": category,
        "period_days": days,
        "market": {
            "products": len(category_products),
            "merchants": len({product.merchant_id for product in category_products}),
            "searches": len(demand_rows),
            "impressions": category_impressions,
            "merchant_impression_share": round(100 * own_impressions / category_impressions, 1) if category_impressions else 0.0,
        },
        "attributes": _query_attribute_counts(demand_rows, category),
        "prices": {
            "average_market_price": round(sum(product.price for product in category_products) / len(category_products), 2) if category_products else 0,
            "your_average_price": round(sum(product.price for product in scope["products"]) / len(scope["products"]), 2) if scope["products"] else 0,
        },
    }


@router.get("/products")
async def analytics_products(
    days: int = Query(30, ge=7, le=90),
    merchant_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_analytics(user, db, merchant_id=merchant_id)
    scope = await _scope(user, db, days, merchant_id)
    return {"period_days": days, "products": _product_metrics(scope)}


@router.get("/buyers")
async def analytics_buyers(
    days: int = Query(30, ge=7, le=90),
    merchant_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_analytics(user, db, advanced=True, merchant_id=merchant_id)
    scope = await _scope(user, db, days, merchant_id)
    grouped: dict[str, list[InterestEvent]] = defaultdict(list)
    for interest in scope["interests"]:
        grouped[interest.buyer_phone].append(interest)
    buyers = []
    for phone, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.created_at)
        buyers.append({
            "phone": phone,
            "interests": len(rows),
            "first_seen": ordered[0].created_at.isoformat(),
            "last_seen": ordered[-1].created_at.isoformat(),
            "products": list({item.product_id for item in rows}),
        })
    return {"period_days": days, "unique_buyers": len(buyers), "buyers": sorted(buyers, key=lambda item: item["interests"], reverse=True)}


@router.get("/recommendations")
async def analytics_recommendations(
    days: int = Query(30, ge=7, le=90),
    merchant_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_analytics(user, db, advanced=True, merchant_id=merchant_id)
    scope = await _scope(user, db, days, merchant_id)
    metrics = _product_metrics(scope)
    recommendations: list[dict] = []
    for metric in metrics:
        if metric["image_count"] == 0:
            recommendations.append({"type": "images", "priority": "high", "product_id": metric["product_id"], "message": f"Add a product image to {metric['name']} so visual searches can match it."})
        if not metric["attributes"]:
            recommendations.append({"type": "attributes", "priority": "high", "product_id": metric["product_id"], "message": f"Add searchable attributes to {metric['name']} such as color, size, material, model, or condition."})
        if metric["stock_qty"] <= 0:
            recommendations.append({"type": "stock", "priority": "high", "product_id": metric["product_id"], "message": f"{metric['name']} is out of stock and cannot convert current interest."})
        if metric["impressions"] >= 3 and metric["interests"] == 0:
            recommendations.append({"type": "conversion", "priority": "medium", "product_id": metric["product_id"], "message": f"{metric['name']} is being found but not selected; review its price, images, and attributes."})
    if not recommendations:
        recommendations.append({"type": "positive", "priority": "low", "message": "Your catalog has no immediate data-quality warnings. Keep adding complete product attributes and fresh images."})
    return {"period_days": days, "recommendations": recommendations[:20]}
