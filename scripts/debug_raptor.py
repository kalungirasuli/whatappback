"""Diagnose raptor1.jpg: size, YOLO detections, raw (unfiltered) embedding matches,
and what products are actually in the index."""
import asyncio

from PIL import Image
from src.services.detector import ObjectDetector
from src.services.embedding import EmbeddingService
from src.services.qdrant_service import QdrantService
from src.services.reranker import Reranker

RAPTOR = r"C:\Users\CONRAD\Downloads\images mocks\test car\raptor1.jpg"
TESTCAR = r"C:\Users\CONRAD\Downloads\images mocks\test car\test car.jpg"


async def diagnose(path: str, title: str) -> None:
    data = open(path, "rb").read()
    img = Image.open(path)
    print(f"\n=== {title} size={img.size} format={img.format} bytes={len(data)} ===")

    det = ObjectDetector()
    crops = det.detect_and_crop_sync(data)
    for c in crops:
        print(f"  detect: label={c.label!r} conf={c.confidence:.2f} bbox={c.bbox}")

    primary = crops[0].image_bytes if crops else data
    emb = EmbeddingService()
    siglip = await emb.embed_image(primary)
    dinov2 = await emb.embed_image_dinov2(primary)
    qd = QdrantService()
    hybrid = await qd.hybrid_search(siglip, dinov2, top_k=12)
    print("  raw hybrid search (top 12, pre-rerank):")
    for r in hybrid:
        print(f"    pid={r.product_id} score={r.score:.4f} name={r.metadata.get('product_name')!r} cat={r.metadata.get('category')!r}")

    reranked = Reranker().rerank(results=hybrid)
    print("  reranked (unfiltered) top 6:")
    for r in reranked[:6]:
        print(f"    #{r.rank} pid={r.product_id} score={r.score:.4f} {r.match_label} name={r.metadata.get('product_name')!r} cat={r.metadata.get('category')!r}")


async def catalog() -> None:
    qd = QdrantService()
    try:
        count = await qd.client.count(qd.collection)
        print(f"\nindexed points: {count.count}")
    except Exception as e:
        print(f"count error: {e}")
    # search by a text query to list what's there
    emb = EmbeddingService()
    v = await emb.embed_text("products")
    hits = await qd.search_similar(query_vector=v, top_k=50, vector_name="text")
    names = {}
    for h in hits:
        c = h.metadata.get("category") or "?"
        names.setdefault(c, []).append(h.metadata.get("product_name"))
    for c, ns in sorted(names.items()):
        print(f"  category={c}: {ns}")


async def main() -> None:
    await diagnose(RAPTOR, "raptor1.jpg")
    await diagnose(TESTCAR, "test car.jpg")
    await catalog()


if __name__ == "__main__":
    asyncio.run(main())
