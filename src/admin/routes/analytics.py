from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from src.core.dependencies import get_db
from src.domain.models import Merchant, Product, Buyer, ConversationLog, InterestEvent
from src.domain.enums import MerchantStatus, ProductStatus, InterestStatus
from src.admin.auth import get_current_admin

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


@router.get("/overview")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    merchant_count = (await db.execute(select(func.count(Merchant.id)))).scalar() or 0
    active_merchants = (await db.execute(
        select(func.count(Merchant.id)).where(Merchant.status == MerchantStatus.approved)
    )).scalar() or 0
    suspended_merchants = (await db.execute(
        select(func.count(Merchant.id)).where(Merchant.status == MerchantStatus.suspended)
    )).scalar() or 0
    banned_merchants = (await db.execute(
        select(func.count(Merchant.id)).where(Merchant.status == MerchantStatus.banned)
    )).scalar() or 0
    product_count = (await db.execute(select(func.count(Product.id)))).scalar() or 0
    active_products = (await db.execute(
        select(func.count(Product.id)).where(Product.status == ProductStatus.active)
    )).scalar() or 0
    buyer_count = (await db.execute(select(func.count(Buyer.id)))).scalar() or 0
    banned_buyers = (await db.execute(
        select(func.count(Buyer.id)).where(Buyer.is_banned == True)
    )).scalar() or 0
    interest_count = (await db.execute(select(func.count(InterestEvent.id)))).scalar() or 0
    responded_interests = (await db.execute(
        select(func.count(InterestEvent.id)).where(InterestEvent.status == InterestStatus.responded)
    )).scalar() or 0
    message_count = (await db.execute(select(func.count(ConversationLog.id)))).scalar() or 0
    inbound_messages = (await db.execute(
        select(func.count(ConversationLog.id)).where(ConversationLog.direction == "in")
    )).scalar() or 0

    return {
        "merchants": {
            "total": merchant_count,
            "active": active_merchants,
            "suspended": suspended_merchants,
            "banned": banned_merchants,
        },
        "products": {
            "total": product_count,
            "active": active_products,
        },
        "buyers": {
            "total": buyer_count,
            "banned": banned_buyers,
        },
        "interests": {
            "total": interest_count,
            "responded": responded_interests,
            "response_rate": f"{(responded_interests / interest_count * 100):.1f}%" if interest_count else "N/A",
        },
        "messages": {
            "total": message_count,
            "inbound": inbound_messages,
        },
    }


@router.get("/recent-merchants")
async def recent_merchants(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(
        select(Merchant).order_by(Merchant.created_at.desc()).limit(limit)
    )
    merchants = result.scalars().all()
    return {"merchants": [
        {
            "id": m.id,
            "business_name": m.business_name,
            "phone_number": m.phone_number,
            "status": m.status.value,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in merchants
    ]}


@router.get("/conversation-volume")
async def conversation_volume(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date_trunc("day", ConversationLog.created_at).label("day"),
            func.count(ConversationLog.id).label("count"),
        )
        .where(ConversationLog.created_at >= since)
        .group_by(func.date_trunc("day", ConversationLog.created_at))
        .order_by(func.date_trunc("day", ConversationLog.created_at))
    )
    rows = result.all()
    return {"data": [{"date": row.day.isoformat() if row.day else None, "count": row.count} for row in rows]}
