"""Re-index all products using the configured embedding models via VisionPipeline.

Drops and recreates the Qdrant collection so every vector uses the current
model version (e.g. SigLIP2 instead of SigLIP1).

Usage:
    python scripts/reindex_products.py
"""
import asyncio
import httpx
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select
from src.domain.models import Product, ProductImage, Merchant
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService
from src.workers.vision_pipeline import VisionPipeline
from src.core.config import settings

DB_URL = settings.database_url


async def main() -> None:
    engine = create_async_engine(DB_URL)
    qdrant = QdrantService()
    pipeline = VisionPipeline()

    # Verify models load
    emb = EmbeddingService()
    print(f"SigLIP model: {emb._siglip_model_name}")
    print(f"DINOv2 model: {emb._dinov2_model_name}")
    print(f"Text model:   {emb._text_model_name}")

    # Drop + recreate collection for clean slate
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url)
        client.delete_collection(settings.qdrant_collection)
        print(f"Dropped Qdrant collection '{settings.qdrant_collection}'")
    except Exception as e:
        print(f"Note: could not drop collection (may not exist): {e}")

    await qdrant.init_collection()
    print(f"Recreated Qdrant collection '{settings.qdrant_collection}'")

    async with AsyncSession(engine) as db:
        result = await db.execute(select(Product).order_by(Product.id))
        products = result.scalars().all()

        total = 0
        indexed = 0
        for product in products:
            total += 1
            img_result = await db.execute(
                select(ProductImage.storage_url)
                .where(ProductImage.product_id == product.id)
                .where(ProductImage.is_primary == True)
                .limit(1)
            )
            img_row = img_result.scalar_one_or_none()
            if not img_row:
                print(f"  SKIP pid={product.id} '{product.name}' — no image")
                continue

            merchant_result = await db.execute(
                select(Merchant).where(Merchant.id == product.merchant_id)
            )
            merchant = merchant_result.scalar_one_or_none()

            try:
                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.get(img_row)
                    resp.raise_for_status()
                    image_bytes = resp.content

                result = await pipeline.process_product_image(
                    product_id=product.id,
                    image_bytes=image_bytes,
                    merchant_id=product.merchant_id,
                    product_name=product.name,
                    product_category=product.category,
                    product_brand=product.brand or "",
                    product_attributes=product.attributes or {},
                    product_price=float(product.price),
                    merchant_lat=merchant.location_lat if merchant else None,
                    merchant_lng=merchant.location_lng if merchant else None,
                )
                if result.get("indexed"):
                    indexed += 1
                    print(f"  OK  pid={product.id} '{product.name}' dim={result.get('embedding_dim')} crops={result.get('crops_count')}")
                else:
                    print(f"  WARN pid={product.id} '{product.name}' indexing failed: {result}")
            except Exception as e:
                print(f"  ERR pid={product.id} '{product.name}': {e}")

    await engine.dispose()
    print(f"\nDone: {indexed}/{total} products indexed")


if __name__ == "__main__":
    asyncio.run(main())
