"""Pull real look-alike listings (bone, tagua, resin, wood carvings) from the eBay Browse API.

Run from the repo root:  uv run --project backend python scripts/pull_ebay.py [--dry-run] [--max 300]

Needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env. They must be a PRODUCTION keyset (EBAY_ENV=production,
the default): the sandbox (EBAY_ENV=sandbox) accepts the same calls but holds no real listings.
Writes one normalized record per item to data/raw/ebay/<itemId>.json and photos to data/raw/ebay_images/
(both gitignored). scripts/ingest_manual_csv.py writes the same record format.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
QUERIES = ["netsuke bone", "bone carving figurine", "carved bone netsuke antique", "tagua carving",
           "vegetable ivory", "resin netsuke", "faux ivory bangle", "ivory color resin figurine",
           "bone bead necklace carved", "antique bone carving chinese", "okimono carving", "boxwood netsuke"]
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

    def search(self, query: str, seller: str | None = None) -> list[dict]:
        params = {"q": query, "limit": 100}
        if seller:
            params["filter"] = f"sellers:{{{seller}}}"
        return self.get("/item_summary/search", **params).get("itemSummaries", [])


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=300, help="stop after this many items")
    parser.add_argument("--dry-run", action="store_true", help="print counts per query; save nothing")
    args = parser.parse_args()
    ebay = Ebay()

    found: dict[str, str] = {}                       # itemId -> the query that found it
    sellers: Counter[str] = Counter()
    bone_tagua_hits: list[dict] = []
    for query in QUERIES:
        hits = ebay.search(query)
        if "bone" in query or "tagua" in query:
            bone_tagua_hits += hits
        for h in hits:
            found.setdefault(h["itemId"], query)
            sellers[(h.get("seller") or {}).get("username") or ""] += 1
        print(f"{query!r}: {len(hits)} items ({len(found)} unique so far)")
    sellers.pop("", None)
    for username, _ in sellers.most_common(15):      # their wider inventories; one becomes the honest dealer
        hits = ebay.search("carving", seller=username)
        for h in hits:
            found.setdefault(h["itemId"], f"seller:{username}")
        print(f"seller inventory {len(hits)} items")
    print(f"total unique items: {len(found)}")
    if args.dry_run:
        return

    (RAW / "ebay").mkdir(parents=True, exist_ok=True)
    (RAW / "ebay_images").mkdir(parents=True, exist_ok=True)
    # Take items round-robin across the searches (80% of --max), then across the seller inventories,
    # so every material is represented instead of the first queries filling the whole quota.
    groups: dict[str, list[str]] = {}
    for item_id, query in found.items():
        groups.setdefault(query, []).append(item_id)

    def round_robin(names: list[str]) -> list[str]:
        longest = max((len(groups[n]) for n in names), default=0)
        return [groups[n][i] for i in range(longest) for n in names if i < len(groups[n])]

    by_query = round_robin([g for g in groups if not g.startswith("seller:")])
    by_seller = round_robin([g for g in groups if g.startswith("seller:")])
    # N3 "honest dealer": up to 10 bone/tagua items of the seller with the most hits in those searches.
    dealers: Counter[str] = Counter()
    for h in bone_tagua_hits:
        dealers[(h.get("seller") or {}).get("username") or ""] += 1
    dealers.pop("", None)
    dealer = dealers.most_common(1)[0][0] if dealers else None
    dealer_items = list(dict.fromkeys(h["itemId"] for h in bone_tagua_hits
                                      if (h.get("seller") or {}).get("username") == dealer))[:10]
    head = int(args.max * 0.8) - len(dealer_items)
    order = list(dict.fromkeys(dealer_items + by_query[:head] + by_seller + by_query[head:]))

    saved = 0
    for item_id in order:
        query = found[item_id]
        if saved >= args.max:
            break
        safe = re.sub(r"[^A-Za-z0-9]+", "_", item_id).strip("_")
        out = RAW / "ebay" / f"{safe}.json"
        if out.exists():
            saved += 1
            continue
        record = normalize(ebay.get(f"/item/{item_id}"), query)
        if record is None:
            continue
        for n, url in enumerate(record["image_urls"]):
            name = f"ebay_images/{safe}_{n}.jpg"
            if download_image(ebay.http, url, RAW / name):
                record["images"].append(name)
        out.write_text(json.dumps(record, indent=1))
        saved += 1
    print(f"saved {saved} items to {RAW / 'ebay'}")


if __name__ == "__main__":
    main()
