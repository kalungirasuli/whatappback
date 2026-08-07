import datetime
import math
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Merchant, Buyer, Product, SubscriptionPlan, MerchantSubscription, User
from src.domain.enums import SubscriptionStatus, PlanSlug, UserRole

logger = logging.getLogger(__name__)


async def get_merchant_by_phone(db: AsyncSession, phone: str) -> Merchant | None:
    result = await db.execute(select(Merchant).where(Merchant.phone_number == phone))
    return result.scalar_one_or_none()


async def get_buyer_by_phone(db: AsyncSession, phone: str) -> Buyer | None:
    result = await db.execute(select(Buyer).where(Buyer.phone_number == phone))
    return result.scalar_one_or_none()


async def create_buyer(db: AsyncSession, phone: str) -> Buyer:
    buyer = Buyer(phone_number=phone)
    db.add(buyer)
    await db.commit()
    await db.refresh(buyer)
    return buyer


async def ensure_whatsapp_user(
    db: AsyncSession,
    phone: str,
    role: UserRole = UserRole.client,
) -> User:
    result = await db.execute(select(User).where(User.phone_number == phone))
    user = result.scalar_one_or_none()
    now = datetime.datetime.now(datetime.UTC)
    if user is None:
        user = User(
            phone_number=phone,
            role=role,
            is_verified=True,
            is_banned=False,
            created_at=now,
            last_active_at=now,
        )
        db.add(user)
    else:
        user.last_active_at = now
        user.is_verified = True
    await db.commit()
    await db.refresh(user)
    return user


async def create_merchant(
    db: AsyncSession, phone: str, business_name: str, category: str,
    lat: float | None = None, lng: float | None = None,
) -> Merchant:
    merchant = Merchant(
        phone_number=phone,
        business_name=business_name,
        category=category,
        location_lat=lat,
        location_lng=lng,
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(merchant)
    return merchant


async def get_merchant_by_id(db: AsyncSession, merchant_id: int) -> Merchant | None:
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    return result.scalar_one_or_none()


async def get_product_by_id(db: AsyncSession, product_id: int) -> Product | None:
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one_or_none()


async def get_product_by_id_and_merchant(
    db: AsyncSession, product_id: int, merchant_id: int
) -> Product | None:
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.merchant_id == merchant_id)
    )
    return result.scalar_one_or_none()


async def update_product(
    db: AsyncSession, product: Product, **fields
) -> Product:
    for key, value in fields.items():
        if hasattr(product, key) and value is not None:
            setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return product


async def delete_product(db: AsyncSession, product: Product) -> None:
    await db.delete(product)
    await db.commit()


async def get_nearby_products(
    lat: float, lon: float, radius_km: float = 10.0, limit: int = 20
) -> list[dict]:
    try:
        return await _get_nearby_products_postgis(lat, lon, radius_km, limit)
    except Exception as e:
        logger.info("PostGIS not available, falling back to Haversine: %s", e)
        return await _get_nearby_products_haversine(lat, lon, radius_km, limit)


async def _get_nearby_products_postgis(
    lat: float, lon: float, radius_km: float, limit: int
) -> list[dict]:
    from src.core.dependencies import async_session_factory

    query = text("""
        SELECT
            p.id AS product_id,
            p.name AS product_name,
            p.category,
            p.price,
            p.currency,
            p.stock_qty,
            p.status,
            m.id AS merchant_id,
            m.business_name,
            m.location_lat,
            m.location_lng,
            ST_Distance(
                ST_SetSRID(ST_MakePoint(m.location_lng, m.location_lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            ) / 1000.0 AS distance_km
        FROM products p
        JOIN merchants m ON p.merchant_id = m.id
        WHERE p.status = 'active'
          AND p.stock_qty > 0
          AND m.location_lat IS NOT NULL
          AND m.location_lng IS NOT NULL
          AND ST_DWithin(
              ST_SetSRID(ST_MakePoint(m.location_lng, m.location_lat), 4326)::geography,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius_m
          )
        ORDER BY distance_km ASC
        LIMIT :lim
    """)

    async with async_session_factory() as db:
        result = await db.execute(
            query, {"lat": lat, "lon": lon, "radius_m": radius_km * 1000, "lim": limit}
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def _get_nearby_products_haversine(
    lat: float, lon: float, radius_km: float, limit: int
) -> list[dict]:
    from src.core.dependencies import async_session_factory

    query = select(
        Product.id.label("product_id"),
        Product.name.label("product_name"),
        Product.category,
        Product.price,
        Product.currency,
        Product.stock_qty,
        Product.status,
        Merchant.id.label("merchant_id"),
        Merchant.business_name,
        Merchant.location_lat,
        Merchant.location_lng,
    ).join(Merchant, Product.merchant_id == Merchant.id).where(
        Product.status == "active",
        Product.stock_qty > 0,
        Merchant.location_lat.isnot(None),
        Merchant.location_lng.isnot(None),
    )

    async with async_session_factory() as db:
        result = await db.execute(query)
        rows = result.mappings().all()

        nearby = []
        for row in rows:
            m_lat = float(row["location_lat"])
            m_lon = float(row["location_lng"])
            dist = _haversine_distance(lat, lon, m_lat, m_lon)
            if dist <= radius_km:
                entry = dict(row)
                entry["distance_km"] = round(dist, 2)
                nearby.append(entry)

        nearby.sort(key=lambda x: x["distance_km"])
        return nearby[:limit]


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ─── Subscription Plan Functions ────────────────────────────────────────────────

async def get_all_active_plans(db: AsyncSession) -> list[SubscriptionPlan]:
    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order)
    )
    return list(result.scalars().all())


async def get_plan_by_slug(db: AsyncSession, slug: str) -> SubscriptionPlan | None:
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.slug == slug)
    )
    return result.scalar_one_or_none()


async def get_plan_by_id(db: AsyncSession, plan_id: int) -> SubscriptionPlan | None:
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    return result.scalar_one_or_none()


async def get_active_subscription(db: AsyncSession, merchant_id: int) -> MerchantSubscription | None:
    result = await db.execute(
        select(MerchantSubscription).where(
            MerchantSubscription.merchant_id == merchant_id,
            MerchantSubscription.status == SubscriptionStatus.active,
        )
    )
    return result.scalar_one_or_none()


async def get_active_plan(db: AsyncSession, merchant_id: int) -> SubscriptionPlan | None:
    sub = await get_active_subscription(db, merchant_id)
    if not sub:
        return None
    return await get_plan_by_id(db, sub.plan_id)


async def subscribe_merchant(
    db: AsyncSession, merchant_id: int, plan_id: int
) -> MerchantSubscription:
    import datetime

    # Cancel any existing active subscription
    existing = await get_active_subscription(db, merchant_id)
    if existing:
        existing.status = SubscriptionStatus.cancelled
        existing.updated_at = datetime.datetime.now(datetime.UTC)
        await db.flush()

    subscription = MerchantSubscription(
        merchant_id=merchant_id,
        plan_id=plan_id,
        status=SubscriptionStatus.active,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def seed_default_plans(db: AsyncSession) -> None:
    """Seed the 4 default subscription plans if none exist."""
    result = await db.execute(select(SubscriptionPlan).limit(1))
    if result.scalar_one_or_none():
        return  # Already seeded

    plans = [
        SubscriptionPlan(
            name="Starter",
            slug=PlanSlug.starter,
            description="Perfect for new sellers. Get started with a basic shop.",
            price=0.0,
            currency="UGX",
            max_products=5,
            max_images_per_product=1,
            features='["basic_search_listing", "whatsapp_support"]',
            is_active=True,
            sort_order=1,
        ),
        SubscriptionPlan(
            name="Growth",
            slug=PlanSlug.growth,
            description="For growing businesses. More products, more visibility.",
            price=50000.0,
            currency="UGX",
            max_products=50,
            max_images_per_product=3,
            features='["priority_search", "whatsapp_support", "analytics_basic"]',
            is_active=True,
            sort_order=2,
        ),
        SubscriptionPlan(
            name="Pro",
            slug=PlanSlug.pro,
            description="For serious sellers. Unlimited products, featured listings.",
            price=150000.0,
            currency="UGX",
            max_products=500,
            max_images_per_product=5,
            features='["featured_listing", "analytics_advanced", "whatsapp_support", "priority_support"]',
            is_active=True,
            sort_order=3,
        ),
        SubscriptionPlan(
            name="Enterprise",
            slug=PlanSlug.enterprise,
            description="For large operations. Everything unlimited, API access.",
            price=500000.0,
            currency="UGX",
            max_products=999999,
            max_images_per_product=10,
            features='["unlimited", "api_access", "custom_branding", "dedicated_support"]',
            is_active=True,
            sort_order=4,
        ),
    ]

    for plan in plans:
        db.add(plan)
    await db.commit()


# ─── User Functions ────────────────────────────────────────────────────────────

async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    result = await db.execute(select(User).where(User.phone_number == phone))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession, phone: str, role: str, name: str | None = None
) -> User:
    user = User(
        phone_number=phone,
        name=name,
        role=UserRole(role),
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user: User, **fields) -> User:
    for key, value in fields.items():
        if hasattr(user, key) and value is not None:
            setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user
