"""System-wide admin endpoints on the main API.

Gated behind the app-level admin role (``users.role == 'admin'``) so the
React admin pages can drive the whole system from one API surface: users,
merchants, products, chat interactions, interest events and analytics.
"""

import datetime
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.dependencies import require_admin
from src.core.dependencies import get_db
from src.domain.enums import MerchantStatus, ProductStatus, UserRole
from src.domain.models import (
    Buyer,
    ChatInteraction,
    ConversationLog,
    InterestEvent,
    Merchant,
    Product,
    User,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _page_result(db: AsyncSession, model, filters, page: int, size: int):
    base = select(func.count()).select_from(model)
    if filters is not None:
        base = base.where(*filters)
    total = (await db.execute(base)).scalar() or 0
    return total


def _paging(page: int, size: int) -> tuple[int, int]:
    page = max(1, page)
    size = min(max(1, size), 100)
    return page, size


@router.get("/overview")
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Single payload for the admin dashboard home screen."""

    user_total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    admin_users = (await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.admin)
    )).scalar() or 0
    banned_users = (await db.execute(
        select(func.count(User.id)).where(User.is_banned == True)
    )).scalar() or 0

    merchant_total = (await db.execute(select(func.count(Merchant.id)))).scalar() or 0
    merchant_by_status = dict((await db.execute(
        select(Merchant.status, func.count(Merchant.id)).group_by(Merchant.status)
    )).all())

    product_total = (await db.execute(select(func.count(Product.id)))).scalar() or 0
    product_by_status = dict((await db.execute(
        select(Product.status, func.count(Product.id)).group_by(Product.status)
    )).all())

    buyer_total = (await db.execute(select(func.count(Buyer.id)))).scalar() or 0
    banned_buyers = (await db.execute(
        select(func.count(Buyer.id)).where(Buyer.is_banned == True)
    )).scalar() or 0

    interest_total = (await db.execute(select(func.count(InterestEvent.id)))).scalar() or 0
    interest_by_status = dict((await db.execute(
        select(InterestEvent.status, func.count(InterestEvent.id)).group_by(InterestEvent.status)
    )).all())

    interaction_total = (await db.execute(select(func.count(ChatInteraction.id)))).scalar() or 0
    message_total = (await db.execute(select(func.count(ConversationLog.id)))).scalar() or 0

    recent_users = (await db.execute(
        select(User).order_by(User.created_at.desc()).limit(6)
    )).scalars().all()

    recent_merchants = (await db.execute(
        select(Merchant).order_by(Merchant.created_at.desc()).limit(6)
    )).scalars().all()

    recent_interactions = (await db.execute(
        select(ChatInteraction).order_by(ChatInteraction.created_at.desc()).limit(8)
    )).scalars().all()

    recent_interests = (await db.execute(
        select(InterestEvent)
        .options(selectinload(InterestEvent.product))
        .order_by(InterestEvent.created_at.desc())
        .limit(8)
    )).scalars().all()

    return {
        "users": {
            "total": user_total,
            "admins": admin_users,
            "banned": banned_users,
        },
        "merchants": {
            "total": merchant_total,
            "approved": merchant_by_status.get(MerchantStatus.approved, 0),
            "suspended": merchant_by_status.get(MerchantStatus.suspended, 0),
            "banned": merchant_by_status.get(MerchantStatus.banned, 0),
        },
        "products": {
            "total": product_total,
            "active": product_by_status.get(ProductStatus.active, 0),
            "inactive": product_by_status.get(ProductStatus.inactive, 0),
            "pending_moderation": product_by_status.get(ProductStatus.pending_moderation, 0),
        },
        "buyers": {"total": buyer_total, "banned": banned_buyers},
        "interests": {
            "total": interest_total,
            "sent": interest_by_status.get("sent", 0),
            "responded": interest_by_status.get("responded", 0),
        },
        "messages": {"total": message_total},
        "interactions": {"total": interaction_total},
        "recent_users": [
            {
                "id": u.id,
                "phone": u.phone_number,
                "name": u.name,
                "role": u.role.value,
                "is_banned": u.is_banned,
                "created_at": u.created_at.isoformat(),
            }
            for u in recent_users
        ],
        "recent_merchants": [
            {
                "id": m.id,
                "business_name": m.business_name,
                "phone_number": m.phone_number,
                "category": m.category,
                "status": m.status.value,
                "created_at": m.created_at.isoformat(),
            }
            for m in recent_merchants
        ],
        "recent_interactions": [
            {
                "id": i.id,
                "phone_number": i.phone_number,
                "user_message_type": i.user_message_type,
                "user_text": i.user_text,
                "reply_type": i.reply_type,
                "response_text": i.response_text,
                "latency_ms": i.latency_ms,
                "created_at": i.created_at.isoformat(),
            }
            for i in recent_interactions
        ],
        "recent_interests": [
            {
                "id": ie.id,
                "buyer_phone": ie.buyer_phone,
                "status": ie.status.value,
                "result_code": ie.result_code,
                "product_name": ie.product.name if ie.product else None,
                "created_at": ie.created_at.isoformat(),
            }
            for ie in recent_interests
        ],
    }


# ---- Users ----


@router.get("/users")
async def list_users(
    role: str | None = None,
    is_banned: bool | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    page, size = _paging(page, size)
    filters = []
    if role:
        try:
            filters.append(User.role == UserRole(role))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown role '{role}'")
    if is_banned is not None:
        filters.append(User.is_banned == is_banned)
    if q:
        like = f"%{q}%"
        filters.append(or_(User.phone_number.ilike(like), User.name.ilike(like), User.email.ilike(like)))

    total = await _page_result(db, User, filters, page, size)
    result = await db.execute(
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    users = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "users": [
            {
                "id": u.id,
                "phone": u.phone_number,
                "name": u.name,
                "email": u.email,
                "role": u.role.value,
                "is_verified": u.is_verified,
                "is_banned": u.is_banned,
                "created_at": u.created_at.isoformat(),
                "last_active_at": u.last_active_at.isoformat(),
            }
            for u in users
        ],
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    interests = (await db.execute(
        select(func.count(InterestEvent.id)).where(InterestEvent.buyer_phone == user.phone_number)
    )).scalar() or 0
    interactions = (await db.execute(
        select(func.count(ChatInteraction.id)).where(ChatInteraction.phone_number == user.phone_number)
    )).scalar() or 0
    merchants = (await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )).scalars().all()

    return {
        "id": user.id,
        "phone": user.phone_number,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "is_verified": user.is_verified,
        "is_banned": user.is_banned,
        "created_at": user.created_at.isoformat(),
        "last_active_at": user.last_active_at.isoformat(),
        "interests_count": interests,
        "interactions_count": interactions,
        "merchants": [
            {
                "id": m.id,
                "business_name": m.business_name,
                "category": m.category,
                "status": m.status.value,
            }
            for m in merchants
        ],
    }


@router.post("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    role: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        role_enum = UserRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown role '{role}'")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == role_enum:
        return {"message": f"User already has role '{role}'", "role": role}
    user.role = role_enum
    await db.commit()
    return {"message": f"User '{user.phone_number}' is now a '{role}'", "role": role}


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    reason: str = "Moderation action",
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = True
    await db.commit()
    return {"message": f"User '{user.phone_number}' banned", "is_banned": True, "reason": reason}


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = False
    await db.commit()
    return {"message": f"User '{user.phone_number}' unbanned", "is_banned": False}


# ---- Merchants ----


@router.get("/merchants")
async def list_merchants(
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    page, size = _paging(page, size)
    filters = []
    if status:
        try:
            filters.append(Merchant.status == MerchantStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status '{status}'")
    if category:
        filters.append(Merchant.category.ilike(f"%{category}%"))
    if q:
        like = f"%{q}%"
        filters.append(or_(Merchant.business_name.ilike(like), Merchant.phone_number.ilike(like)))

    total = await _page_result(db, Merchant, filters, page, size)

    product_counts = dict((await db.execute(
        select(Product.merchant_id, func.count(Product.id)).group_by(Product.merchant_id)
    )).all())
    interest_counts = dict((await db.execute(
        select(InterestEvent.merchant_id, func.count(InterestEvent.id)).group_by(InterestEvent.merchant_id)
    )).all())

    result = await db.execute(
        select(Merchant)
        .where(*filters)
        .order_by(Merchant.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    merchants = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "merchants": [
            {
                "id": m.id,
                "phone_number": m.phone_number,
                "business_name": m.business_name,
                "category": m.category,
                "status": m.status.value,
                "created_at": m.created_at.isoformat(),
                "product_count": product_counts.get(m.id, 0),
                "interest_count": interest_counts.get(m.id, 0),
            }
            for m in merchants
        ],
    }


@router.get("/merchants/{merchant_id}")
async def get_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")

    products = (await db.execute(
        select(Product).where(Product.merchant_id == merchant_id).order_by(Product.created_at.desc())
    )).scalars().all()
    interests = (await db.execute(
        select(InterestEvent).where(InterestEvent.merchant_id == merchant_id).order_by(InterestEvent.created_at.desc())
    )).scalars().all()

    return {
        "id": m.id,
        "phone_number": m.phone_number,
        "business_name": m.business_name,
        "category": m.category,
        "location_lat": m.location_lat,
        "location_lng": m.location_lng,
        "status": m.status.value,
        "created_at": m.created_at.isoformat(),
        "product_count": len(products),
        "interest_count": len(interests),
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "price": p.price,
                "currency": p.currency,
                "stock_qty": p.stock_qty,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in products
        ],
        "interests": [
            {
                "id": ie.id,
                "buyer_phone": ie.buyer_phone,
                "product_id": ie.product_id,
                "result_code": ie.result_code,
                "status": ie.status.value,
                "created_at": ie.created_at.isoformat(),
            }
            for ie in interests
        ],
    }


@router.post("/merchants/{merchant_id}/suspend")
async def suspend_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.suspended
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' suspended", "status": m.status.value}


@router.post("/merchants/{merchant_id}/reactivate")
async def reactivate_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.approved
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' reactivated", "status": m.status.value}


@router.post("/merchants/{merchant_id}/ban")
async def ban_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.banned
    await db.execute(
        update(Product)
        .where(Product.merchant_id == merchant_id, Product.status == ProductStatus.active)
        .values(status=ProductStatus.inactive)
    )
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' banned, all products deactivated", "status": m.status.value}


# ---- Products / listings ----


@router.get("/products")
async def list_products(
    status: str | None = None,
    merchant_id: int | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    page, size = _paging(page, size)
    filters = []
    if status:
        try:
            filters.append(Product.status == ProductStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status '{status}'")
    if merchant_id:
        filters.append(Product.merchant_id == merchant_id)
    if category:
        filters.append(Product.category.ilike(f"%{category}%"))
    if q:
        like = f"%{q}%"
        filters.append(or_(Product.name.ilike(like), Product.brand.ilike(like)))

    total = await _page_result(db, Product, filters, page, size)
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.merchant))
        .where(*filters)
        .order_by(Product.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    products = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "products": [
            {
                "id": p.id,
                "merchant_id": p.merchant_id,
                "merchant_name": p.merchant.business_name if p.merchant else None,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "price": p.price,
                "currency": p.currency,
                "stock_qty": p.stock_qty,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in products
        ],
    }


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.merchant), selectinload(Product.images))
        .where(Product.id == product_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    interest_count = (await db.execute(
        select(func.count(InterestEvent.id)).where(InterestEvent.product_id == product_id)
    )).scalar() or 0
    return {
        "id": p.id,
        "merchant_id": p.merchant_id,
        "merchant_name": p.merchant.business_name if p.merchant else None,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "attributes": p.attributes or {},
        "price": p.price,
        "currency": p.currency,
        "stock_qty": p.stock_qty,
        "status": p.status.value,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
        "interest_count": interest_count,
        "images": [
            {"id": img.id, "storage_url": img.storage_url, "is_primary": img.is_primary}
            for img in p.images
        ],
    }


@router.post("/products/{product_id}/deactivate")
async def deactivate_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    p.status = ProductStatus.inactive
    await db.commit()
    return {"message": f"Product '{p.name}' deactivated", "status": p.status.value}


@router.post("/products/{product_id}/reactivate")
async def reactivate_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    p.status = ProductStatus.active
    await db.commit()
    return {"message": f"Product '{p.name}' reactivated", "status": p.status.value}


# ---- Chat interactions ----


def _interaction_row(i: ChatInteraction) -> dict:
    return {
        "id": i.id,
        "user_id": i.user_id,
        "phone_number": i.phone_number,
        "correlation_id": i.correlation_id,
        "user_message_type": i.user_message_type,
        "user_text": i.user_text,
        "image_count": i.image_count,
        "image_urls": i.image_urls or [],
        "image_description": i.image_description,
        "nlu_intents": i.nlu_intents or [],
        "text_topic": i.text_topic,
        "text_family": i.text_family,
        "image_family": i.image_family,
        "reply_type": i.reply_type,
        "response_text": i.response_text,
        "result_code": i.result_code,
        "follow_up": i.follow_up,
        "top_results": i.top_results or [],
        "latency_ms": i.latency_ms,
        "created_at": i.created_at.isoformat(),
    }


@router.get("/interactions")
async def list_interactions(
    q: str | None = None,
    result_code: str | None = None,
    days: int | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    page, size = _paging(page, size)
    filters = []
    if q:
        filters.append(ChatInteraction.phone_number.ilike(f"%{q}%"))
    if result_code:
        filters.append(ChatInteraction.result_code.ilike(f"%{result_code.upper()}%"))
    if days:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        filters.append(ChatInteraction.created_at >= since)

    total = await _page_result(db, ChatInteraction, filters, page, size)
    result = await db.execute(
        select(ChatInteraction)
        .where(*filters)
        .order_by(ChatInteraction.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "interactions": [_interaction_row(i) for i in rows],
    }


@router.get("/interactions/{interaction_id}")
async def get_interaction(
    interaction_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(ChatInteraction).where(ChatInteraction.id == interaction_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return _interaction_row(i)


# ---- Interest events ----


@router.get("/interests")
async def list_interests(
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    page, size = _paging(page, size)
    filters = []
    if status:
        filters.append(InterestEvent.status == status)
    if q:
        filters.append(InterestEvent.buyer_phone.ilike(f"%{q}%"))

    total = await _page_result(db, InterestEvent, filters, page, size)
    result = await db.execute(
        select(InterestEvent)
        .options(selectinload(InterestEvent.product), selectinload(InterestEvent.merchant))
        .where(*filters)
        .order_by(InterestEvent.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = result.scalars().all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "interests": [
            {
                "id": ie.id,
                "buyer_phone": ie.buyer_phone,
                "result_code": ie.result_code,
                "status": ie.status.value,
                "created_at": ie.created_at.isoformat(),
                "search_images": ie.search_image_urls or [],
                "product": {
                    "id": ie.product.id,
                    "name": ie.product.name,
                    "price": ie.product.price,
                    "currency": ie.product.currency,
                    "category": ie.product.category,
                } if ie.product else None,
                "merchant": {
                    "id": ie.merchant.id,
                    "business_name": ie.merchant.business_name,
                    "phone_number": ie.merchant.phone_number,
                } if ie.merchant else None,
            }
            for ie in rows
        ],
    }


# ---- Analytics ----


@router.get("/analytics")
async def admin_analytics(
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

    interactions = list((await db.execute(
        select(ChatInteraction).where(ChatInteraction.created_at >= since).order_by(ChatInteraction.created_at.asc())
    )).scalars().all())

    interests = list((await db.execute(
        select(InterestEvent).where(InterestEvent.created_at >= since).order_by(InterestEvent.created_at.asc())
    )).scalars().all())

    # Conversation volume timeline.
    volume_rows = (await db.execute(
        select(
            func.date_trunc("day", ConversationLog.created_at).label("day"),
            func.count(ConversationLog.id).label("count"),
        )
        .where(ConversationLog.created_at >= since)
        .group_by(func.date_trunc("day", ConversationLog.created_at))
        .order_by(func.date_trunc("day", ConversationLog.created_at))
    )).all()

    interaction_timeline: dict[str, int] = defaultdict(int)
    interest_timeline: dict[str, int] = defaultdict(int)
    for i in interactions:
        interaction_timeline[i.created_at.date().isoformat()] += 1
    for ie in interests:
        interest_timeline[ie.created_at.date().isoformat()] += 1

    timeline = []
    for offset in range(days + 1):
        day = (since + datetime.timedelta(days=offset)).date().isoformat()
        timeline.append({
            "date": day,
            "interactions": interaction_timeline.get(day, 0),
            "interests": interest_timeline.get(day, 0),
            "conversations": 0,
        })
    for row in volume_rows:
        key = row.day.date().isoformat() if row.day else None
        if key:
            for entry in timeline:
                if entry["date"] == key:
                    entry["conversations"] = row.count
                    break

    # Top merchants by interest volume.
    merchant_counts = Counter(ie.merchant_id for ie in interests if ie.merchant_id)
    if merchant_counts:
        top_ids = [merchant_id for merchant_id, _ in merchant_counts.most_common(10)]
        top_merchants = (await db.execute(
            select(Merchant).where(Merchant.id.in_(top_ids))
        )).scalars().all()
        top_map = {m.id: m for m in top_merchants}
        top = [
            {
                "id": merchant_id,
                "business_name": top_map[merchant_id].business_name,
                "category": top_map[merchant_id].category,
                "status": top_map[merchant_id].status.value,
                "interests": count,
            }
            for merchant_id, count in merchant_counts.most_common(10)
            if merchant_id in top_map
        ]
    else:
        top = []

    # Category demand from NLU intents + product categories in results.
    category_counter: Counter = Counter()
    for i in interactions:
        entities_categories = [
            str(intent.get("entities", {}).get("category", "")).lower()
            for intent in (i.nlu_intents or [])
            if isinstance(intent, dict)
        ]
        for category in entities_categories:
            if category:
                category_counter[category] += 1
        if i.text_family:
            category_counter[str(i.text_family).lower()] += 1

    # Reply type distribution + latency.
    reply_types = Counter((i.reply_type or "text") for i in interactions)
    latencies = [i.latency_ms for i in interactions if i.latency_ms is not None]

    return {
        "period_days": days,
        "summary": {
            "interactions": len(interactions),
            "interests": len(interests),
            "unique_buyers": len({i.phone_number for i in interactions}),
            "unique_merchants_contacted": len({ie.merchant_id for ie in interests if ie.merchant_id}),
            "result_codes_issued": len({i.result_code for i in interactions if i.result_code}),
            "average_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        },
        "timeline": timeline,
        "top_merchants": top,
        "top_categories": [{"category": cat, "count": count} for cat, count in category_counter.most_common(10)],
        "reply_types": [{"type": reply_type, "count": count} for reply_type, count in reply_types.most_common(10)],
    }


# ---- Admin bootstrap ----


@router.post("/bootstrap")
async def bootstrap_admin(
    phone: str,
    name: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Create the first admin-role user. No-op once any admin exists."""
    existing_admin = (await db.execute(
        select(User).where(User.role == UserRole.admin)
    )).scalar_one_or_none()
    if existing_admin:
        return {"message": "An admin already exists", "id": existing_admin.id}

    existing = (await db.execute(select(User).where(User.phone_number == phone))).scalar_one_or_none()
    if existing:
        existing.role = UserRole.admin
        existing.is_verified = True
        await db.commit()
        return {"message": "User promoted to admin", "id": existing.id}

    user = User(
        phone_number=phone,
        name=name,
        role=UserRole.admin,
        is_verified=True,
        is_banned=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"message": "Admin user created", "id": user.id, "phone": user.phone_number}


# ---- Admin accounts (users table) ----


@router.get("/accounts")
async def list_admin_accounts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.role == UserRole.admin).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return {"admins": [
        {
            "id": u.id,
            "phone": u.phone_number,
            "name": u.name,
            "email": u.email,
            "is_verified": u.is_verified,
            "is_banned": u.is_banned,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]}
