from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dependencies import get_db
from src.auth.dependencies import require_merchant
from src.services.result_code_service import ResultCodeService

router = APIRouter(prefix="/api/result-codes", tags=["result-codes"])
_service = ResultCodeService()


@router.get("/{code}")
async def lookup_result_code(
    code: str,
    user=Depends(require_merchant),
    db: AsyncSession = Depends(get_db),
):
    lookup = await _service.lookup(db, code)
    if not lookup:
        raise HTTPException(status_code=404, detail=f"No results found for code '{code.upper()}'")

    return {
        "code": lookup["code"],
        "search_query": lookup["search_query"],
        "image_description": lookup["image_description"],
        "category": lookup["category"],
        "price_min": lookup["price_min"],
        "price_max": lookup["price_max"],
        "product_count": lookup["product_count"],
        "sample_products": lookup["sample_products"],
        "created_at": lookup["created_at"],
    }
