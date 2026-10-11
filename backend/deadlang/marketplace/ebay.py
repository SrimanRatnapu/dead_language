"""eBay Browse API client shared by the dataset pull (scripts/pull_ebay.py), the live connector and refresh.

Official API only (no page scraping). Credentials come from EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env;
EBAY_ENV=sandbox switches hosts (the sandbox has no real listings). Our own rate limit: one request per 0.1 s.
"""
from __future__ import annotations

import html
import io
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY"}


def ship_from(country: str | None, state: str | None) -> str:
    """"US-CA" for US items when the state is known, else the country code."""
    country = (country or "").strip().upper() or "US"
    if country != "US":
        return country
    state = (state or "").strip()
    code = state.upper() if len(state) == 2 else US_STATES.get(state.lower())
    return f"US-{code}" if code else "US"


def clean_text(raw: str, limit: int = 1500) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", raw or "", flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def download_image(http: httpx.Client, url: str, dest: Path) -> bool:
    """Save a remote image as JPEG. Returns False (and saves nothing) if it cannot be fetched or decoded."""
    if dest.exists():
        return True
    try:
        r = http.get(url)
        r.raise_for_status()
        Image.open(io.BytesIO(r.content)).convert("RGB").save(dest, "JPEG", quality=92)
        return True
    except Exception as exc:
        print(f"  image skipped ({exc.__class__.__name__}): {url}")
        return False


class Ebay:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")
        env = os.environ.get("EBAY_ENV", "production").split("#")[0].strip().lower()
        self.host = "https://api.sandbox.ebay.com" if env == "sandbox" else "https://api.ebay.com"
        self.http = httpx.Client(timeout=30, follow_redirects=True)
        self.token, self.token_expires = "", 0.0
        print(f"eBay environment: {env} ({self.host})")
        if env == "sandbox":
            print("WARNING: the sandbox has no real listings. Use a production keyset for the dataset.")

    def _token(self) -> str:
        if time.time() > self.token_expires - 60:
            r = self.http.post(f"{self.host}/identity/v1/oauth2/token",
                               auth=(os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"]),
                               data={"grant_type": "client_credentials",
                                     "scope": "https://api.ebay.com/oauth/api_scope"})
            if r.status_code != 200:
                raise SystemExit(f"eBay token request failed ({r.status_code}): {r.text[:300]}")
            body = r.json()
            self.token, self.token_expires = body["access_token"], time.time() + body["expires_in"]
        return self.token

    def get(self, path: str, **params) -> dict:
        time.sleep(0.1)
        r = self.http.get(f"{self.host}/buy/browse/v1{path}", params=params or None,
                          headers={"Authorization": f"Bearer {self._token()}",
                                   "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        if r.status_code != 200:
            print(f"  eBay {r.status_code} for {path}: {r.text[:200]}")
            return {}
        return r.json()

    def search(self, query: str, seller: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        params = {"q": query, "limit": limit, "offset": offset}
        if seller:
            params["filter"] = f"sellers:{{{seller}}}"
        return self.get("/item_summary/search", **params).get("itemSummaries", [])

    def item_status(self, item_id: str) -> tuple[int, dict]:
        """(HTTP status, body) for one item, so a caller can tell "gone" (404) from "try again later"."""
        time.sleep(0.1)
        r = self.http.get(f"{self.host}/buy/browse/v1/item/{item_id}",
                          headers={"Authorization": f"Bearer {self._token()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        return r.status_code, (r.json() if r.status_code == 200 else {})

    @staticmethod
    def configured() -> bool:
        load_dotenv(ROOT / ".env")
        return bool(os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET"))


def normalize(item: dict, query: str) -> dict | None:
    price = item.get("price") or {}
    if price.get("currency") != "USD" or not item.get("title"):
        return None
    location, seller = item.get("itemLocation") or {}, item.get("seller") or {}
    urls = [(item.get("image") or {}).get("imageUrl")] + [i.get("imageUrl") for i in item.get("additionalImages") or []]
    return {
        "source": "ebay", "source_id": item["itemId"], "title": item["title"].strip(),
        "description": clean_text(item.get("description") or item.get("shortDescription") or ""),
        "price_usd": float(price["value"]),
        "seller_handle": seller.get("username") or "", "seller_feedback": seller.get("feedbackScore"),
        "seller_location": ", ".join(x for x in (location.get("stateOrProvince"), location.get("country")) if x),
        "ship_from": ship_from(location.get("country"), location.get("stateOrProvince")),
        "category": (item.get("categoryPath") or "").replace("|", " > "),
        "source_url": item.get("itemWebUrl"), "posted_at": item.get("itemCreationDate"),
        "image_urls": [u for u in urls if u][:3], "images": [], "query": query, "raw": item}
