"""eBay "marketplace account deletion" endpoint, required before eBay enables production API keys.

Run from the repo root:  uv run --project backend python scripts/ebay_deletion_endpoint.py [--port 8431]
and expose it over HTTPS (e.g. `cloudflared tunnel --url http://localhost:8431`).

.env needs EBAY_VERIFICATION_TOKEN (32-80 chars, the same value typed into eBay's form) and
EBAY_DELETION_ENDPOINT (the exact public URL typed into eBay's form).
- GET  ?challenge_code=...  -> {"challengeResponse": sha256(challenge_code + token + endpoint)}
- POST notification         -> deletes that user's raw records from data/raw/ebay, answers 204
"""
from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
RAW_EBAY = ROOT / "data" / "raw" / "ebay"


def delete_user(username: str) -> int:
    removed = 0
    for path in RAW_EBAY.glob("*.json"):
        if json.loads(path.read_text()).get("seller_handle") == username:
            path.unlink()
            removed += 1
    return removed


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        code = parse_qs(urlparse(self.path).query).get("challenge_code", [""])[0]
        env = dotenv_values(ROOT / ".env")          # re-read each time so the tunnel URL can change
        token, endpoint = env.get("EBAY_VERIFICATION_TOKEN"), env.get("EBAY_DELETION_ENDPOINT")
        if not (code and token and endpoint):
            self.send_error(400, "missing challenge_code, or token/endpoint not configured")
            return
        body = json.dumps({"challengeResponse": hashlib.sha256((code + token + endpoint).encode()).hexdigest()})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            username = json.loads(raw)["notification"]["data"]["username"]
            print(f"deletion notice: removed {delete_user(username)} raw record(s)")
        except (ValueError, KeyError, TypeError):
            print("deletion notice: unreadable body, acknowledged")
        # ponytail: the X-EBAY-SIGNATURE header is not verified; verify it if this ever outlives the hackathon
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8431)
    port = parser.parse_args().port
    print(f"eBay deletion endpoint on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
