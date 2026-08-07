import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.services.qdrant_service import SearchResult
from src.services.reranker import RerankedResult
from src.workers.search_pipeline import SearchPipeline, apply_consistency_filter


def _make_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_search_result(pid: int, score: float = 0.8) -> SearchResult:
    return SearchResult(product_id=pid, score=score, metadata={"product_name": f"Product {pid}"})


def _make_reranked(pid: int, rank: int = 1) -> RerankedResult:
    return RerankedResult(product_id=pid, score=0.8, rank=rank, match_label="Closest match")


def _make_category_result(pid: int, category: str, score: float) -> RerankedResult:
    return RerankedResult(
        product_id=pid,
        score=score,
        rank=0,
        match_label="Match",
        metadata={"product_name": f"Product {pid}", "category": category},
    )


class TestSearchByImage:
    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    @patch("src.workers.search_pipeline._detector")
    async def test_search_by_image_returns_results(self, mock_det, mock_emb, mock_qdr, mock_rer):
        mock_det.detect_and_crop = AsyncMock(return_value=[
            MagicMock(image_bytes=b"cropped", label="car", confidence=0.85)
        ])
        mock_emb.embed_image = AsyncMock(return_value=[0.1] * 768)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.1] * 768)
        mock_qdr.hybrid_search = AsyncMock(return_value=[_make_search_result(1)])
        mock_rer.rerank = MagicMock(return_value=[_make_reranked(1)])

        pipeline = SearchPipeline()
        results = await pipeline.search_by_image(image_bytes=_make_image_bytes())

        assert len(results) == 1
        assert results[0].product_id == 1

    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    @patch("src.workers.search_pipeline._detector")
    async def test_search_by_image_empty_crops_uses_original(self, mock_det, mock_emb, mock_qdr, mock_rer):
        mock_det.detect_and_crop = AsyncMock(return_value=[])
        mock_emb.embed_image = AsyncMock(return_value=[0.1] * 768)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.1] * 768)
        mock_qdr.hybrid_search = AsyncMock(return_value=[])
        mock_rer.rerank = MagicMock(return_value=[])

        pipeline = SearchPipeline()
        await pipeline.search_by_image(image_bytes=_make_image_bytes())

        mock_emb.embed_image.assert_awaited_once_with(_make_image_bytes())

    async def test_search_by_image_none_returns_empty(self):
        pipeline = SearchPipeline()
        results = await pipeline.search_by_image(image_bytes=None)
        assert results == []

    async def test_search_by_image_empty_returns_empty(self):
        pipeline = SearchPipeline()
        results = await pipeline.search_by_image(image_bytes=b"")
        assert results == []

    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    @patch("src.workers.search_pipeline._detector")
    async def test_search_by_image_passes_location_to_reranker(self, mock_det, mock_emb, mock_qdr, mock_rer):
        mock_det.detect_and_crop = AsyncMock(return_value=[MagicMock(image_bytes=b"crop")])
        mock_emb.embed_image = AsyncMock(return_value=[0.0] * 768)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.hybrid_search = AsyncMock(return_value=[])
        mock_rer.rerank = MagicMock(return_value=[])

        location = (0.3136, 32.5811)
        pipeline = SearchPipeline()
        await pipeline.search_by_image(image_bytes=_make_image_bytes(), buyer_location=location)

        mock_rer.rerank.assert_called_once()
        call_kwargs = mock_rer.rerank.call_args
        assert call_kwargs.kwargs["query_location"] == location

    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    @patch("src.workers.search_pipeline._detector")
    async def test_search_by_image_passes_price_range(self, mock_det, mock_emb, mock_qdr, mock_rer):
        mock_det.detect_and_crop = AsyncMock(return_value=[MagicMock(image_bytes=b"crop")])
        mock_emb.embed_image = AsyncMock(return_value=[0.0] * 768)
        mock_emb.embed_image_dinov2 = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.hybrid_search = AsyncMock(return_value=[])
        mock_rer.rerank = MagicMock(return_value=[])

        price_range = (10000, 100000)
        pipeline = SearchPipeline()
        await pipeline.search_by_image(image_bytes=_make_image_bytes(), price_range=price_range)

        call_kwargs = mock_rer.rerank.call_args
        assert call_kwargs.kwargs["price_range"] == price_range


class TestSearchByText:
    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    async def test_search_by_text_returns_results(self, mock_emb, mock_qdr, mock_rer):
        mock_emb.embed_text = AsyncMock(return_value=[0.1] * 768)
        mock_qdr.search_similar = AsyncMock(return_value=[_make_search_result(1), _make_search_result(2)])
        mock_rer.rerank = MagicMock(return_value=[_make_reranked(1), _make_reranked(2, rank=2)])

        pipeline = SearchPipeline()
        results = await pipeline.search_by_text("red shoes")

        assert len(results) == 2

    async def test_search_by_text_empty_string(self):
        pipeline = SearchPipeline()
        results = await pipeline.search_by_text("")
        assert results == []

    async def test_search_by_text_whitespace_only(self):
        pipeline = SearchPipeline()
        results = await pipeline.search_by_text("   ")
        assert results == []

    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    async def test_search_by_text_passes_text_to_reranker(self, mock_emb, mock_qdr, mock_rer):
        mock_emb.embed_text = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.search_similar = AsyncMock(return_value=[])
        mock_rer.rerank = MagicMock(return_value=[])

        pipeline = SearchPipeline()
        await pipeline.search_by_text("laptop under 500000")

        call_kwargs = mock_rer.rerank.call_args
        assert call_kwargs.kwargs["query_text"] == "laptop under 500000"

    @patch("src.workers.search_pipeline._reranker")
    @patch("src.workers.search_pipeline._qdrant")
    @patch("src.workers.search_pipeline._embedding")
    async def test_search_by_text_calls_qdrant_top_k_50(self, mock_emb, mock_qdr, mock_rer):
        mock_emb.embed_text = AsyncMock(return_value=[0.0] * 768)
        mock_qdr.search_similar = AsyncMock(return_value=[])
        mock_rer.rerank = MagicMock(return_value=[])

        pipeline = SearchPipeline()
        await pipeline.search_by_text("test")

        call_kwargs = mock_qdr.search_similar.call_args
        assert call_kwargs.kwargs["top_k"] == 50


class TestFormatReply:
    async def test_format_reply_empty_results(self):
        pipeline = SearchPipeline()
        reply = await pipeline.format_reply([])
        assert reply == ""

    async def test_format_reply_with_results(self):
        results = [
            RerankedResult(
                product_id=1, score=0.9, rank=1, match_label="Closest match",
                metadata={"product_name": "Red Shoes", "price": 50000, "merchant_name": "John"},
            )
        ]
        pipeline = SearchPipeline()
        reply = await pipeline.format_reply(results)

        assert "Red Shoes" in reply
        assert "50,000 UGX" in reply
        assert "John" in reply

    async def test_format_reply_plural(self):
        results = [
            RerankedResult(product_id=1, score=0.9, rank=1, match_label="Closest match"),
            RerankedResult(product_id=2, score=0.8, rank=2, match_label="Similar style"),
        ]
        pipeline = SearchPipeline()
        reply = await pipeline.format_reply(results)

        assert "Product #1" in reply
        assert "Product #2" in reply

    async def test_format_reply_truncation(self):
        results = [
            RerankedResult(product_id=i, score=0.9, rank=i, match_label="Match")
            for i in range(1, 8)
        ]
        pipeline = SearchPipeline()
        reply = await pipeline.format_reply(results, max_results=5)

        assert len(reply.split("Product #")) == 6  # 5 results + 1 for the split

    async def test_format_reply_no_metadata_fallback_name(self):
        results = [
            RerankedResult(product_id=42, score=0.9, rank=1, match_label="Closest match")
        ]
        pipeline = SearchPipeline()
        reply = await pipeline.format_reply(results)

        assert "Product #42" in reply


class TestConsistencyFilter:
    def test_empty_results_passthrough(self):
        assert apply_consistency_filter([]) == []

    def test_unknown_family_keeps_all(self):
        results = [_make_reranked(1), _make_reranked(2, rank=2)]
        filtered = apply_consistency_filter(results)
        assert [r.product_id for r in filtered] == [1, 2]

    def test_drops_cross_category_pollution(self):
        """A car-anchored result list must never show phones or shoes."""
        results = [
            _make_category_result(1, "Cars", 0.60),
            _make_category_result(2, "Cars", 0.41),
            _make_category_result(3, "Cars", 0.34),
            _make_category_result(4, "Phones", 0.21),
            _make_category_result(5, "Shoes", 0.16),
        ]
        filtered = apply_consistency_filter(results)
        assert [r.product_id for r in filtered] == [1, 2, 3]

    def test_preferred_family_wins(self):
        """The detector's family overrides the top result's category."""
        results = [
            _make_category_result(1, "Cars", 0.60),
            _make_category_result(2, "Cars", 0.41),
            _make_category_result(3, "Phones", 0.39),
        ]
        filtered = apply_consistency_filter(results, preferred_family="vehicles")
        assert [r.product_id for r in filtered] == [1, 2]

    def test_score_band_drops_stragglers(self):
        results = [
            _make_category_result(1, "Cars", 0.60),
            _make_category_result(2, "Cars", 0.20),
            _make_category_result(3, "Cars", 0.10),
        ]
        filtered = apply_consistency_filter(results)
        assert [r.product_id for r in filtered] == [1]

    def test_filter_never_empties_list(self):
        """If every result would be dropped, the original list is preserved."""
        results = [_make_reranked(1)]
        filtered = apply_consistency_filter(results, preferred_family="vehicles")
        assert [r.product_id for r in filtered] == [1]

    def test_ranks_are_recomputed(self):
        results = [
            _make_category_result(10, "Cars", 0.6),
            _make_category_result(11, "Phones", 0.4),
            _make_category_result(12, "Cars", 0.3),
        ]
        filtered = apply_consistency_filter(results)
        assert [r.rank for r in filtered] == [1, 2]
