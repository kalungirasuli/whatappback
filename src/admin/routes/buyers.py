from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from src.core.dependencies import get_db
from src.domain.models import Buyer
from src.admin.auth import get_current_admin

router = APIRouter(prefix="/admin/buyers", tags=["admin-buyers"])


@router.get("")
async def list_buyers(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(
        select(Buyer).order_by(Buyer.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    buyers = result.scalars().all()
    return {"buyers": [
        {
            "id": b.id,
            "phone_number": b.phone_number,
            "is_banned": b.is_banned,
            "banned_reason": b.banned_reason,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "last_active_at": b.last_active_at.isoformat() if b.last_active_at else None,
        } for b in buyers
    ], "page": page, "size": size}


@router.get("/{buyer_id}")
async def get_buyer(
    buyer_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Buyer).where(Buyer.id == buyer_id))
    b = result.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Buyer not found")
    return {
        "id": b.id,
        "phone_number": b.phone_number,
        "is_banned": b.is_banned,
        "banned_reason": b.banned_reason,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "last_active_at": b.last_active_at.isoformat() if b.last_active_at else None,
    }


@router.post("/{buyer_id}/ban")
async def ban_buyer(
    buyer_id: int,
    reason: str = "Abuse reported",
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Buyer).where(Buyer.id == buyer_id))
    b = result.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Buyer not found")
    b.is_banned = True
    b.banned_reason = reason
    b.banned_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": f"Buyer '{b.phone_number}' banned", "status": "banned"}


@router.post("/{buyer_id}/unban")
async def unban_buyer(
    buyer_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Buyer).where(Buyer.id == buyer_id))
    b = result.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Buyer not found")
    b.is_banned = False
    b.banned_reason = None
    b.banned_at = None
    await db.commit()
    return {"message": f"Buyer '{b.phone_number}' unbanned", "status": "active"}
