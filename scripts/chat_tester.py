"""Interactive chat tester: texts the app (with optional images) as the test client.

Usage:
    python scripts/chat_tester.py "I want to buy a laptop"
    python scripts/chat_tester.py "Find something like this" --image C:\\path\\to\\photo.jpg
    python scripts/chat_tester.py --image C:\\path\\to\\shoes.jpg --lat 0.3136 --lng 32.5811
    python scripts/chat_tester.py --token <ACCESS_TOKEN> "hello"   # reuse a token
"""
import os
import glob
import argparse
import json
import re
import sys

import requests

API = "http://127.0.0.1:8002"
PHONE = "+256700000001"
LOG_DIR = "C:/Users/CONRAD/Rooms/whatAppSeller"


def get_otp_from_log() -> str:
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


def login() -> str:
    r = requests.post(f"{API}/api/auth/request-otp", json={"phone": PHONE}, timeout=30)
    print(f"[request-otp] {r.status_code} {r.text}")
    code = get_otp_from_log()
    if not code:
        print("ERROR: could not find OTP in API log — is the server running?", file=sys.stderr)
        sys.exit(1)
    print(f"[otp] code {code}")
    r = requests.post(
        f"{API}/api/auth/verify-otp",
        json={"phone": PHONE, "code": code, "role": "client"},
        timeout=30,
    )
    print(f"[verify-otp] {r.status_code}")
    data = r.json()
    if "access_token" not in data:
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)
    return data["access_token"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="", help="message text")
    ap.add_argument("--image", help="path to an image to send")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--token", help="reuse an access token instead of OTP login")
    args = ap.parse_args()

    token = args.token or login()
    headers = {"Authorization": f"Bearer {token}"}

    params = {}
    if args.lat is not None and args.lng is not None:
        params = {"lat": args.lat, "lng": args.lng}

    files = None
    if args.image:
        files = [("files", (args.image, open(args.image, "rb"), "image/jpeg"))]

    r = requests.post(
        f"{API}/api/chat",
        headers=headers,
        params=params,
        data={"text": args.text},
        files=files,
        timeout=120,
    )
    print(f"\n[chat] {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
