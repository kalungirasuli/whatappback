from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.services.qdrant_service import QdrantService, SearchResult


@pytest.fixture(autouse=True)
def _patch_qdrant_unavailable():
    """Force in-memory fallback for all mock-store tests."""
    with patch("src.services.qdrant_service._qdrant_available", False):
        yield


def _fake_vector(dim: int = 512) -> list[float]:
    import random
    random.seed(42)
    vec = [random.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


def _fake_vector_b(dim: int = 512) -> list[float]:
    import random
    random.seed(99)
    vec = [random.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


class TestMockUpsertAndSearch:
    async def test_upsert_stores_product(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(
            product_id=1,
            siglip_vector=vec,
            dinov2_vector=vec,
            metadata={"product_name": "Shirt", "price": 50000},
        )
        assert len(svc._mock_store) == 1
        pid, siglip_vec, dinov2_vec, text_vec, meta = svc._mock_store[0]
        assert pid == 1
        assert meta["product_name"] == "Shirt"
        assert meta["price"] == 50000

    async def test_upsert_replaces_existing(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"v": 1})
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"v": 2})
        assert len(svc._mock_store) == 1
        _, _, _, _, meta = svc._mock_store[0]
        assert meta["v"] == 2

    async def test_search_similar_returns_results(self):
        svc = QdrantService()
        vec_a = _fake_vector()
        vec_b = _fake_vector_b()
        await svc.upsert_product(product_id=1, siglip_vector=vec_a, dinov2_vector=vec_a, metadata={"name": "A"})
        await svc.upsert_product(product_id=2, siglip_vector=vec_b, dinov2_vector=vec_b, metadata={"name": "B"})

        results = await svc.search_similar(query_vector=vec_a, top_k=10)
        assert len(results) == 2
        assert results[0].product_id == 1
        assert results[0].score > results[1].score

    async def test_search_top_k_limits_results(self):
        svc = QdrantService()
        vec = _fake_vector()
        for i in range(5):
            await svc.upsert_product(product_id=i, siglip_vector=vec, dinov2_vector=vec, metadata={})

        results = await svc.search_similar(query_vector=vec, top_k=3)
        assert len(results) == 3

    async def test_search_with_filters(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"category": "shoes"})
        await svc.upsert_product(product_id=2, siglip_vector=vec, dinov2_vector=vec, metadata={"category": "hats"})

        results = await svc.search_similar(query_vector=vec, top_k=10, filters={"category": "shoes"})
        assert len(results) == 1
        assert results[0].product_id == 1

    async def test_search_no_match_filter(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"category": "shoes"})

        results = await svc.search_similar(query_vector=vec, top_k=10, filters={"category": "gold"})
        assert len(results) == 0

    async def test_delete_product(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={})
        await svc.upsert_product(product_id=2, siglip_vector=vec, dinov2_vector=vec, metadata={})

        await svc.delete_product(1)
        assert len(svc._mock_store) == 1
        assert svc._mock_store[0][0] == 2

    async def test_delete_nonexistent_product(self):
        svc = QdrantService()
        await svc.delete_product(999)
        assert len(svc._mock_store) == 0

    async def test_delete_merchant_products(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"merchant_id": 10})
        await svc.upsert_product(product_id=2, siglip_vector=vec, dinov2_vector=vec, metadata={"merchant_id": 20})
        await svc.upsert_product(product_id=3, siglip_vector=vec, dinov2_vector=vec, metadata={"merchant_id": 10})

        await svc.delete_merchant_products(10)
        assert len(svc._mock_store) == 1
        assert svc._mock_store[0][0] == 2

    async def test_delete_merchant_products_none_match(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"merchant_id": 5})
        await svc.delete_merchant_products(999)
        assert len(svc._mock_store) == 1

    async def test_init_collection_no_client(self):
        svc = QdrantService()
        await svc.init_collection()
        assert svc._mock_store == []


class TestMockCosineSimilarity:
    async def test_identical_vector_high_score(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={})

        results = await svc.search_similar(query_vector=vec, top_k=1)
        assert len(results) == 1
        assert results[0].score > 0.99

    async def test_orthogonal_vectors_low_score(self):
        svc = QdrantService()
        vec_a = [1.0] + [0.0] * 511
        vec_b = [0.0, 1.0] + [0.0] * 510
        await svc.upsert_product(product_id=1, siglip_vector=vec_a, dinov2_vector=vec_a, metadata={})

        results = await svc.search_similar(query_vector=vec_b, top_k=1)
        assert len(results) == 1
        assert abs(results[0].score) < 0.01

    async def test_search_result_metadata_excludes_dinov2(self):
        svc = QdrantService()
        vec = _fake_vector()
        await svc.upsert_product(
            product_id=1,
            siglip_vector=vec,
            dinov2_vector=vec,
            metadata={"product_name": "Test"},
        )

        results = await svc.search_similar(query_vector=vec, top_k=1)
        assert "dinov2_vector" not in results[0].metadata


class TestMockEmptyStore:
    async def test_search_empty_store(self):
        svc = QdrantService()
        results = await svc.search_similar(query_vector=_fake_vector(), top_k=10)
        assert results == []

    async def test_delete_from_empty_store(self):
        svc = QdrantService()
        await svc.delete_product(1)
        assert svc._mock_store == []


class TestQdrantClientMocked:
    @patch("src.services.qdrant_service._qdrant_available", True)
    @patch("src.services.qdrant_service.QdrantClient")
    async def test_init_collection_creates(self, mock_cls):
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        mock_cls.return_value = mock_client

        svc = QdrantService()
        svc._client = mock_client

        await svc.init_collection()
        mock_client.create_collection.assert_called_once()

    @patch("src.services.qdrant_service._qdrant_available", True)
    async def test_upsert_product_calls_client(self):
        mock_client = MagicMock()
        svc = QdrantService()
        svc._client = mock_client
        vec = _fake_vector()

        await svc.upsert_product(product_id=1, siglip_vector=vec, dinov2_vector=vec, metadata={"k": "v"})
        mock_client.upsert.assert_called_once()

    @patch("src.services.qdrant_service._qdrant_available", True)
    async def test_delete_product_calls_client(self):
        mock_client = MagicMock()
        svc = QdrantService()
        svc._client = mock_client

        await svc.delete_product(1)
        mock_client.delete.assert_called_once()

    @patch("src.services.qdrant_service._qdrant_available", True)
    async def test_delete_merchant_products_calls_client(self):
        mock_client = MagicMock()
        svc = QdrantService()
        svc._client = mock_client

        await svc.delete_merchant_products(10)
        mock_client.delete.assert_called_once()

    @patch("src.services.qdrant_service._qdrant_available", True)
    async def test_search_similar_calls_client(self):
        mock_client = MagicMock()
        mock_client.query_points.return_value = MagicMock(points=[])
        svc = QdrantService()
        svc._client = mock_client

        await svc.search_similar(query_vector=_fake_vector(), top_k=5)
        mock_client.query_points.assert_called_once()

    @patch("src.services.qdrant_service._qdrant_available", True)
    async def test_search_client_exception_returns_empty(self):
        mock_client = MagicMock()
        mock_client.query_points.side_effect = Exception("connection refused")
        svc = QdrantService()
        svc._client = mock_client

        results = await svc.search_similar(query_vector=_fake_vector(), top_k=5)
        assert results == []
