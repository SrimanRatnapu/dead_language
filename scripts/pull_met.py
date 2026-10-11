"""Pull public-domain (CC0) object photos from The Met Open Access API.

Run from the repo root:  uv run --project backend python scripts/pull_met.py

Writes two things:
- data/museum/<objectID>.jpg + data/museum/museum_labels.csv — a labeled photo set for measuring the
  Material Examiner (committed).
- data/raw/met/<objectID>_<n>.jpg + <objectID>.json — extra ivory objects with several views each, used
  only as photos for reconstructed listings (gitignored; never overlaps the museum set).

Note: the plan's /v1/search endpoint was retired on 2026-10-01; this uses its replacement /v1.1/search.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MUSEUM, RAW = ROOT / "data" / "museum", ROOT / "data" / "raw" / "met"
API = "https://collectionapi.metmuseum.org/public/collection"
MUSEUM_QUERIES = ["netsuke ivory", "okimono ivory", "netsuke bone", "netsuke wood", "netsuke stag antler",
                  "carved bone"]
POOL_QUERIES = [("netsuke ivory", 30), ("okimono", 4), ("ivory bracelet", 12)]   # (query, max objects)
MATERIAL_WORDS = ("ivory", "bone", "wood", "antler")
client = httpx.Client(timeout=30, headers={"User-Agent": "watchdog-hackathon/0.1"}, follow_redirects=True)


def get(url: str, **params) -> httpx.Response | None:
    """GET with patience: the API's bot filter answers bursts with 403s or hung connections."""
    for wait in (0, 30, 90):
        time.sleep(1.0 + wait)                         # well under 5 requests per second
        try:
            r = client.get(url, params=params or None)
        except httpx.TransportError:
            continue
        if r.status_code not in (403, 429):
            return r
    return None


def get_json(cache_name: str, url: str, **params) -> dict:
    """API JSON, cached under data/raw/met_cache so an interrupted run can resume."""
    cache = RAW.parent / "met_cache" / f"{cache_name}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    r = get(url, **params)
    if r is None or r.status_code != 200:
        return {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text)
    return r.json()


def label_for(medium: str) -> str | None:
    m = medium.lower()
    if sum(word in m for word in MATERIAL_WORDS) != 1 or "vegetable" in m:
        return None                                    # mixed or unclear materials are skipped
    return {"ivory": "elephant_ivory", "bone": "bone", "wood": "wood", "antler": "other"}[
        next(word for word in MATERIAL_WORDS if word in m)]


def search(query: str, limit: int = 80) -> list[int]:
    found = get_json("search_" + query.replace(" ", "_"), f"{API}/v1.1/search", hasImages="true", q=query, limit=limit)
    return found.get("objectIDs") or []


def fetch_object(object_id: int) -> dict | None:
    obj = get_json(str(object_id), f"{API}/v1/objects/{object_id}")
    return obj if obj.get("isPublicDomain") and obj.get("primaryImageSmall") else None


def save_jpeg(url: str, dest: Path, max_side: int = 800, max_bytes: int = 300_000) -> bool:
    if dest.exists():
        return True                                    # re-runs only download what is missing
    r = get(url)
    if r is None or r.status_code != 200:
        return False
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    img.thumbnail((max_side, max_side))
    for quality in (85, 75, 65, 55):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            break
    dest.write_bytes(buf.getvalue())
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-label", default="elephant_ivory=20,bone=10,wood=10,other=10",
                        help="caps for the museum set, e.g. elephant_ivory=20,bone=10")
    parser.add_argument("--listing-pool", type=int, default=46,
                        help="extra ivory objects (with several views) saved for reconstructed listings")
    args = parser.parse_args()
    caps = {k: int(v) for k, v in (pair.split("=") for pair in args.per_label.split(","))}
    MUSEUM.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    seen: set[int] = set()
    rows: list[dict] = []
    counts = dict.fromkeys(caps, 0)
    for query in MUSEUM_QUERIES:
        for object_id in search(query):
            if object_id in seen or all(counts[k] >= caps[k] for k in caps):
                continue
            seen.add(object_id)
            obj = fetch_object(object_id)
            label = label_for(obj.get("medium", "")) if obj else None
            if label is None or counts.get(label, 0) >= caps.get(label, 0):
                continue
            if not save_jpeg(obj["primaryImageSmall"], MUSEUM / f"{object_id}.jpg"):
                continue
            counts[label] += 1
            rows.append({"object_id": object_id, "label": label, "medium": obj["medium"], "title": obj["title"],
                         "object_url": obj["objectURL"], "image_path": f"museum/{object_id}.jpg"})
            print(f"museum {label:15} {object_id}  {obj['medium'][:40]!r}  {obj['title'][:50]}")
    rows.sort(key=lambda r: r["object_id"])
    with (MUSEUM / "museum_labels.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("museum set:", counts)

    used = {r["object_id"] for r in rows}             # the examiner's test photos are never listing photos
    pool = 0
    for query, cap in POOL_QUERIES:
        taken = 0
        for object_id in search(query):
            if taken >= cap or pool >= args.listing_pool:
                break
            if object_id in used:
                continue
            used.add(object_id)
            obj = fetch_object(object_id)
            if not obj or label_for(obj.get("medium", "")) != "elephant_ivory":
                continue
            urls = [obj["primaryImageSmall"]] + [u.replace("/original/", "/web-large/")
                                                 for u in obj.get("additionalImages", [])[:3]]
            saved = [f"{object_id}_{n}.jpg" for n, url in enumerate(urls) if save_jpeg(url, RAW / f"{object_id}_{n}.jpg")]
            if not saved:
                continue
            keep = ("objectID", "title", "objectName", "medium", "objectDate", "dimensions", "objectURL", "culture")
            (RAW / f"{object_id}.json").write_text(json.dumps({**{k: obj.get(k) for k in keep}, "images": saved,
                                                              "query": query}, indent=1))
            taken += 1
            pool += 1
            print(f"pool   {object_id}  {len(saved)} views  {obj.get('objectName', '')[:20]:20} {obj['title'][:50]}")
    print("listing pool:", pool, "ivory objects in", RAW)


if __name__ == "__main__":
    main()
