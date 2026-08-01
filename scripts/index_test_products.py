import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select
from src.domain.models import Product, Merchant
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService


async def index_products():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5433/whatappseller")
    embedding = EmbeddingService()
    qdrant = QdrantService()

    from qdrant_client import QdrantClient
    client = QdrantClient(url="http://localhost:6333")
    client.delete_collection("products")

    await qdrant.init_collection()

    async with AsyncSession(engine) as db:
        result = await db.execute(select(Product))
        products = result.scalars().all()
        merch = (await db.execute(select(Merchant).where(Merchant.id == 1))).scalar_one()
        for p in products:
            text = f"{p.name} {p.brand or ''} {p.category}"
            text_vec = await embedding.embed_text(text)
            siglip_vec = await embedding.embed_text(text)
            dinov2_vec = await embedding.embed_text(text)
            await qdrant.upsert_product(
                product_id=p.id,
                siglip_vector=siglip_vec,
                dinov2_vector=dinov2_vec,
                text_vector=text_vec,
                metadata={
                    "product_id": p.id,
                    "merchant_id": p.merchant_id,
                    "product_name": p.name,
                    "brand": p.brand or "",
                    "category": p.category,
                    "price": p.price,
                    "currency": p.currency,
                    "merchant_lat": merch.location_lat,
                    "merchant_lng": merch.location_lng,
                },
            )
            p.qdrant_point_id = str(p.id)
            print(f"Indexed product {p.id}: {p.name} (text_dim {len(text_vec)})")
        await db.commit()
    await engine.dispose()


asyncio.run(index_products())
