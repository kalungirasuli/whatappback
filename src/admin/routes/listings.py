from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db
from src.domain.models import Product, ProductImage
from src.domain.enums import ProductStatus
from src.admin.auth import get_current_admin

router = APIRouter(prefix="/admin/listings", tags=["admin-listings"])


@router.get("")
async def list_products(
    status: str | None = None,
    merchant_id: int | None = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    q = select(Product)
    if status:
        q = q.where(Product.status == status)
    if merchant_id:
        q = q.where(Product.merchant_id == merchant_id)
    q = q.order_by(Product.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(q)
    products = result.scalars().all()
    return {"products": [
        {
            "id": p.id,
            "merchant_id": p.merchant_id,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "price": p.price,
            "currency": p.currency,
            "stock_qty": p.stock_qty,
            "status": p.status.value,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p in products
    ], "page": page, "size": size}


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    images_result = await db.execute(
        select(ProductImage).where(ProductImage.product_id == product_id)
    )
    images = images_result.scalars().all()

    return {
        "id": p.id,
        "merchant_id": p.merchant_id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "price": p.price,
        "currency": p.currency,
        "stock_qty": p.stock_qty,
        "status": p.status.value,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "images": [{"id": img.id, "storage_url": img.storage_url, "is_primary": img.is_primary} for img in images],
    }


@router.post("/{product_id}/deactivate")
async def deactivate_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    p.status = ProductStatus.inactive
    await db.commit()
    return {"message": f"Product '{p.name}' deactivated", "status": "inactive"}


@router.post("/{product_id}/reactivate")
async def reactivate_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    p.status = ProductStatus.active
    await db.commit()
    return {"message": f"Product '{p.name}' reactivated", "status": "active"}
