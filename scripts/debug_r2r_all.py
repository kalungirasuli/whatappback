"""Show full result list for r2r image search to check category mixing."""
import asyncio

from src.workers.search_pipeline import SearchPipeline


async def main() -> None:
    p = SearchPipeline()
    path = r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg"
    data = open(path, "rb").read()
    results = await p.search_by_image(image_bytes=data)
    print("=== r2r.jpg all results ===")
    for r in results:
        cat = r.metadata.get("category")
        name = r.metadata.get("product_name")
        print(f"#{r.rank} pid={r.product_id} score={r.score:.4f} cat={cat!r} name={name!r}")
    cars = [r for r in results if r.metadata.get("category") == "cars"]
    print(f"\ntotal={len(results)} cars_only={len(cars)}")


if __name__ == "__main__":
    asyncio.run(main())
