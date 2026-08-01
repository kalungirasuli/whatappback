import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domain.models import Merchant, Product
from src.services.postgres_service import get_active_plan


async def is_new_merchant(merchant: Merchant) -> bool:
    if not merchant.created_at:
        return True
    window = datetime.timedelta(days=settings.new_merchant_window_days)
    return datetime.datetime.now(datetime.UTC) - merchant.created_at < window


async def get_daily_listing_count(db: AsyncSession, merchant_id: int) -> int:
    today_start = datetime.datetime.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.merchant_id == merchant_id,
            Product.created_at >= today_start,
        )
    )
    return result.scalar() or 0


async def get_total_product_count(db: AsyncSession, merchant_id: int) -> int:
    result = await db.execute(
        select(func.count(Product.id)).where(Product.merchant_id == merchant_id)
    )
    return result.scalar() or 0


async def check_listing_limit(db: AsyncSession, merchant: Merchant) -> tuple[bool, str | None]:
    # Check plan product limit
    plan = await get_active_plan(db, merchant.id)
    if plan and plan.max_products < 999999:
        total = await get_total_product_count(db, merchant.id)
        if total >= plan.max_products:
            return False, (
                f"You've reached the {plan.name} plan limit of {plan.max_products} products.\n"
                "Send @plans to see upgrade options."
            )

    # Check new merchant daily limit
    if not await is_new_merchant(merchant):
        return True, None

    daily_count = await get_daily_listing_count(db, merchant.id)
    if daily_count >= settings.new_merchant_max_listings_per_day:
        return False, (
            f"As a new merchant, you can post up to {settings.new_merchant_max_listings_per_day} "
            f"products per day. You've reached today's limit. Please try again tomorrow."
        )
    return True, None
