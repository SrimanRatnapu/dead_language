"""Manual fallback for pull_ebay.py: turn a hand-filled CSV of public listings into the same raw records.

Run from the repo root:  uv run --project backend python scripts/ingest_manual_csv.py [path/to/filled.csv]

Columns are those of data/manual_listings_template.csv. ship_from is "US-CA"-style for US items, else a
country code. posted_at is an ISO date. Writes data/raw/manual/<row_n>.json and data/raw/manual_images/.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import httpx

from pull_ebay import RAW, ROOT, clean_text, download_image


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "manual_listings.csv"
    (RAW / "manual").mkdir(parents=True, exist_ok=True)
    (RAW / "manual_images").mkdir(parents=True, exist_ok=True)
    http = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    saved = 0
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=1):
            row = {k: (v or "").strip() for k, v in row.items() if k}
            try:
                price = float(row["price_usd"].replace("$", "").replace(",", ""))
            except (KeyError, ValueError):
                price = 0.0
            if not row.get("title") or price <= 0 or not row.get("seller_handle"):
                print(f"row {n} skipped: needs title, price_usd and seller_handle")
                continue
            record = {
                "source": "manual", "source_id": f"{n:04d}", "title": row["title"],
                "description": clean_text(row.get("description", "")), "price_usd": price,
                "seller_handle": row["seller_handle"], "seller_feedback": None,
                "seller_location": row.get("seller_location", ""), "ship_from": row.get("ship_from") or "US",
                "category": row.get("category", ""), "source_url": row.get("source_url") or None,
                "posted_at": row.get("posted_at") or None, "images": [], "query": "manual"}
            for i in (1, 2, 3):
                url = row.get(f"image_url_{i}")
                name = f"manual_images/{n:04d}_{i - 1}.jpg"
                if url and download_image(http, url, RAW / name):
                    record["images"].append(name)
            (RAW / "manual" / f"{n:04d}.json").write_text(json.dumps(record, indent=1))
            saved += 1
    print(f"saved {saved} listings to {RAW / 'manual'}")


if __name__ == "__main__":
    main()
