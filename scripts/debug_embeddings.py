import asyncio
import numpy as np
from src.services.embedding import EmbeddingService


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


async def main():
    emb = EmbeddingService()
    products = [
        "Dell Laptop XPS Dell electronics",
        "Samsung Galaxy S24 Samsung electronics",
        "Nike Air Max Nike shoes",
    ]
    pvecs = [await emb.embed_text(p) for p in products]
    print("Product vectors computed")

    queries = [
        "laptop",
        "I want to buy a laptop",
        "electronics",
        "shoes",
        "samsung galaxy phone",
        "sneakers",
    ]
    for q in queries:
        qv = await emb.embed_text(q)
        scores = [(cos(qv, pv), name) for name, pv in zip(products, pvecs)]
        scores.sort(reverse=True)
        print(f"\nQuery: '{q}'")
        for s, name in scores:
            print(f"  {s:.4f}  {name}")


asyncio.run(main())
