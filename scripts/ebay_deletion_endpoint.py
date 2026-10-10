"""eBay "marketplace account deletion" endpoint, required before eBay enables production API keys.

Run from the repo root:  uv run --project backend python scripts/ebay_deletion_endpoint.py [--port 8431]
and expose it over HTTPS (e.g. `cloudflared tunnel --url http://localhost:8431`).

.env needs EBAY_VERIFICATION_TOKEN (32-80 chars, the same value typed into eBay's form) and
EBAY_DELETION_ENDPOINT (the exact public URL typed into eBay's form).
- GET  ?challenge_code=...  -> {"challengeResponse": sha256(challenge_code + token + endpoint)}
- POST notification         -> answers 204 always; if eBay's signature verifies, deletes that user's raw
                               records and photos and adds their listings to data/seed/exclude_real.csv, so the
                               next scripts/build_dataset.py run drops them from the dataset too
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values

from pull_ebay import Ebay

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EXCLUDE = ROOT / "data" / "seed" / "exclude_real.csv"


def signed_by_ebay(body: bytes, header: str | None) -> bool:
    """Check the X-EBAY-SIGNATURE header (ECDSA over the raw body) against eBay's published key."""
    try:
        sig = json.loads(base64.b64decode(header or ""))
        ebay = Ebay()
        r = ebay.http.get(f"{ebay.host}/commerce/notification/v1/public_key/{sig['kid']}",
                          headers={"Authorization": f"Bearer {ebay._token()}"})
        pem = r.json()["key"].replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "")
        pem = f"-----BEGIN PUBLIC KEY-----\n{pem.strip()}\n-----END PUBLIC KEY-----\n"
        serialization.load_pem_public_key(pem.encode()).verify(
            base64.b64decode(sig["signature"]), body, ec.ECDSA(hashes.SHA1()))
        return True
    except Exception as exc:                           # bad header, unknown key, wrong signature, no network
        print(f"signature not verified ({exc.__class__.__name__})")
        return False


def delete_user(username: str) -> int:
    """Remove the seller's raw records and photos, and exclude their listings from future dataset builds."""
    removed = 0
    for path in (RAW / "ebay").glob("*.json"):
        record = json.loads(path.read_text())
        if record.get("seller_handle") != username:
            continue
        for image in record.get("images", []):
            (RAW / image).unlink(missing_ok=True)
        with EXCLUDE.open("a", newline="") as f:
            csv.writer(f).writerow([record["source"], record["source_id"], "seller account deleted (eBay notice)"])
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
        # Always acknowledge (eBay retries and flags the endpoint otherwise); only a signed notice deletes.
        if signed_by_ebay(raw, self.headers.get("X-EBAY-SIGNATURE")):
            try:
                username = json.loads(raw)["notification"]["data"]["username"]
                removed = delete_user(username)
                print(f"deletion notice: removed {removed} raw record(s)"
                      + ("; run scripts/build_dataset.py to drop them from the dataset" if removed else ""))
            except (ValueError, KeyError, TypeError):
                print("deletion notice: unreadable body, acknowledged")
        else:
            print("deletion notice ignored: not signed by eBay")
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8431)
    port = parser.parse_args().port
    print(f"eBay deletion endpoint on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
