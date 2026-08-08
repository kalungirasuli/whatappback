import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.dependencies import get_db
from src.domain.models import Product, ProductImage, Merchant, User
from src.domain.enums import ProductStatus
from src.auth.dependencies import require_merchant
from src.services.object_storage import upload_image, delete_image
from src.services.qdrant_service import QdrantService

router = APIRouter(prefix="/api/products", tags=["products"])

qdrant_service = QdrantService()


def _parse_attributes(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get("")
async def list_my_products(
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.merchant_id == db_merchant.id)
        .order_by(Product.created_at.desc())
    )
    products = result.scalars().all()

    return [
        {
            "id": p.id,
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
            "images": [
                {"id": img.id, "url": img.storage_url, "is_primary": img.is_primary}
                for img in p.images
            ],
        }
        for p in products
    ]


@router.post("")
async def create_product(
    name: str,
    category: str,
    price: float,
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
    brand: str | None = None,
    attributes: str | None = None,
    stock_qty: int = 0,
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    product = Product(
        merchant_id=db_merchant.id,
        name=name,
        brand=brand,
        category=category,
        attributes=_parse_attributes(attributes),
        price=price,
        stock_qty=stock_qty,
        status=ProductStatus.pending_moderation,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "attributes": product.attributes or {},
        "price": product.price,
        "currency": product.currency,
        "stock_qty": product.stock_qty,
        "status": product.status.value,
        "created_at": product.created_at.isoformat(),
    }


@router.get("/public/latest")
async def list_latest_products(
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    limit = min(limit, 100)
    offset = (page - 1) * limit

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status == ProductStatus.active)
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    products = result.scalars().all()

    count_result = await db.execute(
        select(func.count(Product.id)).where(Product.status == ProductStatus.active)
    )
    total = count_result.scalar()

    return {
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "attributes": p.attributes or {},
                "price": p.price,
                "currency": p.currency,
                "stock_qty": p.stock_qty,
                "created_at": p.created_at.isoformat(),
                "images": [
                    {"url": img.storage_url, "is_primary": img.is_primary}
                    for img in p.images
                ],
            }
            for p in products
        ],
        "page": page,
        "limit": limit,
        "total": total,
    }


@router.get("/public/category/{category}")
async def list_products_by_category(
    category: str,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    limit = min(limit, 100)
    offset = (page - 1) * limit

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status == ProductStatus.active, Product.category == category)
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    products = result.scalars().all()

    count_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.status == ProductStatus.active, Product.category == category
        )
    )
    total = count_result.scalar()

    return {
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "brand": p.brand,
                "category": p.category,
                "price": p.price,
                "currency": p.currency,
                "stock_qty": p.stock_qty,
                "created_at": p.created_at.isoformat(),
                "images": [
                    {"url": img.storage_url, "is_primary": img.is_primary}
                    for img in p.images
                ],
            }
            for p in products
        ],
        "page": page,
        "limit": limit,
        "total": total,
    }


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images), selectinload(Product.merchant))
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "attributes": product.attributes or {},
        "price": product.price,
        "currency": product.currency,
        "stock_qty": product.stock_qty,
        "status": product.status.value,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
        "merchant": {
            "id": product.merchant.id,
            "business_name": product.merchant.business_name,
            "category": product.merchant.category,
        },
        "images": [
            {"id": img.id, "url": img.storage_url, "is_primary": img.is_primary}
            for img in product.images
        ],
    }


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
    name: str | None = None,
    brand: str | None = None,
    category: str | None = None,
    price: float | None = None,
    attributes: str | None = None,
    stock_qty: int | None = None,
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(Product).where(
            Product.id == product_id, Product.merchant_id == db_merchant.id
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    if name is not None:
        product.name = name
    if brand is not None:
        product.brand = brand
    if category is not None:
        product.category = category
    if price is not None:
        product.price = price
    if attributes is not None:
        product.attributes = _parse_attributes(attributes)
    if stock_qty is not None:
        product.stock_qty = stock_qty

    product.updated_at = datetime.datetime.now(datetime.timezone.utc)

    changed = {}
    if name is not None:
        changed["product_name"] = name
    if brand is not None:
        changed["brand"] = brand
    if category is not None:
        changed["category"] = category
    if price is not None:
        changed["price"] = price
    if attributes is not None:
        changed["attributes"] = product.attributes or {}

    if changed:
        try:
            await qdrant_service.update_metadata(product.id, changed)
        except Exception:
            pass

    await db.commit()
    await db.refresh(product)

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "attributes": product.attributes or {},
        "price": product.price,
        "currency": product.currency,
        "stock_qty": product.stock_qty,
        "status": product.status.value,
        "updated_at": product.updated_at.isoformat(),
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(Product).where(
            Product.id == product_id, Product.merchant_id == db_merchant.id
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    try:
        await qdrant_service.delete_product(product_id)
    except Exception:
        pass

    await db.delete(product)
    await db.commit()

    return {"message": "Product deleted successfully"}


@router.post("/{product_id}/images")
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(Product).where(
            Product.id == product_id, Product.merchant_id == db_merchant.id
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    content_type = file.content_type or "image/jpeg"
    url = await upload_image(content, content_type)

    existing_count_result = await db.execute(
        select(func.count(ProductImage.id)).where(ProductImage.product_id == product_id)
    )
    existing_count = existing_count_result.scalar()

    is_primary = (existing_count == 0)
    image = ProductImage(
        product_id=product_id,
        storage_url=url,
        is_primary=is_primary,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)

    if is_primary:
        try:
            from src.workers.vision_pipeline import VisionPipeline
            pipeline = VisionPipeline()
            result = await pipeline.process_product_image(
                product_id=product.id,
                image_bytes=content,
                merchant_id=db_merchant.id,
                product_name=product.name,
                product_category=product.category,
                product_brand=product.brand or "",
                product_attributes=product.attributes or {},
                product_price=product.price,
                merchant_lat=db_merchant.location_lat,
                merchant_lng=db_merchant.location_lng,
            )
            if result.get("indexed"):
                product.qdrant_point_id = str(product.id)
                await db.commit()
        except Exception:
            pass

    return {
        "id": image.id,
        "url": image.storage_url,
        "is_primary": image.is_primary,
        "moderation_status": image.moderation_status.value,
    }


@router.delete("/{product_id}/images/{image_id}")
async def delete_product_image(
    product_id: int,
    image_id: int,
    merchant: User = Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Merchant).where(Merchant.phone_number == merchant.phone_number)
    )
    db_merchant = result.scalar_one_or_none()
    if not db_merchant:
        raise HTTPException(status_code=404, detail="Merchant profile not found")

    result = await db.execute(
        select(Product).where(
            Product.id == product_id, Product.merchant_id == db_merchant.id
        )
    )
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or not owned by you")

    result = await db.execute(
        select(ProductImage).where(
            ProductImage.id == image_id, ProductImage.product_id == product_id
        )
    )
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    await delete_image(image.storage_url)
    await db.delete(image)
    await db.commit()

    return {"message": "Image deleted successfully"}
