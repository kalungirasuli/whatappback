import math

import pytest

from src.services.qdrant_service import SearchResult
from src.services.reranker import Reranker, RerankedResult


def _make_search_result(product_id: int, score: float = 0.9, **meta) -> SearchResult:
    return SearchResult(product_id=product_id, score=score, metadata=meta)


class TestHaversine:
    def test_same_location_zero_distance(self):
        r = Reranker()
        d = r._haversine_km(0.0, 0.0, 0.0, 0.0)
        assert d == 0.0

    def test_known_distance_kampala_entebbe(self):
        r = Reranker()
        d = r._haversine_km(0.3136, 32.5811, 0.0601, 32.4635)
        assert 30.0 < d < 45.0

    def test_symmetric_distance(self):
        r = Reranker()
        d1 = r._haversine_km(1.0, 2.0, 3.0, 4.0)
        d2 = r._haversine_km(3.0, 4.0, 1.0, 2.0)
        assert abs(d1 - d2) < 0.001

    def test_antipodal_points(self):
        r = Reranker()
        d = r._haversine_km(0.0, 0.0, 0.0, 180.0)
        assert d > 20000.0


class TestTextMatchScore:
    def test_matching_word_gives_boost(self):
        r = Reranker()
        meta = {"product_name": "Nike Running Shoes", "description": "lightweight", "brand": "", "category": ""}
        score = r._text_match_score("I need shoes for running", meta)
        assert score == r.WEIGHT_TEXT_BOOST

    def test_no_matching_word(self):
        r = Reranker()
        meta = {"product_name": "Laptop", "description": "gaming", "brand": "Dell", "category": ""}
        score = r._text_match_score("red shoes", meta)
        assert score == 0.0

    def test_empty_query(self):
        r = Reranker()
        meta = {"product_name": "Shoes"}
        score = r._text_match_score(None, meta)
        assert score == 0.0

    def test_empty_metadata(self):
        r = Reranker()
        score = r._text_match_score("shoes", {})
        assert score == 0.0

    def test_match_in_description(self):
        r = Reranker()
        meta = {"description": "brand new leather jacket"}
        score = r._text_match_score("jacket", meta)
        assert score == r.WEIGHT_TEXT_BOOST

    def test_match_in_category(self):
        r = Reranker()
        meta = {"category": "electronics"}
        score = r._text_match_score("electronics store", meta)
        assert score == r.WEIGHT_TEXT_BOOST


class TestLocationScore:
    def test_no_location(self):
        r = Reranker()
        score = r._location_score(None, {})
        assert score == 0.0

    def test_close_location(self):
        r = Reranker()
        meta = {"merchant_lat": 0.3140, "merchant_lng": 32.5820}
        score = r._location_score((0.3136, 32.5811), meta)
        assert score == r.WEIGHT_LOCATION_BOOST_CLOSE

    def test_mid_location(self):
        r = Reranker()
        meta = {"merchant_lat": 0.40, "merchant_lng": 32.70}
        score = r._location_score((0.3136, 32.5811), meta)
        assert score == r.WEIGHT_LOCATION_BOOST_MID

    def test_far_location(self):
        r = Reranker()
        meta = {"merchant_lat": 1.0, "merchant_lng": 33.0}
        score = r._location_score((0.3136, 32.5811), meta)
        assert score == 0.0

    def test_missing_lat_lng(self):
        r = Reranker()
        score = r._location_score((0.0, 0.0), {})
        assert score == 0.0

    def test_string_lat_lng(self):
        r = Reranker()
        meta = {"merchant_lat": "0.3140", "merchant_lng": "32.5820"}
        score = r._location_score((0.3136, 32.5811), meta)
        assert score == r.WEIGHT_LOCATION_BOOST_CLOSE

    def test_invalid_lat_lng(self):
        r = Reranker()
        meta = {"merchant_lat": "invalid", "merchant_lng": "also_invalid"}
        score = r._location_score((0.0, 0.0), meta)
        assert score == 0.0


class TestPriceScore:
    def test_no_price_range(self):
        r = Reranker()
        score = r._price_score(None, {"price": 50000})
        assert score == 0.0

    def test_price_in_range(self):
        r = Reranker()
        score = r._price_score((10000, 100000), {"price": 50000})
        assert score == r.WEIGHT_PRICE_BOOST

    def test_price_below_range(self):
        r = Reranker()
        score = r._price_score((50000, 100000), {"price": 10000})
        assert score == 0.0

    def test_price_above_range(self):
        r = Reranker()
        score = r._price_score((10000, 50000), {"price": 100000})
        assert score == 0.0

    def test_price_at_boundary(self):
        r = Reranker()
        score = r._price_score((50000, 50000), {"price": 50000})
        assert score == r.WEIGHT_PRICE_BOOST

    def test_no_price_in_metadata(self):
        r = Reranker()
        score = r._price_score((10000, 100000), {})
        assert score == 0.0

    def test_string_price(self):
        r = Reranker()
        score = r._price_score((10000, 100000), {"price": "50000"})
        assert score == r.WEIGHT_PRICE_BOOST

    def test_invalid_price_string(self):
        r = Reranker()
        score = r._price_score((10000, 100000), {"price": "not_a_number"})
        assert score == 0.0


class TestMatchLabel:
    def test_exact_match(self):
        r = Reranker()
        assert r._match_label(0.95) == "Exact match"
        assert r._match_label(0.90) == "Exact match"

    def test_closest_match(self):
        r = Reranker()
        assert r._match_label(0.75) == "Related"
        assert r._match_label(0.60) == "Related"

    def test_similar_style(self):
        r = Reranker()
        assert r._match_label(0.45) == "Related"
        assert r._match_label(0.35) == "Related"

    def test_related(self):
        r = Reranker()
        assert r._match_label(0.20) == "Related"
        assert r._match_label(0.10) == "Related"


class TestRerank:
    def test_rerank_returns_reranked_results(self):
        r = Reranker()
        results = [
            _make_search_result(1, score=0.8),
            _make_search_result(2, score=0.6),
        ]
        reranked = r.rerank(results)

        assert len(reranked) == 2
        assert all(isinstance(rr, RerankedResult) for rr in reranked)

    def test_rerank_sorted_by_score(self):
        r = Reranker()
        results = [
            _make_search_result(1, score=0.5),
            _make_search_result(2, score=0.9),
            _make_search_result(3, score=0.7),
        ]
        reranked = r.rerank(results)

        assert reranked[0].product_id == 2
        assert reranked[1].product_id == 3
        assert reranked[2].product_id == 1

    def test_rerank_base_score_formula(self):
        r = Reranker()
        results = [_make_search_result(1, score=1.0)]
        reranked = r.rerank(results)

        expected = 1.0 * r.WEIGHT_BASE
        assert abs(reranked[0].score - expected) < 0.001

    def test_rerank_with_text_boost(self):
        r = Reranker()
        results = [
            _make_search_result(1, score=0.8, product_name="red shoes"),
            _make_search_result(2, score=0.8, product_name="blue hat"),
        ]
        reranked = r.rerank(results, query_text="shoes for sale")

        r1 = next(rr for rr in reranked if rr.product_id == 1)
        r2 = next(rr for rr in reranked if rr.product_id == 2)
        assert r1.score > r2.score

    def test_rerank_with_location_boost(self):
        r = Reranker()
        results = [
            _make_search_result(1, score=0.8, merchant_lat=0.3140, merchant_lng=32.5820),
            _make_search_result(2, score=0.8, merchant_lat=1.0, merchant_lng=33.0),
        ]
        reranked = r.rerank(results, query_location=(0.3136, 32.5811))

        r1 = next(rr for rr in reranked if rr.product_id == 1)
        r2 = next(rr for rr in reranked if rr.product_id == 2)
        assert r1.score > r2.score

    def test_rerank_with_price_boost(self):
        r = Reranker()
        results = [
            _make_search_result(1, score=0.8, price=50000),
            _make_search_result(2, score=0.8, price=200000),
        ]
        reranked = r.rerank(results, price_range=(10000, 100000))

        r1 = next(rr for rr in reranked if rr.product_id == 1)
        r2 = next(rr for rr in reranked if rr.product_id == 2)
        assert r1.score > r2.score

    def test_rerank_assigns_ranks(self):
        r = Reranker()
        results = [_make_search_result(i, score=i * 0.1) for i in range(1, 6)]
        reranked = r.rerank(results)

        ranks = sorted([rr.rank for rr in reranked])
        assert ranks == [1, 2, 3, 4, 5]

    def test_rerank_empty_results(self):
        r = Reranker()
        reranked = r.rerank([])
        assert reranked == []

    def test_rerank_single_result(self):
        r = Reranker()
        results = [_make_search_result(42, score=0.95)]
        reranked = r.rerank(results)

        assert len(reranked) == 1
        assert reranked[0].rank == 1
        assert reranked[0].match_label == "Related"
