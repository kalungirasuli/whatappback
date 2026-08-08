import secrets
import string
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.domain.models import ResultCode
from src.services.reranker import RerankedResult

logger = logging.getLogger(__name__)

CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 4
CODE_PREFIX = "RS"


class ResultCodeService:
    async def generate(self, db: AsyncSession) -> str:
        for _ in range(20):
            suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            code = f"{CODE_PREFIX}-{suffix}"
            existing = await db.execute(
                select(ResultCode).where(ResultCode.code == code)
            )
            if not existing.scalar_one_or_none():
                return code
        raise RuntimeError("Failed to generate unique result code after 20 attempts")

    async def store(
        self,
        db: AsyncSession,
        code: str,
        user_id: int,
        search_query: str | None = None,
        image_description: str | None = None,
        category: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        product_ids: list[int] | None = None,
        sample_products: list[dict] | None = None,
    ) -> ResultCode:
        record = ResultCode(
            code=code,
            search_query=search_query,
            image_description=image_description,
            category=category,
            price_min=price_min,
            price_max=price_max,
            product_ids=product_ids or [],
            sample_products=sample_products or [],
            user_id=user_id,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    async def lookup(self, db: AsyncSession, code: str) -> dict | None:
        result = await db.execute(
            select(ResultCode).where(ResultCode.code == code.upper())
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "code": record.code,
            "search_query": record.search_query,
            "image_description": record.image_description,
            "category": record.category,
            "price_min": record.price_min,
            "price_max": record.price_max,
            "product_count": len(record.product_ids),
            "product_ids": list(record.product_ids),
            "sample_products": record.sample_products,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    async def get_by_user(self, db: AsyncSession, user_id: int, limit: int = 5) -> list[ResultCode]:
        result = await db.execute(
            select(ResultCode)
            .where(ResultCode.user_id == user_id)
            .order_by(ResultCode.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    def build_sample_products(reranked_results: list[RerankedResult], db_products: dict) -> list[dict]:
        seen: set[int] = set()
        samples: list[dict] = []
        for r in reranked_results:
            if r.product_id in seen:
                continue
            seen.add(r.product_id)
            product = db_products.get(r.product_id)
            if product:
                samples.append({
                    "name": product.name,
                    "price": product.price,
                })
                if len(samples) >= 3:
                    break
        return samples
