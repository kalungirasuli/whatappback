import asyncio
import logging

from src.services.categories import (
    SCORE_BAND_RATIO,
    family_for_category,
    family_for_detector_labels,
)
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService, SearchResult
from src.services.reranker import Reranker, RerankedResult
from src.services.detector import ObjectDetector

logger = logging.getLogger(__name__)

_embedding = EmbeddingService()
_qdrant = QdrantService()
_reranker = Reranker()
_detector = ObjectDetector()


def apply_consistency_filter(
    results: list[RerankedResult],
    preferred_family: str | None = None,
) -> list[RerankedResult]:
    """Ensures results are from the same product family, with two-way fallback."""
    if not results:
        return results

    top_category_family = family_for_category(results[0].metadata.get("category"))

    family = preferred_family
    if family is None:
        family = top_category_family

    filtered = results
    if family is not None:
        matched = [
            r for r in results
            if family_for_category(r.metadata.get("category")) == family
        ]
        if not matched and top_category_family is not None:
            matched = [
                r for r in results
                if family_for_category(r.metadata.get("category")) == top_category_family
            ]
        if matched:
            filtered = matched

    top_score = filtered[0].score if filtered else 0.0
    if top_score > 0:
        kept = [r for r in filtered if r.score >= top_score * SCORE_BAND_RATIO]
        if kept:
            filtered = kept

    for i, r in enumerate(filtered, start=1):
        r.rank = i
        r.match_label = _reranker._match_label(i)
    return filtered


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
        labels = [c.label for c in crops if c.label]

        siglip_vector = await _embedding.embed_image(primary)
        dinov2_vector = await _embedding.embed_image_dinov2(primary)

        hybrid_results = await _qdrant.hybrid_search(siglip_vector, dinov2_vector, top_k=50)

        reranked = _reranker.rerank(
            results=hybrid_results,
            query_location=buyer_location,
            price_range=price_range,
        )

        preferred_family = family_for_detector_labels(labels)
        try:
            best_conf = max((c.confidence for c in crops if getattr(c, "label", None)), default=0)
            if best_conf < 0.60:
                preferred_family = None
        except (AttributeError, TypeError):
            pass
        return apply_consistency_filter(reranked, preferred_family=preferred_family)

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

        return apply_consistency_filter(reranked)

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