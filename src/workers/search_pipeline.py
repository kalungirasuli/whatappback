import asyncio
import logging

from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService, SearchResult
from src.services.reranker import Reranker, RerankedResult
from src.services.detector import ObjectDetector

logger = logging.getLogger(__name__)

_embedding = EmbeddingService()
_qdrant = QdrantService()
_reranker = Reranker()
_detector = ObjectDetector()


class SearchPipeline:
    async def search_by_image(
        self,
        image_bytes: bytes | None = None,
        buyer_location: tuple[float, float] | None = None,
        price_range: tuple[float, float] | None = None,
    ) -> list[RerankedResult]:
        if not image_bytes:
            return []

        crops = await _detector.detect_and_crop(image_bytes)
        primary = crops[0].image_bytes if crops else image_bytes

        siglip_vector = await _embedding.embed_image(primary)
        dinov2_vector = await _embedding.embed_image_dinov2(primary)

        hybrid_results = await _qdrant.hybrid_search(siglip_vector, dinov2_vector, top_k=50)

        reranked = _reranker.rerank(
            results=hybrid_results,
            query_location=buyer_location,
            price_range=price_range,
        )

        return reranked

    async def search_by_text(
        self,
        text: str,
        buyer_location: tuple[float, float] | None = None,
        price_range: tuple[float, float] | None = None,
    ) -> list[RerankedResult]:
        if not text or not text.strip():
            return []

        query_vector = await _embedding.embed_text(text.strip())

        raw_results = await _qdrant.search_similar(
            query_vector=query_vector,
            top_k=50,
            vector_name="text",
        )

        reranked = _reranker.rerank(
            results=raw_results,
            query_text=text,
            query_location=buyer_location,
            price_range=price_range,
        )

        return reranked

    async def format_reply(
        self,
        results: list[RerankedResult],
        max_results: int = 5,
        section_title: str | None = None,
    ) -> str:
        if not results:
            return ""

        top = results[:max_results]
        prefix = f"*{section_title}*\n\n" if section_title else ""
        lines: list[str] = [prefix]

        for r in top:
            product_name = r.metadata.get("product_name", f"Product #{r.product_id}")
            price = r.metadata.get("price")
            price_str = f" - {float(price):,.0f} UGX" if price else ""
            seller = r.metadata.get("merchant_name", "")

            entry = f"*{r.rank}.* {product_name}{price_str}"
            entry += f"\n   Match: {r.match_label}"
            if seller:
                entry += f"\n   Seller: {seller}"
            lines.append(entry)

        return "\n\n".join(lines)