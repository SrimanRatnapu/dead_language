"""Pull real look-alike listings (bone, tagua, resin, wood carvings) from the eBay Browse API.

Run from the repo root:  uv run --project backend python scripts/pull_ebay.py [--dry-run] [--max 300]

Needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env. They must be a PRODUCTION keyset (EBAY_ENV=production,
the default): the sandbox (EBAY_ENV=sandbox) accepts the same calls but holds no real listings.
Writes one normalized record per item to data/raw/ebay/<itemId>.json and photos to data/raw/ebay_images/
(both gitignored). scripts/ingest_manual_csv.py writes the same record format.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from deadlang.marketplace.ebay import Ebay, clean_text, download_image, normalize, ship_from  # noqa: E402,F401
RAW = ROOT / "data" / "raw"
QUERIES = ["netsuke bone", "bone carving figurine", "carved bone netsuke antique", "tagua carving",
           "vegetable ivory", "resin netsuke", "faux ivory bangle", "ivory color resin figurine",
           "bone bead necklace carved", "antique bone carving chinese", "okimono carving", "boxwood netsuke"]
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
