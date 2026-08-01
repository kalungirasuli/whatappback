from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from src.core.dependencies import get_db
from src.domain.models import Merchant, Product, ProductImage
from src.domain.enums import MerchantStatus
from src.admin.auth import get_current_admin

router = APIRouter(prefix="/admin/merchants", tags=["admin-merchants"])


@router.get("")
async def list_merchants(
    status: str | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    q = select(Merchant)
    if status:
        q = q.where(Merchant.status == status)
    q = q.order_by(Merchant.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    merchants = result.scalars().all()
    return {"merchants": [
        {
            "id": m.id,
            "phone_number": m.phone_number,
            "business_name": m.business_name,
            "category": m.category,
            "status": m.status.value,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in merchants
    ], "page": page, "size": size}


@router.get("/{merchant_id}")
async def get_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")

    products_result = await db.execute(
        select(Product).where(Product.merchant_id == merchant_id).order_by(Product.created_at.desc())
    )
    products = products_result.scalars().all()

    return {
        "id": m.id,
        "phone_number": m.phone_number,
        "business_name": m.business_name,
        "category": m.category,
        "status": m.status.value,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "products": [{
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "currency": p.currency,
            "stock_qty": p.stock_qty,
            "status": p.status.value,
        } for p in products],
    }


@router.post("/{merchant_id}/suspend")
async def suspend_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.suspended
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' suspended", "status": "suspended"}


@router.post("/{merchant_id}/reactivate")
async def reactivate_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.approved
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' reactivated", "status": "approved"}


@router.post("/{merchant_id}/ban")
async def ban_merchant(
    merchant_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    m.status = MerchantStatus.banned
    await db.execute(
        update(Product).where(Product.merchant_id == merchant_id, Product.status == "active").values(status="inactive")
    )
    await db.commit()
    return {"message": f"Merchant '{m.business_name}' banned, all products deactivated", "status": "banned"}
