import asyncio
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService
from src.services.reranker import Reranker


async def debug():
    embedding = EmbeddingService()
    qdrant = QdrantService()
    await qdrant.init_collection()

    query = "laptop"
    vec = await embedding.embed_text(query)
    print(f"Query: '{query}' dim={len(vec)}")

    results = await qdrant.search_similar(vec, top_k=10, vector_name="siglip")
    print(f"Raw Qdrant results: {len(results)}")
    for r in results:
        print(f"  {r.product_id}: score={r.score:.4f} meta={r.metadata}")

    reranked = Reranker().rerank(results=results, query_text=query)
    print(f"Reranked results: {len(reranked)}")
    for r in reranked:
        print(f"  {r.product_id}: score={r.score:.4f} kept={r.is_kept}")


asyncio.run(debug())
