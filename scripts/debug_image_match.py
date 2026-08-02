"""Debug image search accuracy for specific test images."""
import asyncio

from src.workers.search_pipeline import SearchPipeline


IMAGES = [
    r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\test car\test car.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\shoes\IMG_20251115_094214.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\shoes\IMG_20251117_091441.jpg",
]


async def main() -> None:
    p = SearchPipeline()
    for path in IMAGES:
        data = open(path, "rb").read()
        results = await p.search_by_image(image_bytes=data)
        print(f"=== {path.split(chr(92))[-1]} ===")
        for r in results[:6]:
            print(
                f"  #{r.rank} pid={r.product_id} score={r.score:.4f} {r.match_label} "
                f"name={r.metadata.get('product_name')!r} cat={r.metadata.get('category')!r}"
            )
        print()


if __name__ == "__main__":
    asyncio.run(main())
