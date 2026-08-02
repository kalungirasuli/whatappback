"""Live test: post raptor1.jpg (and small text messages) to the RUNNING backend,
mirroring exactly what the frontend does, and show the replies."""
import glob
import json
import os
import re
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API = "http://127.0.0.1:8002"
LOG_DIR = "C:/Users/CONRAD/Rooms/whatAppSeller"
PHONE = "+256700000777"
RAPTOR = r"C:\Users\CONRAD\Downloads\images mocks\test car\raptor1.jpg"


def get_otp_from_log(phone: str) -> str:
    files = sorted(glob.glob(os.path.join(LOG_DIR, "api_out*.log")), key=os.path.getmtime, reverse=True)
    if not files:
        return ""
    needle = phone.replace("+", "")
    for line in reversed(open(files[0], encoding="utf-8", errors="ignore").readlines()):
        m = re.search(rf"OTP for {re.escape(needle)}: (\d{{6}})", line)
        if m:
            return m.group(1)
    return ""


def show(reply: dict) -> None:
    rt = reply.get("reply_type")
    print(f"  reply_type={rt} code={reply.get('result_code')}")
    text = reply.get("text") or reply.get("response_text") or ""
    print(f"  text: {text[:300]}")
    sections = reply.get("sections") or []
    if sections:
        for s in sections:
            names = [(r.get("name"), round(r.get("score", 0), 3)) for r in (s.get("results") or [])[:5]]
            print(f"  section '{s['label']}': total={s['total']} -> {names}")
    if reply.get("follow_up"):
        print(f"  follow_up: {reply['follow_up']['prompt'][:200]}")


def main() -> None:
    s = requests.Session()
    r = s.post(f"{API}/api/auth/request-otp", json={"phone": PHONE}, timeout=30)
    print(f"request-otp: {r.status_code}")
    code = get_otp_from_log(PHONE)
    print(f"otp: {code}")
    if not code:
        sys.exit(1)
    r = s.post(f"{API}/api/auth/verify-otp", json={"phone": PHONE, "code": code, "role": "client"}, timeout=30)
    data = r.json()
    token = data.get("access_token")
    print(f"verify-otp: {r.status_code} role={(data.get('user') or {}).get('role')}")
    if not token:
        sys.exit(1)
    s.headers["Authorization"] = f"Bearer {token}"

    with open(RAPTOR, "rb") as f:
        img = f.read()

    print("\n--- [1] raptor image ONLY (no text) ---")
    r = s.post(f"{API}/api/chat", files={"files": ("raptor1.jpg", img, "image/jpeg")}, timeout=120)
    show(r.json())

    print("\n--- [2] raptor image + caption 'i need this car' ---")
    r = s.post(f"{API}/api/chat", data={"text": "i need this car"}, files={"files": ("raptor1.jpg", img, "image/jpeg")}, timeout=120)
    show(r.json())

    print("\n--- [3] small text 'hello' ---")
    r = s.post(f"{API}/api/chat", data={"text": "hello"}, timeout=120)
    show(r.json())

    print("\n--- [4] small text 'i want shoes' ---")
    r = s.post(f"{API}/api/chat", data={"text": "i want shoes"}, timeout=120)
    show(r.json())


if __name__ == "__main__":
    main()
