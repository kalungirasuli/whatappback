from fastapi import APIRouter, Depends

from src.auth.dependencies import require_client
from src.workers.nlu_router import extract_nlu

router = APIRouter(prefix="/api/nlu", tags=["nlu"])


@router.post("/extract")
async def extract_intents(
    text: str = "",
    has_image: bool = False,
    user=Depends(require_client),
):
    result = await extract_nlu(text, has_image=has_image)
    return {
        "intents": [
            {
                "type": si.type,
                "description": si.description,
                "entities": si.entities,
            }
            for si in result.search_intents
        ],
        "primary_intent": result.intent,
        "confidence": result.confidence,
        "is_multi_intent": result.is_multi_intent,
    }
