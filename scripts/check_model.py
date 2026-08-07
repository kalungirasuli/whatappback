"""Verify configured embedding models load and sanity-check discrimination.

Usage:
    python scripts/check_model.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.embedding import EmbeddingService
from src.core.config import settings

IMAGES = [
    r"C:\Users\CONRAD\Downloads\images mocks\cars\r2r.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\cars\rr.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\iphones\i17.jpg",
    r"C:\Users\CONRAD\Downloads\images mocks\shoes\IMG_20251115_094214.jpg",
]


def cos(a, b) -> float:
    n = (sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5)
    return sum(x * y for x, y in zip(a, b)) / n if n else 0.0


def main() -> int:
    emb = EmbeddingService()
    print(f"SigLIP : {emb._siglip_model_name} (dim {emb._siglip_dim})")
    print(f"DINOv2 : {emb._dinov2_model_name} (dim {emb._dinov2_dim})")
    print(f"Text   : {emb._text_model_name} (dim {emb._text_dim})")

    vecs = {}
    for path in IMAGES:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        vecs[name] = emb.embed_image_sync(data)
        print(f"  embedded {name}: dim={len(vecs[name])}")

    s = vecs["r2r.jpg"]
    pairs = [
        ("r2r.jpg  vs rr.jpg   (both cars) ", s, vecs["rr.jpg"]),
        ("r2r.jpg  vs i17.jpg  (car vs phone)", s, vecs["i17.jpg"]),
        ("r2r.jpg  vs shoe     (car vs shoe) ", s, vecs["IMG_20251115_094214.jpg"]),
    ]
    for label, a, b in pairs:
        print(f"  {label}: cos={cos(a, b):.4f}")

    related = cos(vecs["r2r.jpg"], vecs["rr.jpg"])
    unrelated = cos(vecs["r2r.jpg"], vecs["i17.jpg"])
    print(f"\nrelated({related:.4f}) vs unrelated({unrelated:.4f}) -> "
          f"{'OK' if related > unrelated else 'SUSPICIOUS'}")
    return 0 if related > unrelated else 1


if __name__ == "__main__":
    sys.exit(main())
