"""Sanity: accuracy fix on r2r.jpg + shoes, then a live Lisa turn."""
import asyncio

from src.workers.search_pipeline import SearchPipeline
from src.services.lisa_agent import LisaAgent


async def search(path: str, title: str) -> None:
    p = SearchPipeline()
    data = open(path, "rb").read()
    results = await p.search_by_image(image_bytes=data)
    print(f"=== {title} (top {len(results)}) ===")
    for r in results[:8]:
        print(
            f"#{r.rank} pid={r.product_id} score={r.score:.4f} {r.match_label} "
            f"name={r.metadata.get('product_name')!r} cat={r.metadata.get('category')!r}"
        )


async def lisa_demo() -> None:
    agent = LisaAgent()

    class FakeRedis:
        def __init__(self):
            self.data = {}

        async def get(self, key):
            return self.data.get(key)

        async def set(self, key, value):
            self.data[key] = value

    redis = FakeRedis()
    turn = await agent.decide(redis, 99, "yo watsup i need some cool kicks my bro's buzz", has_image=False)
    print(f"=== Lisa decide: action={turn.action}")
    print(f"reply: {turn.reply}")
    print(f"search_text: {turn.search_text!r}")

    # second turn: continuation from the demo
    await agent.record_turn(redis, 99, "yo watsup i need some cool kicks my bro's buzz", turn.reply)
    turn2 = await agent.decide(redis, 99, "and looking kick that will suite my today outlive with this ride", has_image=False)
    print(f"=== Lisa decide (turn 2): action={turn2.action}")
    print(f"reply: {turn2.reply}")
    print(f"search_text: {turn2.search_text!r}")


async def main() -> None:
    await search(r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg", "r2r.jpg (car)")
    await search(r"C:\Users\CONRAD\Downloads\images mocks\shoes\IMG_20251115_094214.jpg", "shoe 1")
    await search(r"C:\Users\CONRAD\Downloads\images mocks\iphones\i17.jpg", "iphone i17")
    await lisa_demo()


if __name__ == "__main__":
    asyncio.run(main())
