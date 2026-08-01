"""End-to-end smoke test mirroring the frontend's API usage:
login -> chat (search) -> lookup result code -> express/remove interest -> open shop (role upgrade) -> products CRUD.
"""
import glob
import json
import os
import re
import sys

import requests

API = "http://127.0.0.1:8002"
LOG_DIR = "C:/Users/CONRAD/Rooms/whatAppSeller"
PHONE = "+256700000999"


def get_otp_from_log() -> str:
    files = sorted(glob.glob(os.path.join(LOG_DIR, "api_out*.log")), key=os.path.getmtime, reverse=True)
    if not files:
        return ""
    for line in reversed(open(files[0], encoding="utf-8", errors="ignore").readlines()):
        m = re.search(r"OTP for .*?: (\d{6})", line)
        if m:
            return m.group(1)
    return ""


def check(name: str, ok: bool, extra: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" {extra}" if extra else ""))


def main() -> None:
    s = requests.Session()

    r = s.post(f"{API}/api/auth/request-otp", json={"phone": PHONE}, timeout=30)
    check("request-otp", r.status_code == 200, f"({r.status_code})")

    code = get_otp_from_log()
    check("otp read from log", bool(code))
    if not code:
        sys.exit(1)

    r = s.post(f"{API}/api/auth/verify-otp", json={"phone": PHONE, "code": code, "role": "client"}, timeout=30)
    data = r.json()
    check("verify-otp client", r.status_code == 200 and (data.get("user") or {}).get("role") == "client", f"role={(data.get('user') or {}).get('role')}")
    token = data.get("access_token")
    if not token:
        sys.exit(1)
    s.headers["Authorization"] = f"Bearer {token}"

    r = s.get(f"{API}/api/auth/me", timeout=30)
    check("get /me", r.status_code == 200, f"({r.status_code})")

    # Chat
    r = s.post(f"{API}/api/chat", data={"text": "I want shoes"}, timeout=120)
    chat = r.json()
    check("chat search", r.status_code == 200 and chat.get("reply_type") == "search_results")
    result_code = chat.get("result_code")
    sections = chat.get("sections") or []
    check("chat has sections", bool(sections), f"{len(sections)} sections")
    first = sections[0]["results"][0] if sections and sections[0]["results"] else None
    check("result shape", first and "product_id" in first and "images" in first and "merchant" in first)
    if first:
        print("       first result:", json.dumps({k: first.get(k) for k in ("product_id", "name", "price", "currency", "category", "match_label", "score")}, ensure_ascii=False))
        print("       first image:", first["images"][0]["url"] if first.get("images") else None)
    if chat.get("follow_up"):
        print("       follow_up:", chat["follow_up"]["prompt"])

    # Result-code lookup
    if result_code:
        r = s.get(f"{API}/api/result-codes/{result_code}", timeout=30)
        check("result-code lookup", r.status_code == 200 and r.json().get("code") == result_code, f"({r.status_code})")

    # Interest
    if first:
        pid = first["product_id"]
        r = s.post(f"{API}/api/clients/me/interests/{pid}", timeout=30)
        check("express interest", r.status_code == 200, f"({r.status_code})")
        r = s.get(f"{API}/api/clients/me/interests", timeout=30)
        check("list interests", r.status_code == 200 and any(i["product"]["id"] == pid for i in r.json()), f"({r.status_code})")
        r = s.delete(f"{API}/api/clients/me/interests/{pid}", timeout=30)
        check("remove interest", r.status_code == 200, f"({r.status_code})")

    # History
    r = s.get(f"{API}/api/clients/me/history", timeout=30)
    hist = r.json()
    check("history recorded", r.status_code == 200 and hist.get("total", 0) >= 1, f"total={hist.get('total')}")

    # Open shop (role upgrade)
    r = s.put(f"{API}/api/merchants/me/profile", params={"business_name": "Smoke Test Shop", "category": "Shoes"}, timeout=30)
    check("update merchant profile", r.status_code == 200, f"({r.status_code})")
    r = s.get(f"{API}/api/merchants/me/profile", timeout=30)
    check("get merchant profile", r.status_code == 200 and r.json().get("business_name") == "Smoke Test Shop", f"({r.status_code})")
    r = s.get(f"{API}/api/auth/me", timeout=30)
    check("role upgraded to merchant", r.json().get("role") == "merchant", f"role={r.json().get('role')}")

    # Products CRUD
    r = s.post(f"{API}/api/products", params={"name": "Smoke Test Sandal", "category": "Shoes", "price": 50000, "brand": "desc", "stock_qty": 3}, timeout=30)
    prod = r.json()
    check("create product", r.status_code == 200 and "id" in prod, f"id={prod.get('id')}")
    if "id" in prod:
        pid = prod["id"]
        r = s.get(f"{API}/api/products", timeout=30)
        check("list products", r.status_code == 200 and any(p["id"] == pid for p in r.json()), f"({r.status_code})")
        r = s.put(f"{API}/api/products/{pid}", params={"price": 55000}, timeout=30)
        check("update product", r.status_code == 200 and r.json().get("price") == 55000, f"({r.status_code})")
        r = s.delete(f"{API}/api/products/{pid}", timeout=30)
        check("delete product", r.status_code == 200, f"({r.status_code})")

    print("\nDone.")


if __name__ == "__main__":
    main()
