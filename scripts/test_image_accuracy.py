"""Test image-search accuracy via the real /api/chat endpoint.

For every mock image: post it (optionally with a caption) as the test client,
find the visual-search section in the reply, and check that the #1 result is
the EXACT product whose photo was uploaded (exact-image match).

Usage:
    python scripts/test_image_accuracy.py                  # image only
    python scripts/test_image_accuracy.py --caption "find this"
    python scripts/test_image_accuracy.py --token <TOKEN>
"""
import argparse
import json
import os
import re
import sys

import requests

from chat_tester import get_otp_from_log

API = "http://127.0.0.1:8002"
PHONE = "+256700000001"
MOCKS_DIR = r"C:\Users\CONRAD\Downloads\images mocks"
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "mock_inventory_manifest.json")


def login() -> str:
    r = requests.post(f"{API}/api/auth/request-otp", json={"phone": PHONE}, timeout=30)
    code = get_otp_from_log()
    if not code:
        raise RuntimeError("could not find OTP in API log")
    r = requests.post(
        f"{API}/api/auth/verify-otp",
        json={"phone": PHONE, "code": code, "role": "client"},
        timeout=30,
    )
    return r.json()["access_token"]


def find_visual_section(response: dict) -> list[dict] | None:
    for section in response.get("sections", []):
        if section.get("label", "").lower().startswith("i see"):
            return section.get("results", [])
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caption", default="", help="caption to add with the image")
    ap.add_argument("--token", help="reuse an access token")
    args = ap.parse_args()

    manifest = json.load(open(MANIFEST_PATH))
    reverse = {str(pid): img for img, pid in manifest.items()}
    token = args.token or login()
    headers = {"Authorization": f"Bearer {token}"}

    results = []
    for img_file in sorted(manifest):
        pid = manifest[img_file]
        for folder in ("cars", "iphones", "shoes"):
            path = os.path.join(MOCKS_DIR, folder, img_file)
            if os.path.exists(path):
                break
        else:
            print(f"SKIP {img_file}: not found in any folder")
            continue

        with open(path, "rb") as f:
            r = requests.post(
                f"{API}/api/chat",
                headers=headers,
                data={"text": args.caption},
                files={"files": (img_file, f, "image/jpeg")},
                timeout=300,
            )
        if r.status_code != 200:
            print(f"FAIL {img_file}: HTTP {r.status_code} {r.text[:200]}")
            results.append((img_file, pid, None, None))
            continue

        body = r.json()
        visual = find_visual_section(body)
        if not visual:
            print(f"FAIL {img_file}: no visual section in reply")
            results.append((img_file, pid, None, None))
            continue

        top = visual[0]
        top_pid = top["product_id"]
        top_score = top.get("score")
        ok = top_pid == pid
        match = "PASS" if ok else "FAIL"
        top_name = reverse.get(str(top_pid), f"product {top_pid}")
        print(f"{match} {img_file}: expected #{pid}, got #{top_pid} ({top['name']}) score={top_score} {'<-- WRONG, expected '+reverse.get(str(pid),'?') if not ok else ''}")
        results.append((img_file, pid, top_pid, ok))

    total = len(results)
    passes = sum(1 for *_, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"EXACT-MATCH ACCURACY: {passes}/{total} = {100.0*passes/total:.1f}%")
    if args.caption:
        print(f"(caption: '{args.caption}')")


if __name__ == "__main__":
    main()
