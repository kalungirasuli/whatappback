import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.dependencies import get_db
from src.domain.models import User, Merchant, Product, InterestEvent, MerchantSubscription, SubscriptionPlan
from src.domain.enums import ProductStatus, MerchantStatus, UserRole
from src.auth.dependencies import require_merchant, get_current_user
from src.services.postgres_service import create_merchant

router = APIRouter(prefix="/api/merchants", tags=["merchants"])


@router.get("/me/dashboard")
async def get_dashboard(
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    total_products_result = await db.execute(
        select(func.count(Product.id)).where(Product.merchant_id == db_merchant.id)
    )
    total_products = total_products_result.scalar()

    active_products_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.merchant_id == db_merchant.id,
            Product.status == ProductStatus.active,
        )
    )
    active_products = active_products_result.scalar()

    total_interests_result = await db.execute(
        select(func.count(InterestEvent.id)).where(
            InterestEvent.merchant_id == db_merchant.id
        )
    )
    total_interests = total_interests_result.scalar()

    week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    weekly_interests_result = await db.execute(
        select(func.count(InterestEvent.id)).where(
            InterestEvent.merchant_id == db_merchant.id,
            InterestEvent.created_at >= week_ago,
        )
    )
    interests_this_week = weekly_interests_result.scalar()

    sub_result = await db.execute(
        select(MerchantSubscription)
        .options(selectinload(MerchantSubscription.plan))
        .where(
            MerchantSubscription.merchant_id == db_merchant.id,
            MerchantSubscription.status == "active",
        )
    )
    subscription = sub_result.scalar_one_or_none()
    plan_name = subscription.plan.name if subscription and subscription.plan else "None"

    return {
        "total_products": total_products,
        "active_products": active_products,
        "total_interests": total_interests,
        "interests_this_week": interests_this_week,
        "plan_name": plan_name,
    }


@router.get("/me/subscription")
async def get_subscription(
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    sub_result = await db.execute(
        select(MerchantSubscription)
        .options(selectinload(MerchantSubscription.plan))
        .where(
            MerchantSubscription.merchant_id == db_merchant.id,
            MerchantSubscription.status == "active",
        )
    )
    subscription = sub_result.scalar_one_or_none()

    if not subscription:
        return {
            "active": False,
            "plan": None,
            "started_at": None,
            "expires_at": None,
        }

    return {
        "active": True,
        "plan": {
            "id": subscription.plan.id,
            "name": subscription.plan.name,
            "slug": subscription.plan.slug.value,
            "price": subscription.plan.price,
            "currency": subscription.plan.currency,
            "max_products": subscription.plan.max_products,
            "max_images_per_product": subscription.plan.max_images_per_product,
            "features": subscription.plan.features,
        },
        "started_at": subscription.started_at.isoformat(),
        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
    }


@router.post("/me/subscription")
async def change_subscription(
    plan_id: int,
    user: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    plan_result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.id == plan_id, SubscriptionPlan.is_active == True
        )
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found or inactive")

    existing_sub_result = await db.execute(
        select(MerchantSubscription).where(
            MerchantSubscription.merchant_id == db_merchant.id,
            MerchantSubscription.status == "active",
        )
    )
    existing_sub = existing_sub_result.scalar_one_or_none()

    if existing_sub:
        existing_sub.status = "cancelled"
        existing_sub.updated_at = datetime.datetime.now(datetime.timezone.utc)
        await db.flush()

    new_sub = MerchantSubscription(
        merchant_id=db_merchant.id,
        plan_id=plan.id,
        status="active",
    )
    db.add(new_sub)
    await db.commit()
    await db.refresh(new_sub)

    return {
        "id": new_sub.id,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "slug": plan.slug.value,
            "price": plan.price,
        },
        "status": new_sub.status.value,
        "started_at": new_sub.started_at.isoformat(),
    }


@router.get("/me/interests")
async def list_merchant_interests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(InterestEvent)
        .where(InterestEvent.merchant_id == db_merchant.id)
        .order_by(InterestEvent.created_at.desc())
    )
    interests = result.scalars().all()

    buyer_phones = list(set(ie.buyer_phone for ie in interests))

    return [
        {
            "id": ie.id,
            "buyer_phone": ie.buyer_phone,
            "product_id": ie.product_id,
            "status": ie.status.value,
            "created_at": ie.created_at.isoformat(),
        }
        for ie in interests
    ]


@router.get("/me/profile")
async def get_merchant_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()

    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    return {
        "id": db_merchant.id,
        "phone_number": db_merchant.phone_number,
        "business_name": db_merchant.business_name,
        "category": db_merchant.category,
        "location_lat": db_merchant.location_lat,
        "location_lng": db_merchant.location_lng,
        "status": db_merchant.status.value,
        "created_at": db_merchant.created_at.isoformat(),
    }


@router.put("/me/profile")
async def update_merchant_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    business_name: str | None = None,
    category: str | None = None,
    location_lat: float | None = None,
    location_lng: float | None = None,
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == user.phone_number)
    )
    db_merchant = result.scalar_one_or_none()

    if not db_merchant:
        if not business_name:
            raise HTTPException(status_code=400, detail="business_name is required to create a merchant profile")
        db_merchant = await create_merchant(
            db,
            phone=user.phone_number,
            business_name=business_name,
            category=category or "",
            lat=location_lat,
            lng=location_lng,
        )
        if user.role != UserRole.merchant:
            user.role = UserRole.merchant
            await db.commit()
            await db.refresh(user)
    else:
        if business_name is not None:
            db_merchant.business_name = business_name
        if category is not None:
            db_merchant.category = category
        if location_lat is not None:
            db_merchant.location_lat = location_lat
        if location_lng is not None:
            db_merchant.location_lng = location_lng

        await db.commit()
        await db.refresh(db_merchant)

    return {
        "id": db_merchant.id,
        "phone_number": db_merchant.phone_number,
        "business_name": db_merchant.business_name,
        "category": db_merchant.category,
        "location_lat": db_merchant.location_lat,
        "location_lng": db_merchant.location_lng,
        "status": db_merchant.status.value,
        "created_at": db_merchant.created_at.isoformat(),
    }
