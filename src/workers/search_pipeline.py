import asyncio
import logging

from src.services.categories import (
    SCORE_BAND_RATIO,
    family_for_category,
    family_for_detector_labels,
)
from src.core.config import settings
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService, SearchResult
from src.services.reranker import Reranker, RerankedResult
from src.services.detector import ObjectDetector
from src.services.lexical_search import lexical_fallback

logger = logging.getLogger(__name__)

# Absolute relevance floor, kept in sync with nlu_router.MIN_MATCH_SCORE.
# Results scoring below this are treated as noise rather than matches.
_MIN_RELEVANCE_SCORE = 0.3

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
        r.match_label = _reranker._match_label(r.score)
    return filtered


class SearchPipeline:
    async def search_by_image(
        self,
        image_bytes: bytes | None = None,
        query_text: str | None = None,
        query_entities: dict | None = None,
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
            query_text=query_text,
            query_entities=query_entities,
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

    async def search_all_objects(
        self,
        image_bytes: bytes | None = None,
        buyer_location: tuple[float, float] | None = None,
        price_range: tuple[float, float] | None = None,
    ) -> list[tuple[str, RerankedResult]]:
        """Search every detected object independently for exact matches."""
        if not image_bytes:
            return []

        crops = await _detector.detect_and_crop(image_bytes)
        if not crops:
            return []

        exact_matches: list[tuple[str, RerankedResult]] = []
        exact_threshold = settings.exact_match_threshold
        min_score = 0.30
        seen_product_ids: set[int] = set()

        for crop in crops:
            label = getattr(crop, "label", "object") or "object"
            if label == "full_image":
                continue
            conf = getattr(crop, "confidence", 0)

            siglip_vec = await _embedding.embed_image(crop.image_bytes)
            dinov2_vec = await _embedding.embed_image_dinov2(crop.image_bytes)

            hybrid_results = await _qdrant.hybrid_search(siglip_vec, dinov2_vec, top_k=10)

            reranked = _reranker.rerank(
                results=hybrid_results,
                query_location=buyer_location,
                price_range=price_range,
            )

            preferred_family = family_for_detector_labels([label]) if conf >= 0.60 else None
            filtered = apply_consistency_filter(reranked, preferred_family=preferred_family)

            if not filtered:
                continue

            top_result = filtered[0]
            if top_result.score < min_score or top_result.product_id in seen_product_ids:
                continue

            section_label = (
                f"Exact match: {label}"
                if top_result.score >= exact_threshold
                else f"Related match: {label}"
            )
            exact_matches.append((section_label, top_result))
            seen_product_ids.add(top_result.product_id)

        return exact_matches

    async def search_by_text(
        self,
        text: str,
        query_entities: dict | None = None,
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
            query_entities=query_entities,
            query_location=buyer_location,
            price_range=price_range,
        )

        filtered = apply_consistency_filter(reranked)

        # Dense search missed: try a lexical/fuzzy (name-first) fallback so an
        # exact or near-exact product lookup that embeddings can't resolve
        # (e.g. a misspelled brand name) is still found. The floor matches
        # MIN_MATCH_SCORE in nlu_router (0.3), which is where results are
        # finally discarded — trigger the fallback when nothing clears it.
        strong = [r for r in filtered if r.score >= _MIN_RELEVANCE_SCORE]
        if not strong:
            try:
                fallback = await lexical_fallback(text, limit=5)
                if fallback:
                    return fallback
            except Exception:
                logger.exception("Lexical fallback search failed")

        return filtered

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
