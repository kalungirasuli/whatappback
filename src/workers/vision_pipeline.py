import io
import logging

import imagehash
from PIL import Image

from src.services.detector import ObjectDetector
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService
from src.workers.moderation import ModerationService

logger = logging.getLogger(__name__)

_detector = ObjectDetector()
_embedding = EmbeddingService()
_qdrant = QdrantService()
_moderation = ModerationService()


class VisionPipeline:
    async def process_product_image(
        self,
        product_id: int,
        image_bytes: bytes,
        merchant_id: int,
        product_name: str = "",
        product_category: str = "",
        product_brand: str = "",
        product_price: float = 0.0,
        merchant_lat: float | None = None,
        merchant_lng: float | None = None,
    ) -> dict:
        # Step 1: Moderation check
        mod_result = await _moderation.check_image(image_bytes)
        if not mod_result.is_approved:
            logger.warning(
                f"Product {product_id} image failed moderation: {mod_result.reason}"
            )
            return {
                "product_id": product_id,
                "crops_count": 0,
                "embedding_dim": 0,
                "indexed": False,
                "moderation_rejected": True,
                "moderation_reason": mod_result.reason,
            }

        # Step 2: Detect and crop objects
        crops = await _detector.detect_and_crop(image_bytes)
        if not crops:
            crops_count = 0
        else:
            crops_count = len(crops)

        # Step 3: Embed the primary image (first crop or full image)
        primary_crop = crops[0].image_bytes if crops else image_bytes
        siglip_vector = await _embedding.embed_image(primary_crop)
        dinov2_vector = await _embedding.embed_image_dinov2(primary_crop)

        # Step 3b: Embed the product text for text-based search
        text_for_embedding = " ".join(
            p for p in [product_name, product_brand, product_category] if p
        )
        text_vector = await _embedding.embed_text(text_for_embedding)

        # Step 3c: Compute perceptual hash for exact pixel-level matching
        try:
            pil_img = Image.open(io.BytesIO(primary_crop))
            phash = str(imagehash.phash(pil_img))
        except Exception:
            phash = ""

        # Step 4: Upsert to Qdrant with metadata
        metadata = {
            "product_id": product_id,
            "merchant_id": merchant_id,
            "product_name": product_name,
            "category": product_category,
            "brand": product_brand,
            "price": product_price,
            "merchant_lat": merchant_lat,
            "merchant_lng": merchant_lng,
            "crops_count": crops_count,
            "phash": phash,
        }

        await _qdrant.upsert_product(
            product_id=product_id,
            siglip_vector=siglip_vector,
            dinov2_vector=dinov2_vector,
            text_vector=text_vector,
            metadata=metadata,
        )

        logger.info(
            f"VisionPipeline indexed product {product_id}: "
            f"{crops_count} crops, dim={len(siglip_vector)}"
        )

        return {
            "product_id": product_id,
            "crops_count": crops_count,
            "embedding_dim": len(siglip_vector),
            "indexed": True,
        }
