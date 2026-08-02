"""Print only the top-3 for the r2r car image."""
import asyncio

from src.workers.search_pipeline import SearchPipeline


async def main() -> None:
    p = SearchPipeline()
    path = r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg"
    data = open(path, "rb").read()
    results = await p.search_by_image(image_bytes=data)
    print("=== r2r.jpg top-3 ===")
    for r in results[:3]:
        print(
            f"#{r.rank} pid={r.product_id} score={r.score:.4f} {r.match_label} "
            f"name={r.metadata.get('product_name')!r} cat={r.metadata.get('category')!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
