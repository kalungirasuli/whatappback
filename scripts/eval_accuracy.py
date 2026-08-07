"""Evaluate image-search accuracy against a labeled eval set.

Metrics:
  - Top-1 exact: expected product id is rank 1 (kind=exact)
  - Top-3 exact: expected product id appears in the first 3 (kind=exact)
  - Family hit: top-1 result belongs to the expected family (all cases)

Usage:
    python scripts/eval_accuracy.py                    # run + print
    python scripts/eval_accuracy.py --baseline         # run and save baseline
    python scripts/eval_accuracy.py --compare          # diff against saved baseline
    python scripts/eval_accuracy.py --min-top1 80      # fail if top-1 % is below this
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workers.search_pipeline import SearchPipeline
from src.services.categories import family_for_category

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_PATH = os.path.join(HERE, "eval", "eval_set.json")
BASELINE_PATH = os.path.join(HERE, "eval", "baseline.json")


def load_cases() -> list[dict]:
    with open(EVAL_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_search(pipeline: SearchPipeline, image_path: str) -> list:
    async def _run():
        with open(image_path, "rb") as f:
            data = f.read()
        return await pipeline.search_by_image(image_bytes=data)

    return asyncio.run(_run())


def family_of(result) -> str | None:
    if result is None:
        return None
    return family_for_category(result.metadata.get("category"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", action="store_true", help="save results as the new baseline")
    ap.add_argument("--compare", action="store_true", help="diff against saved baseline")
    ap.add_argument("--min-top1", type=float, default=80.0, help="minimum top-1 exact %% (exit 1 below)")
    args = ap.parse_args()

    cases = load_cases()
    pipeline = SearchPipeline()

    rows = []
    stats = {"exact": 0, "exact_top3": 0, "family": 0, "total": len(cases)}

    print(f"{'CASE':<46} {'KIND':<7} {'RESULT':<7} {'FAMILY':<11} TOP3  DETAIL")
    print("-" * 120)

    for case in cases:
        name = os.path.basename(case["image"])
        results = run_search(pipeline, case["image"])
        top = results[0] if results else None
        top_family = family_of(top)

        expected = set(case.get("expected_product_ids") or [])
        expected_family = case.get("expected_family")

        if case["kind"] == "exact" and expected:
            ok1 = top is not None and top.product_id in expected
            ok3 = any(r.product_id in expected for r in results[:3])
            family_ok = expected_family is None or top_family == expected_family
            stats["exact"] += int(ok1)
            stats["exact_top3"] += int(ok3)
            stats["family"] += int(family_ok)
        else:
            ok1 = top_family == expected_family
            ok3 = ok1
            family_ok = ok1
            stats["family"] += int(family_ok)

        verdict = "PASS" if (ok1 and family_ok) else "FAIL"
        top_name = top.metadata.get("product_name") if top else "-"
        top3_ids = [r.product_id for r in results[:3]]
        print(
            f"{name:<46} {case['kind']:<7} {verdict:<7} "
            f"{(top_family or '?')!s:<11} {ok3!s:<5} "
            f"#{top.product_id if top else '?'} {top_name} top3={top3_ids}"
        )

    total = stats["total"]
    top1_rate = 100.0 * stats["exact"] / total
    top3_rate = 100.0 * stats["exact_top3"] / total
    family_rate = 100.0 * stats["family"] / total

    print("=" * 120)
    print(f"Top-1 exact match: {stats['exact']}/{total} = {top1_rate:.1f}%")
    print(f"Top-3 exact match: {stats['exact_top3']}/{total} = {top3_rate:.1f}%")
    print(f"Family hit:       {stats['family']}/{total} = {family_rate:.1f}%")

    if args.baseline:
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        print(f"Baseline saved to {BASELINE_PATH}")

    if args.compare and os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding="utf-8") as f:
            base = json.load(f)
        print("-" * 120)
        print("vs baseline:")
        print(f"  top-1 exact: {top1_rate:.1f}% (was {100.0*base['exact']/base['total']:.1f}%)")
        print(f"  top-3 exact: {top3_rate:.1f}% (was {100.0*base['exact_top3']/base['total']:.1f}%)")
        print(f"  family hit:  {family_rate:.1f}% (was {100.0*base['family']/base['total']:.1f}%)")

    return 1 if top1_rate < args.min_top1 else 0


if __name__ == "__main__":
    sys.exit(main())
