import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.dependencies import get_db, get_redis
from src.domain.models import User, InterestEvent, Product
from src.auth.dependencies import require_client

router = APIRouter(prefix="/api/clients", tags=["clients"])

SEARCH_HISTORY_PREFIX = "search_history:"


@router.get("/me/profile")
async def get_profile(
    user: User = Depends(require_client),
):
    return {
        "id": user.id,
        "phone": user.phone_number,
        "name": user.name,
        "role": user.role.value,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat(),
        "last_active_at": user.last_active_at.isoformat(),
    }


@router.put("/me/profile")
async def update_profile(
    user: User = Depends(require_client),
    db: AsyncSession = Depends(get_db),
    name: str | None = None,
):
    if name is not None:
        user.name = name

    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "phone": user.phone_number,
        "name": user.name,
        "role": user.role.value,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat(),
        "last_active_at": user.last_active_at.isoformat(),
    }


@router.get("/me/interests")
async def list_interests(
    user: User = Depends(require_client),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InterestEvent)
        .options(
            selectinload(InterestEvent.product).selectinload(Product.images),
            selectinload(InterestEvent.product).selectinload(Product.merchant),
        )
        .where(InterestEvent.buyer_phone == user.phone_number)
        .order_by(InterestEvent.created_at.desc())
    )
    interests = result.scalars().all()

    return [
        {
            "id": ie.id,
            "status": ie.status.value,
            "created_at": ie.created_at.isoformat(),
            "product": {
                "id": ie.product.id,
                "name": ie.product.name,
                "price": ie.product.price,
                "currency": ie.product.currency,
                "category": ie.product.category,
                "merchant_name": ie.product.merchant.business_name if ie.product.merchant else "",
                "images": [
                    {"url": img.storage_url, "is_primary": img.is_primary}
                    for img in ie.product.images
                ],
            },
        }
        for ie in interests
    ]


@router.post("/me/interests/{product_id}")
async def express_interest(
    product_id: int,
    user: User = Depends(require_client),
    db: AsyncSession = Depends(get_db),
):
    product_result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = product_result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = await db.execute(
        select(InterestEvent).where(
            InterestEvent.buyer_phone == user.phone_number,
            InterestEvent.product_id == product_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Interest already expressed for this product")

    interest = InterestEvent(
        buyer_phone=user.phone_number,
        product_id=product_id,
        merchant_id=product.merchant_id,
    )
    db.add(interest)
    await db.commit()
    await db.refresh(interest)

    return {
        "id": interest.id,
        "status": interest.status.value,
        "created_at": interest.created_at.isoformat(),
        "product_id": product_id,
    }


@router.delete("/me/interests/{product_id}")
async def remove_interest(
    product_id: int,
    user: User = Depends(require_client),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InterestEvent).where(
            InterestEvent.buyer_phone == user.phone_number,
            InterestEvent.product_id == product_id,
        )
    )
    interest = result.scalar_one_or_none()

    if not interest:
        raise HTTPException(status_code=404, detail="Interest not found")

    await db.delete(interest)
    await db.commit()

    return {"message": "Interest removed successfully"}


@router.get("/me/history")
async def search_history(
    user: User = Depends(require_client),
    redis=Depends(get_redis),
):
    key = f"{SEARCH_HISTORY_PREFIX}{user.phone_number}"
    entries = await redis.lrange(key, 0, 19)

    history = []
    for entry in entries:
        try:
            data = json.loads(entry)
            history.append(data)
        except json.JSONDecodeError:
            continue

    return {"history": history, "total": len(history)}
