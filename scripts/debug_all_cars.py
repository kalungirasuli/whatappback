"""Top-3 for every car image, to gauge ranking sensitivity."""
import asyncio

from src.workers.search_pipeline import SearchPipeline

IMAGES = {
    "ad.jpg (Car1?)": r"C:\Users\CONRAD\Downloads\images mocks\cars\ad.jpg",
    "bb.jpg": r"C:\Users\CONRAD\Downloads\images mocks\cars\bb.jpg",
    "ct.jpg": r"C:\Users\CONRAD\Downloads\images mocks\cars\ct.jpg",
    "r2r.jpg (Car4)": r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg",
    "rr.jpg (Car5?)": r"C:\Users\CONRAD\Downloads\images mocks\cars\rr.jpg",
    "test car.jpg": r"C:\Users\CONRAD\Downloads\images mocks\test car\test car.jpg",
}


async def main() -> None:
    p = SearchPipeline()
    for label, path in IMAGES.items():
        data = open(path, "rb").read()
        results = await p.search_by_image(image_bytes=data)
        top = " | ".join(f"{r.metadata.get('product_name')}({r.product_id}):{r.score:.3f}" for r in results[:3])
        print(f"{label}: {top}")


if __name__ == "__main__":
    asyncio.run(main())
