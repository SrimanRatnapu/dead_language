"""Live lane: a capped fetch of real listings from the eBay Browse API, or a recorded fetch when the API is
unavailable. The result always says which of the two it is; a recorded result is never presented as live.

Limits (ours, on top of eBay's): at most MAX_CAP listings per call, at most MAX_PAGES search pages, one request
per 0.1 s, at most 3 photos per listing. Official API only.

What is kept: data/live/listings.jsonl (one record per listing: the listing, its pseudonymous seller, the eBay
item id, the fetch time and a SHA-256 of the raw API response) and photos under data/images/live/. The raw
response and the seller's real username are NOT kept. Records older than RETENTION_DAYS are purged on each fetch.
Nothing here ever touches data/listings.jsonl or data/labels.csv.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from deadlang.marketplace.client import data_dir, get_marketplace_client
from deadlang.marketplace.ebay import Ebay, normalize
from deadlang.schemas import Listing, Seller, now_iso
from deadlang.specialists.network import photo_hashes, same_photo
from deadlang.textparse import item_type, stated_material

log = logging.getLogger("deadlang.live")
MAX_CAP = 50
MAX_PAGES = 3
RETENTION_DAYS = 30
SALT = "deadlang"
RECORDED = Path(__file__).resolve().parents[3] / "fixtures" / "live_recorded.jsonl"
RECORDED_IMAGES = RECORDED.parent / "live_recorded_images"


def _records_file() -> Path:
    return data_dir() / "live" / "listings.jsonl"


def load_records() -> list[dict]:
    """Every live listing kept on disk: {listing, seller, source_item_id, fetched_at, snapshot_sha256}."""
    path = _records_file()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _write_records(records: list[dict]) -> None:
    path = _records_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def snapshot_hash(listing_id: str) -> str | None:
    """SHA-256 of the raw source snapshot taken when a live listing was fetched (chain of custody)."""
    return next((r["snapshot_sha256"] for r in load_records() if r["listing"]["id"] == listing_id), None)


def purge_expired(records: list[dict]) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    keep = [r for r in records if r["fetched_at"] >= cutoff]
    for r in records:
        if r["fetched_at"] < cutoff:
            for rel in r["listing"]["image_paths"]:
                (data_dir() / rel).unlink(missing_ok=True)
    return keep


def _seller(username: str, feedback: int | None, location: str) -> Seller:
    digest = hashlib.sha1((username + SALT).encode()).hexdigest()
    return Seller(id=f"S-live-{digest[:4]}", name=f"seller_{digest[:6]}", location=location or "unknown",
                  joined=now_iso(), feedback_score=feedback)       # eBay gives no join date; this is first-seen


def _language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    return "en" if not letters or sum(c.isascii() for c in letters) / len(letters) > 0.8 else "und"


def _save_photo(raw: bytes, dest: Path) -> bool:
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((800, 800))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "JPEG", quality=85)
        return True
    except Exception:
        return False                                       # an unreadable photo is skipped, never fatal


def _fetch_from_ebay(query: str, cap: int, known_items: set[str], next_number: int,
                     fetched_before: dict[str, dict]) -> list[dict]:
    """Blocking. Up to `cap` records for the query: items fetched before are reused as they are (no duplicate
    is stored), items already in the stored dataset are skipped. Raises if the API cannot be used."""
    ebay = Ebay()
    ebay._token()                                          # fail here, before any work, if the keys are bad
    records: list[dict] = []
    old_ids = {r["listing"]["id"] for r in fetched_before.values()}
    for page in range(MAX_PAGES):
        hits = ebay.search(query, limit=50, offset=page * 50)
        for hit in hits:
            if len(records) >= cap:
                return records
            item_id = hit.get("itemId")
            if item_id in fetched_before:
                if fetched_before[item_id] not in records:
                    records.append(fetched_before[item_id])
                continue
            if not item_id or item_id in known_items:
                continue                                   # dedupe by item id against the stored dataset
            known_items.add(item_id)
            status, raw = ebay.item_status(item_id)
            n = normalize(raw, query) if status == 200 else None
            if n is None:
                continue                                   # gone, not priced in USD, or untitled
            lid = f"LV{next_number + sum(r['listing']['id'] not in old_ids for r in records):04d}"
            paths = []
            for url in n["image_urls"]:
                try:
                    body = ebay.http.get(url).content
                except Exception:
                    continue
                rel = f"images/live/{lid}_{len(paths)}.jpg"
                if _save_photo(body, data_dir() / rel):
                    paths.append(rel)
            username = n["seller_handle"] or f"unknown-{item_id}"
            seller = _seller(username, n["seller_feedback"], n["seller_location"])
            for field in ("title", "description"):         # sellers often name their own shop in the text
                n[field] = re.sub(rf"(?<![A-Za-z0-9]){re.escape(username)}(?![A-Za-z0-9])", seller.name, n[field], flags=re.I)
            listing = Listing(
                id=lid, marketplace="ebay", seller_id=seller.id, title=n["title"], description=n["description"],
                price_usd=round(n["price_usd"], 2), category=n["category"],
                stated_material=stated_material(n["title"], n["description"]),
                item_type=item_type(n["title"], n["description"]), ship_from=n["ship_from"],
                language=_language(n["title"] + " " + n["description"]), image_paths=paths,
                posted_at=n["posted_at"] or now_iso(), source_url=n["source_url"], origin="live")
            records.append({"listing": listing.model_dump(mode="json"), "seller": seller.model_dump(mode="json"),
                            "source_item_id": item_id, "fetched_at": now_iso(),
                            "snapshot_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()})
        if len(hits) < 50:
            break
    return records


def _recorded(cap: int) -> list[dict]:
    """The saved fetch (fixtures/live_recorded.jsonl), with its photos copied to where the app serves them."""
    if not RECORDED.exists():
        return []
    records = [json.loads(line) for line in RECORDED.read_text().splitlines() if line.strip()][:cap]
    for r in records:
        for rel in r["listing"]["image_paths"]:
            src, dest = RECORDED_IMAGES / Path(rel).name, data_dir() / rel
            if src.exists() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
    return records


async def fetch_live(query: str, cap: int = 25) -> tuple[list[tuple[Listing, Seller | None]], str]:
    """Up to `cap` (max 50) listings for `query`, each already added to the marketplace store.

    Returns (pairs, mode). mode is "live" when they came from the eBay API just now and "recorded" when the API
    could not be used (no credentials, or it failed) and the saved fetch was returned instead.
    """
    cap = max(1, min(cap, MAX_CAP))
    market = get_marketplace_client()
    stored = purge_expired(load_records())
    mode, new = "recorded", []
    if Ebay.configured():
        fetched_before = {r["source_item_id"]: r for r in stored}
        known = {l.source_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] for l in await market.all_active()
                  if l.origin == "demo" and l.source_url}          # numeric id of items already in the dataset
        next_number = 1 + max((int(r["listing"]["id"][2:]) for r in stored), default=0)
        try:
            new = await asyncio.to_thread(_fetch_from_ebay, query, cap, _LegacyIds(known), next_number, fetched_before)
            mode = "live"
        except (Exception, SystemExit) as exc:             # Ebay() exits on a rejected token
            log.warning("live fetch failed (%s); using the recorded fetch", exc.__class__.__name__)
    if mode == "live":
        fresh = await _drop_reused_photos(market, [r for r in new if r not in stored])
        _write_records(stored + fresh)
        records = [r for r in new if r in stored or r in fresh]
    else:
        _write_records(stored)
        records = _recorded(cap)
    log.info("fetch_live query=%r cap=%d mode=%s returned=%d", query, cap, mode, len(records))
    pairs = []
    for r in records:
        listing, seller = Listing.model_validate(r["listing"]), Seller.model_validate(r["seller"])
        await market.add_listing(listing, seller)
        pairs.append((listing, seller))
    return pairs, mode


class _LegacyIds(set):
    """eBay item ids appear as "v1|123|0" in the API and as "123" in a listing URL; match either form."""

    def __contains__(self, item_id: object) -> bool:
        s = str(item_id)
        return super().__contains__(s) or (s.count("|") == 2 and super().__contains__(s.split("|")[1]))


async def _drop_reused_photos(market, records: list[dict]) -> list[dict]:
    """Dedupe by image: drop a fetched listing whose first photo is one we already store (same item re-listed
    under another id, or already in the dataset), and delete its downloaded photos."""
    stored_paths = {p for l in await market.all_active() for p in l.image_paths[:1]}
    stored = await asyncio.to_thread(photo_hashes, market, stored_paths)
    kept: list[dict] = []
    for r in records:
        first = set(r["listing"]["image_paths"][:1])
        mine = await asyncio.to_thread(photo_hashes, market, first)
        if any(same_photo(h, other) for h in mine.values() for other in stored.values()):
            for rel in r["listing"]["image_paths"]:
                (data_dir() / rel).unlink(missing_ok=True)
            continue
        stored.update(mine)
        kept.append(r)
    return kept
