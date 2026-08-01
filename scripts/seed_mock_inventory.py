"""Seed mock inventory: 3 merchants (cars/phones/shoes) + 13 products with real photos.

Each product's photo is uploaded via POST /api/products/{id}/images which triggers
the VisionPipeline (YOLO crop -> SigLIP + DINOv2 embeddings -> Qdrant).

Saves scripts/mock_inventory_manifest.json mapping each image file -> product id.
"""
import argparse
import json
import os
import re
import sys
import time

import requests

API = "http://127.0.0.1:8002"
LOG_DIR = "C:/Users/CONRAD/Rooms/whatAppSeller"

MOCKS_DIR = r"C:\Users\CONRAD\Downloads\images mocks"

MERCHANTS = [
    {"phone": "+256700000003", "role": "merchant", "business_name": "Prime Motors Kampala", "category": "cars", "lat": 0.3136, "lng": 32.5811},
    {"phone": "+256700000004", "role": "merchant", "business_name": "iHub Phones", "category": "phone", "lat": 0.3136, "lng": 32.5811},
    {"phone": "+256700000005", "role": "merchant", "business_name": "Sole Republic", "category": "shoes", "lat": 0.3136, "lng": 32.5811},
]

CATALOG = [
    # (folder, merchant index, product names, category, price)
    ("cars", 0, ["Car 1", "Car 2", "Car 3", "Car 4", "Car 5"], "cars", 30_000_000),
    ("iphones", 1, ["Phone 1", "Phone 2", "Phone 3", "Phone 4"], "phone", 3_000_000),
    ("shoes", 2, ["Shoes 1", "Shoes 2", "Shoes 3", "Shoes 4"], "shoes", 150_000),
]


def get_otp_from_log() -> str:
    import glob
    files = sorted(
        glob.glob(os.path.join(LOG_DIR, "api_out*.log")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        return ""
    for line in reversed(open(files[0], encoding="utf-8", errors="ignore").readlines()):
        m = re.search(r"OTP for .*?: (\d{6})", line)
        if m:
            return m.group(1)
    return ""


def merchant_login(phone: str) -> str:
    r = requests.post(f"{API}/api/auth/request-otp", json={"phone": phone}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"request-otp {r.status_code}: {r.text}")
    code = get_otp_from_log()
    if not code:
        raise RuntimeError("could not find OTP in API log")
    r = requests.post(
        f"{API}/api/auth/verify-otp",
        json={"phone": phone, "code": code, "role": "merchant"},
        timeout=30,
    )
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"verify-otp failed: {data}")
    return data["access_token"]


def create_merchant_profile(token: str, info: dict) -> None:
    r = requests.put(
        f"{API}/api/merchants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "business_name": info["business_name"],
            "category": info["category"],
            "location_lat": info["lat"],
            "location_lng": info["lng"],
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"profile {r.status_code}: {r.text}")
    print(f"  merchant profile OK: {r.json()['business_name']} (id={r.json()['id']})")


def create_product(token: str, name: str, category: str, price: float) -> int:
    r = requests.post(
        f"{API}/api/products",
        headers={"Authorization": f"Bearer {token}"},
        params={"name": name, "category": category, "price": price, "stock_qty": 5},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create product {name} {r.status_code}: {r.text}")
    return r.json()["id"]


def upload_primary_image(token: str, product_id: int, image_path: str) -> None:
    with open(image_path, "rb") as f:
        r = requests.post(
            f"{API}/api/products/{product_id}/images",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (os.path.basename(image_path), f, "image/jpeg")},
            timeout=600,
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload image {image_path} {r.status_code}: {r.text}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", help="skip products already in the manifest")
    args = ap.parse_args()

    manifest_path = os.path.join(os.path.dirname(__file__), "mock_inventory_manifest.json")
    manifest = {}
    if args.resume and os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path))

    tokens = {}
    for i, m in enumerate(MERCHANTS):
        print(f"[merchant {i+1}] {m['business_name']} ({m['phone']})")
        tokens[i] = merchant_login(m["phone"])
        create_merchant_profile(tokens[i], m)

    for folder, m_idx, names, category, price in CATALOG:
        folder_path = os.path.join(MOCKS_DIR, folder)
        images = sorted(os.listdir(folder_path))
        if len(images) != len(names):
            print(f"WARNING: {folder} has {len(images)} files but {len(names)} names")
        for name, img_file in zip(names, images):
            img_path = os.path.join(folder_path, img_file)
            if img_file in manifest and not args.resume:
                print(f"  skip {img_file} (already in manifest)")
                continue
            if args.resume and img_file in manifest:
                print(f"  resume: keep {img_file} -> product {manifest[img_file]}")
                continue
            t0 = time.time()
            pid = create_product(tokens[m_idx], name, category, price)
            upload_primary_image(tokens[m_idx], pid, img_path)
            manifest[img_file] = pid
            json.dump(manifest, open(manifest_path, "w"), indent=2)
            print(f"  {img_file} -> product {pid} ({name}, {category}, {price:,} UGX) [{time.time()-t0:.1f}s]")

    json.dump(manifest, open(manifest_path, "w"), indent=2)
    print(f"\nDONE. Manifest: {manifest_path}")
    print(f"Total products: {len(manifest)}")


if __name__ == "__main__":
    main()
