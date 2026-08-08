import math
import re
from dataclasses import dataclass, field
from typing import Any

from src.services.qdrant_service import SearchResult


@dataclass
class RerankedResult:
    product_id: int
    score: float
    rank: int
    match_label: str
    metadata: dict = field(default_factory=dict)


class Reranker:
    WEIGHT_BASE = 0.6
    WEIGHT_TEXT_BOOST = 0.1
    WEIGHT_LOCATION_BOOST_CLOSE = 0.15
    WEIGHT_LOCATION_BOOST_MID = 0.05
    WEIGHT_PRICE_BOOST = 0.1
    WEIGHT_ENTITY_BOOST = 0.08

    def _haversine_km(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _text_match_score(self, query_text: str | None, metadata: dict[str, Any]) -> float:
        if not query_text:
            return 0.0

        query_words = set(re.findall(r"\w+", query_text.lower()))
        if not query_words:
            return 0.0

        product_name = (metadata.get("product_name") or "").lower()
        product_desc = (metadata.get("description") or "").lower()
        product_brand = (metadata.get("brand") or "").lower()
        product_category = (metadata.get("category") or "").lower()

        product_text = f"{product_name} {product_desc} {product_brand} {product_category}"
        product_words = set(re.findall(r"\w+", product_text))

        overlap = query_words & product_words
        if overlap:
            return self.WEIGHT_TEXT_BOOST
        return 0.0

    def _location_score(
        self,
        query_location: tuple[float, float] | None,
        metadata: dict[str, Any],
    ) -> float:
        if not query_location:
            return 0.0

        lat = metadata.get("merchant_lat")
        lng = metadata.get("merchant_lng")
        if lat is None or lng is None:
            return 0.0

        try:
            lat = float(lat)
            lng = float(lng)
        except (ValueError, TypeError):
            return 0.0

        distance = self._haversine_km(
            query_location[0], query_location[1], lat, lng
        )

        if distance <= 5.0:
            return self.WEIGHT_LOCATION_BOOST_CLOSE
        elif distance <= 20.0:
            return self.WEIGHT_LOCATION_BOOST_MID
        return 0.0

    def _price_score(
        self,
        price_range: tuple[float, float] | None,
        metadata: dict[str, Any],
    ) -> float:
        if not price_range:
            return 0.0

        price_min, price_max = price_range
        price = metadata.get("price")
        if price is None:
            return 0.0

        try:
            price = float(price)
        except (ValueError, TypeError):
            return 0.0

        if price_min <= price <= price_max:
            return self.WEIGHT_PRICE_BOOST
        return 0.0

    def _entity_match_score(
        self,
        query_entities: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> float:
        if not query_entities:
            return 0.0

        product_attributes = metadata.get("attributes") or {}
        if not isinstance(product_attributes, dict):
            product_attributes = {}
        query_attributes = query_entities.get("attributes") or {}
        if not isinstance(query_attributes, dict):
            query_attributes = {}

        keys = {
            "product_name", "item_type", "category", "brand", "model", "variant",
            "gender", "size", "color", "material", "style", "condition", "occasion",
        }
        matches = 0
        checked = 0
        for key in keys:
            query_value = query_entities.get(key, query_attributes.get(key))
            product_value = metadata.get(key, product_attributes.get(key))
            if not query_value or not product_value:
                continue
            checked += 1
            query_words = set(re.findall(r"\w+", str(query_value).lower()))
            product_words = set(re.findall(r"\w+", str(product_value).lower()))
            if query_words and query_words.intersection(product_words):
                matches += 1

        if not checked:
            return 0.0
        return min(self.WEIGHT_ENTITY_BOOST * matches, 0.24)

    def _match_label(self, score: float) -> str:
        if score >= 0.90:
            return "Exact match"
        return "Related"

    def rerank(
        self,
        results: list[SearchResult],
        query_text: str | None = None,
        query_entities: dict[str, Any] | None = None,
        query_location: tuple[float, float] | None = None,
        price_range: tuple[float, float] | None = None,
    ) -> list[RerankedResult]:
        scored: list[tuple[float, SearchResult]] = []

        for result in results:
            base = result.score * self.WEIGHT_BASE
            text_boost = self._text_match_score(query_text, result.metadata)
            entity_boost = self._entity_match_score(query_entities, result.metadata)
            location_boost = self._location_score(query_location, result.metadata)
            price_boost = self._price_score(price_range, result.metadata)

            total = base + text_boost + entity_boost + location_boost + price_boost
            scored.append((total, result))

        scored.sort(key=lambda x: x[0], reverse=True)

        reranked: list[RerankedResult] = []
        for rank, (score, result) in enumerate(scored, start=1):
            reranked.append(
                RerankedResult(
                    product_id=result.product_id,
                    score=score,
                    rank=rank,
                    match_label=self._match_label(score),
                    metadata=result.metadata,
                )
            )

        return reranked
