import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        VectorParams,
        PointStruct,
        Filter,
        FieldCondition,
        MatchValue,
    )

    _qdrant_available = True
except ImportError:
    _qdrant_available = False
    logger.warning("qdrant-client not installed — using in-memory mock")


@dataclass
class SearchResult:
    product_id: int
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class QdrantService:
    def __init__(self) -> None:
        self._client = None
        self._collection = settings.qdrant_collection
        self._siglip_dim = settings.siglip_dim
        self._dinov2_dim = settings.dinov2_dim
        self._text_dim = settings.text_embedding_dim
        self._siglip_weight = settings.siglip_weight
        self._dinov2_weight = settings.dinov2_weight
        # In-memory fallback storage: list of (product_id, siglip_vector, dinov2_vector, text_vector, metadata)
        self._mock_store: list[
            tuple[int, list[float], list[float], list[float], dict[str, Any]]
        ] = []

    def _get_client(self):
        if self._client is None and _qdrant_available:
            self._client = QdrantClient(url=settings.qdrant_url)
        return self._client

    async def init_collection(self) -> None:
        client = self._get_client()
        if client is None:
            logger.info("Qdrant unavailable — using in-memory mock storage")
            return

        try:
            collections = client.get_collections().collections
            names = [c.name for c in collections]
            if self._collection not in names:
                client.create_collection(
                    collection_name=self._collection,
                    vectors_config={
                        "siglip": VectorParams(
                            size=self._siglip_dim,
                            distance=Distance.COSINE,
                        ),
                        "dinov2": VectorParams(
                            size=self._dinov2_dim,
                            distance=Distance.COSINE,
                        ),
                        "text": VectorParams(
                            size=self._text_dim,
                            distance=Distance.COSINE,
                        ),
                    },
                )
                logger.info(
                    f"Created Qdrant collection '{self._collection}' "
                    f"with siglip({self._siglip_dim}) + dinov2({self._dinov2_dim}) + text({self._text_dim}) named vectors"
                )
            else:
                logger.info(f"Qdrant collection already exists: {self._collection}")
        except Exception as e:
            logger.error(f"Failed to init Qdrant collection: {e}")

    async def upsert_product(
        self,
        product_id: int,
        siglip_vector: list[float],
        dinov2_vector: list[float],
        text_vector: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        client = self._get_client()
        if client is None:
            self._mock_store = [
                (pid, sv, dv, tv, meta)
                for pid, sv, dv, tv, meta in self._mock_store
                if pid != product_id
            ]
            self._mock_store.append(
                (product_id, siglip_vector, dinov2_vector, text_vector or [], metadata or {})
            )
            logger.info(f"[mock] Upserted product {product_id}")
            return

        try:
            vectors: dict[str, list[float]] = {
                "siglip": siglip_vector,
                "dinov2": dinov2_vector,
            }
            if text_vector:
                vectors["text"] = text_vector

            point = PointStruct(
                id=product_id,
                vector=vectors,
                payload=metadata or {},
            )
            client.upsert(
                collection_name=self._collection,
                points=[point],
                wait=True,
            )
            logger.info(f"Upserted product {product_id} to Qdrant with siglip + dinov2 + text vectors")
        except Exception as e:
            logger.error(f"Failed to upsert product {product_id}: {e}")

    async def search_similar(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        vector_name: str = "siglip",
    ) -> list[SearchResult]:
        client = self._get_client()
        if client is None:
            return self._mock_search(query_vector, top_k, filters, vector_name)

        try:
            query_filter = None
            if filters:
                conditions = []
                for key, value in filters.items():
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )
                if conditions:
                    query_filter = Filter(must=conditions)

            results = client.query_points(
                collection_name=self._collection,
                query=query_vector,
                using=vector_name,
                limit=top_k,
                query_filter=query_filter,
            )

            search_results: list[SearchResult] = []
            for hit in results.points:
                metadata = dict(hit.payload) if hit.payload else {}
                search_results.append(
                    SearchResult(
                        product_id=hit.id,
                        score=hit.score,
                        metadata=metadata,
                    )
                )
            return search_results
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []

    async def hybrid_search(
        self,
        siglip_vector: list[float],
        dinov2_vector: list[float],
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        siglip_results = await self.search_similar(siglip_vector, top_k, filters, "siglip")
        dinov2_results = await self.search_similar(dinov2_vector, top_k, filters, "dinov2")

        combined: dict[int, dict[str, Any]] = {}
        for r in siglip_results:
            combined[r.product_id] = {
                "siglip_score": r.score,
                "dinov2_score": 0.0,
                "metadata": r.metadata,
            }
        for r in dinov2_results:
            if r.product_id in combined:
                combined[r.product_id]["dinov2_score"] = r.score
            else:
                combined[r.product_id] = {
                    "siglip_score": 0.0,
                    "dinov2_score": r.score,
                    "metadata": r.metadata,
                }

        hybrid: list[SearchResult] = []
        for pid, scores in combined.items():
            hybrid_score = (
                self._siglip_weight * scores["siglip_score"]
                + self._dinov2_weight * scores["dinov2_score"]
            )
            hybrid.append(
                SearchResult(
                    product_id=pid,
                    score=hybrid_score,
                    metadata=scores["metadata"],
                )
            )

        hybrid.sort(key=lambda r: r.score, reverse=True)
        return hybrid[:top_k]

    def _mock_search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None,
        vector_name: str = "siglip",
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for pid, sv, dv, tv, meta in self._mock_store:
            if filters:
                match = True
                for key, value in filters.items():
                    if meta.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            if vector_name == "siglip":
                vec = sv
            elif vector_name == "dinov2":
                vec = dv
            elif vector_name == "text":
                vec = tv
            else:
                vec = sv

            dot = sum(a * b for a, b in zip(query_vector, vec))
            norm_a = sum(a * a for a in query_vector) ** 0.5
            norm_b = sum(b * b for b in vec) ** 0.5
            score = dot / (norm_a * norm_b) if (norm_a and norm_b) else 0.0

            results.append(
                SearchResult(
                    product_id=pid,
                    score=score,
                    metadata={k: v for k, v in meta.items()},
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def update_metadata(
        self,
        product_id: int,
        metadata: dict[str, Any],
    ) -> bool:
        """Update payload metadata for an existing product without changing vectors."""
        client = self._get_client()
        if client is None:
            for i, (pid, sv, dv, tv, meta) in enumerate(self._mock_store):
                if pid == product_id:
                    merged = {**meta, **metadata}
                    self._mock_store[i] = (pid, sv, dv, tv, merged)
                    logger.info(f"[mock] Updated metadata for product {product_id}")
                    return True
            logger.warning(f"[mock] Product {product_id} not found for metadata update")
            return False

        try:
            points = client.retrieve(
                collection_name=self._collection,
                ids=[product_id],
                with_vectors=True,
            )
            if not points:
                logger.warning(f"Product {product_id} not found in Qdrant for metadata update")
                return False

            point = points[0]
            new_payload = dict(point.payload) if point.payload else {}
            new_payload.update(metadata)
            client.upsert(
                collection_name=self._collection,
                points=[PointStruct(
                    id=product_id,
                    vector=point.vector,
                    payload=new_payload,
                )],
            )
            logger.info(f"Updated metadata for product {product_id} in Qdrant")
            return True
        except Exception as e:
            logger.error(f"Failed to update metadata for product {product_id}: {e}")
            return False

    async def delete_product(self, product_id: int) -> None:
        client = self._get_client()
        if client is None:
            self._mock_store = [
                (pid, sv, dv, tv, meta)
                for pid, sv, dv, tv, meta in self._mock_store
                if pid != product_id
            ]
            logger.info(f"[mock] Deleted product {product_id}")
            return

        try:
            client.delete(
                collection_name=self._collection,
                points_selector=[product_id],
            )
            logger.info(f"Deleted product {product_id} from Qdrant")
        except Exception as e:
            logger.error(f"Failed to delete product {product_id}: {e}")

    async def delete_merchant_products(self, merchant_id: int) -> None:
        client = self._get_client()
        if client is None:
            self._mock_store = [
                (pid, sv, dv, tv, meta)
                for pid, sv, dv, tv, meta in self._mock_store
                if meta.get("merchant_id") != merchant_id
            ]
            logger.info(f"[mock] Deleted all products for merchant {merchant_id}")
            return

        try:
            client.delete(
                collection_name=self._collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="merchant_id",
                            match=MatchValue(value=merchant_id),
                        )
                    ]
                ),
            )
            logger.info(f"Deleted all products for merchant {merchant_id}")
        except Exception as e:
            logger.error(f"Failed to delete products for merchant {merchant_id}: {e}")
