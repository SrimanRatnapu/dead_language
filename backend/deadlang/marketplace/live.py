"""Live lane: a capped fetch of real listings from the eBay Browse API, or a recorded fetch when the API is
unavailable. The result always says which of the two it is; a recorded result is never presented as live.

Limits (ours, on top of eBay's): at most MAX_CAP listings per call, at most MAX_PAGES search pages, one request
per 0.1 s, at most 3 photos per listing. Official API only.

What is kept: data/live/listings.jsonl (one record per listing: the listing, its pseudonymous seller, the eBay
item id, the fetch time and a SHA-256 of the raw API response) and photos under data/images/live/. The raw
response and the seller's real username are NOT kept. Records older than RETENTION_DAYS are purged on each fetch.
Nothing here ever touches data/listings.jsonl or data/labels.csv.

Follow-up fetch (fetch_related): when a live listing is flagged, fetch that seller's other listings and listings
that use the same distinctive wording. The seller's real username is read from eBay for that one search and is
not stored, logged or returned. Its limits are the FOLLOW_UP_* constants below.
"""
from __future__ import annotations

import asyncio
from itertools import zip_longest
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import logging
import re
import shutil
import time
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from deadlang.marketplace.client import data_dir, get_marketplace_client
from deadlang.marketplace.ebay import Ebay, normalize
from deadlang.schemas import Listing, Seller, now_iso
from deadlang.specialists.network import STOPWORDS, photo_hashes, same_photo, token_runs
from deadlang.textparse import item_type, stated_material

log = logging.getLogger("deadlang.live")
MAX_CAP = 50
MAX_PAGES = 3
RETENTION_DAYS = 30
SALT = "deadlang"
RECORDED = Path(__file__).resolve().parents[3] / "fixtures" / "live_recorded.jsonl"
RECORDED_IMAGES = RECORDED.parent / "live_recorded_images"

# Follow-up fetch, per flagged listing. The caller adds its own ceiling on listings added per batch.
FOLLOW_UP_SELLER_MAX = 10        # the seller's other listings
FOLLOW_UP_CATEGORY_LEVELS = 3    # seller search: the listing's own category, then up to two parent categories
FOLLOW_UP_TERMS = 2              # word pairs actually used
FOLLOW_UP_TERM_TRIES = 3         # word pairs tried to find those (one search request each)
FOLLOW_UP_PER_TERM = 10          # listings kept per word pair
FOLLOW_UP_MAX_TOTAL = 25         # a pair found in more titles than this, in that category, is ordinary wording: skipped
FOLLOW_UP_COMMON_SHARE = 0.05    # a word used by more than this share of the listings we hold is too common to search on

# Discovery sweeps: (eBay category id, price floor in USD). Search by where the item has to be listed and what it
# costs, not by words. Floors are about 3x the stored median for the material; tune after real sweeps.
SWEEPS: dict[str, list[tuple[str, int]]] = {
    "netsuke":   [("37938", 300), ("29453", 300)],
    "figures":   [("162973", 400), ("29445", 400), ("73466", 400)],
    "bracelets": [("262003", 100)],
}
DEFAULT_SWEEP = "netsuke"

_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _lock() -> asyncio.Lock:
    """One fetch at a time: every fetch reads, extends and rewrites data/live/listings.jsonl and hands out the
    next LV id, so two at once would overwrite each other. (One lock per event loop; the API has one loop.)"""
    return _locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())


def _records_file() -> Path:
    return data_dir() / "live" / "listings.jsonl"


def load_records() -> list[dict]:
    """Every live listing kept on disk: {listing, seller, source_item_id, category_id, fetched_at,
    snapshot_sha256}. (category_id is missing from records fetched before the follow-up fetch existed.)"""
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


def _encode_photo(raw: bytes) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((800, 800))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return None                                        # an unreadable photo is skipped, never fatal


WORKERS = 6     # parallel item/photo fetches: ~60 eBay calls/s is far under the Browse API's daily quota, and each call still sleeps 0.1 s


def _item(ebay: Ebay, item_id: str) -> tuple[int, dict]:
    """Blocking: (HTTP status, body) for one item, backing off and retrying while eBay answers 429."""
    for attempt in range(3):
        status, raw = ebay.item_status(item_id)
        if status != 429:
            break
        time.sleep(2 ** attempt)                           # rate limited: back off and retry
    return status, raw


def _photo_bodies(ebay: Ebay, n: dict) -> list[bytes | None]:
    """Blocking: the item's photos, decoded and resized here (off the main thread); None for any that fail."""
    def download(url: str) -> bytes | None:
        try:
            return _encode_photo(ebay.http.get(re.sub(r"s-l\d+", "s-l800", url)).content)   # we shrink to 800 px anyway: smaller download
        except Exception:
            return None
    return [download(u) for u in n["image_urls"]]


def _load_item(ebay: Ebay, item_id: str, query: str) -> tuple[dict, dict, list[bytes | None]] | None:
    """Blocking, runs in a worker thread: one item's details and photo bytes, or None if unusable."""
    status, raw = _item(ebay, item_id)
    n = normalize(raw, query) if status == 200 else None
    if n is None:
        return None                                        # gone, not priced in USD, or untitled
    return raw, n, _photo_bodies(ebay, n)


def _make_record(lid: str, item_id: str, raw: dict, n: dict, bodies: list[bytes | None]) -> dict:
    """Store the photos and build the on-disk record for one fetched item. The seller's username is used only
    to derive the pseudonym and to redact it from the text; it is not part of the record."""
    paths = []
    for body in bodies:
        rel = f"images/live/{lid}_{len(paths)}.jpg"
        if body:
            (data_dir() / rel).parent.mkdir(parents=True, exist_ok=True)
            (data_dir() / rel).write_bytes(body)
            paths.append(rel)
    username = n["seller_handle"] or f"unknown-{item_id}"
    seller = _seller(username, n["seller_feedback"], n["seller_location"])
    for field in ("title", "description"):                 # sellers often name their own shop in the text
        n[field] = re.sub(rf"(?<![A-Za-z0-9]){re.escape(username)}(?![A-Za-z0-9])", seller.name, n[field], flags=re.I)
    listing = Listing(
        id=lid, marketplace="ebay", seller_id=seller.id, title=n["title"], description=n["description"],
        price_usd=round(n["price_usd"], 2), category=n["category"],
        stated_material=stated_material(n["title"], n["description"]),
        item_type=item_type(n["title"], n["description"]), ship_from=n["ship_from"],
        language=_language(n["title"] + " " + n["description"]), image_paths=paths,
        posted_at=n["posted_at"] or now_iso(), source_url=n["source_url"], origin="live")
    return {"listing": listing.model_dump(mode="json"), "seller": seller.model_dump(mode="json"),
            "source_item_id": item_id, "category_id": raw.get("categoryId"), "fetched_at": now_iso(),
            "snapshot_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()}


def _keyword_hits(ebay: Ebay, query: str) -> list[dict]:
    """Blocking. eBay's relevance order for one keyword query, up to MAX_PAGES pages."""
    hits: list[dict] = []
    for page in range(MAX_PAGES):
        got = ebay.search(query, limit=50, offset=page * 50)
        hits += got
        if len(got) < 50:
            break
    return hits


def _sweep_hits(ebay: Ebay, entries: list[tuple[str, int]], cap: int) -> list[dict]:
    """Blocking. Newest-first listings for each (category, price floor), no keyword, interleaved so every entry
    gets an even share of the cap (an entry that runs dry hands its share to the others). Raises if nothing
    came back at all: a failed search must not look like an empty marketplace."""
    streams: list[list[dict]] = []
    for category, floor in entries:
        streams.append([])
        for page in range(MAX_PAGES):
            _, got = ebay.search_page(category_ids=category, filter=f"price:[{floor}..],priceCurrency:USD",
                                      sort="newlyListed", offset=page * 50)
            streams[-1] += got
            if len(got) < 50 or len(streams[-1]) >= 2 * cap:     # spare hits cover items that turn out unusable
                break
    hits = [h for group in zip_longest(*streams) for h in group if h is not None]
    if not hits:
        raise RuntimeError("sweep search returned nothing")
    return hits


def _fetch_from_ebay(query: str | None, cap: int, known_items: set[str], next_number: int,
                     fetched_before: dict[str, dict], sweep: list[tuple[str, int]] | None = None) -> list[dict]:
    """Blocking. Up to `cap` records for the keyword query, or for a sweep (category + price floor, no keyword):
    items fetched before are reused as they are (no duplicate is stored), items already in the stored dataset are
    skipped. Raises if the API cannot be used."""
    ebay = Ebay()
    ebay._token()                                          # fail here, before any work, if the keys are bad
    records: list[dict] = []
    old_ids = {r["listing"]["id"] for r in fetched_before.values()}
    candidates: list[str] = []                             # new item ids, in search order
    query = query or ""
    for hit in _sweep_hits(ebay, sweep, cap) if sweep else _keyword_hits(ebay, query):
        item_id = hit.get("itemId")
        if item_id in fetched_before:
            if fetched_before[item_id] not in records and len(records) < cap:
                records.append(fetched_before[item_id])
        elif item_id and item_id not in known_items and item_id not in candidates:
            candidates.append(item_id)                     # dedupe by item id against the stored dataset
    with ThreadPoolExecutor(WORKERS) as pool:
        while candidates and len(records) < cap:
            batch, candidates = candidates[:cap - len(records)], candidates[cap - len(records):]
            for item_id, loaded in zip(batch, pool.map(lambda i: _load_item(ebay, i, query), batch)):
                if loaded is None:
                    continue
                raw, n, bodies = loaded
                lid = f"LV{next_number + sum(r['listing']['id'] not in old_ids for r in records):04d}"
                records.append(_make_record(lid, item_id, raw, n, bodies))
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


async def fetch_live(query: str | None = None, cap: int = 25,
                     sweep: str | None = None) -> tuple[list[tuple[Listing, Seller | None]], str]:
    """Up to `cap` (max 50) listings, each already added to the marketplace store. `query`: a keyword search, as
    always. `sweep`: a named category + price-floor sweep from SWEEPS, no keyword, newest first. Neither: the
    default sweep. Both, or an unknown sweep name: ValueError.

    Returns (pairs, mode). mode is "live" when they came from the eBay API just now and "recorded" when the API
    could not be used (no credentials, or it failed) and the saved fetch was returned instead.
    """
    if query and sweep:
        raise ValueError("give a query or a sweep, not both")
    if sweep is not None and sweep not in SWEEPS:
        raise ValueError(f"unknown sweep {sweep!r}")
    async with _lock():
        return await _fetch_live(query, cap, SWEEPS[sweep or DEFAULT_SWEEP] if not query else None)


async def _fetch_live(query: str | None, cap: int, sweep: list[tuple[str, int]] | None) -> tuple[list[tuple[Listing, Seller | None]], str]:
    cap = max(1, min(cap, MAX_CAP))
    market = get_marketplace_client()
    stored = purge_expired(load_records())
    mode, new = "recorded", []
    if Ebay.configured():
        fetched_before = {r["source_item_id"]: r for r in stored}
        next_number = 1 + max((int(r["listing"]["id"][2:]) for r in stored), default=0)
        try:
            new = await asyncio.to_thread(_fetch_from_ebay, query, cap, await _dataset_item_ids(market), next_number,
                                          fetched_before, sweep)
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
    log.info("fetch_live query=%r sweep=%s cap=%d mode=%s returned=%d", query, sweep, cap, mode, len(records))
    pairs = []
    for r in records:
        listing, seller = Listing.model_validate(r["listing"]), Seller.model_validate(r["seller"])
        await market.add_listing(listing, seller)
        pairs.append((listing, seller))
    return pairs, mode


async def _dataset_item_ids(market) -> "_LegacyIds":
    """eBay item ids of listings already in the stored dataset (read from their listing URLs)."""
    return _LegacyIds({l.source_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0] for l in await market.all_active()
                       if l.origin == "demo" and l.source_url})


class _LegacyIds(set):
    """eBay item ids appear as "v1|123|0" in the API and as "123" in a listing URL; match either form."""

    def __contains__(self, item_id: object) -> bool:
        s = str(item_id)
        return super().__contains__(s) or (s.count("|") == 2 and super().__contains__(s.split("|")[1]))


async def _drop_reused_photos(market, records: list[dict], same_seller_only: bool = False) -> list[dict]:
    """Dedupe by image: drop a fetched listing whose first photo is one we already store (same item re-listed
    under another id, or already in the dataset), and delete its downloaded photos.

    same_seller_only=True keeps a listing that reuses ANOTHER seller's photo: for a follow-up fetch that is the
    interesting case (the same piece under a second account), not a duplicate."""
    owners = {l.image_paths[0]: l for l in await market.all_active() if l.image_paths}
    stored = await asyncio.to_thread(photo_hashes, market, set(owners))
    names: dict[str, str] = {}
    kept: list[dict] = []
    for r in records:
        first = set(r["listing"]["image_paths"][:1])
        mine = await asyncio.to_thread(photo_hashes, market, first)
        duplicate = False
        for path, other in stored.items():
            if not any(same_photo(h, other) for h in mine.values()):
                continue
            if not same_seller_only:
                duplicate = True
                break
            owner = owners.get(path)
            if owner is not None and owner.seller_id not in names:
                names[owner.seller_id] = (await market.get_seller(owner.seller_id)).name
            if owner is None or names[owner.seller_id] == r["seller"]["name"]:      # pseudonyms are per real seller
                duplicate = True
                break
        if duplicate:
            for rel in r["listing"]["image_paths"]:
                (data_dir() / rel).unlink(missing_ok=True)
            continue
        stored.update(mine)
        for path in first:
            owners[path] = Listing.model_validate(r["listing"])
            names[r["listing"]["seller_id"]] = r["seller"]["name"]
        kept.append(r)
    return kept


# ------------------------------------------------------------------ follow-up: listings related to a flagged one
# Words our parser already reads as a material or an item type. Every listing in the category has them.
GENERIC = frozenset("""tagua vegetable ivory corozo faux imitation resin polyresin plastic celluloid color colour
colored coloured tone white finish bone bones bovine boxwood wood wooden netsuke netsukes bangle bangles bracelet
bracelets bead beads necklace necklaces pendant pendants mala ring rings earring earrings okimono figurine
figurines figure figures statue statues carving carvings sculpture sculptures""".split())


def _title_words(title: str) -> list[str]:
    return [t for run in token_runs(title, "") for t in run]


def distinctive_terms(listing: Listing, others: list[Listing], max_terms: int = FOLLOW_UP_TERM_TRIES) -> list[str]:
    """Search terms made only of words in this listing's own title: its rarest words, two at a time, rarest
    pair first ("dakota nantucket", then the next two, ...). Rarity is counted over `others`, the listings we
    hold. Code, not a model: the same inputs always give the same terms, and nothing a seller writes can add a
    word that is not literally in the title.

    Left out: filler words, numbers and codes, words under 3 letters, the material and item-type words our
    parser already reads (bone, netsuke, carving, ...), and any word that more than 5% of the listings we hold
    use (at least 2 listings): "vintage", "japanese" and "out" cannot make a listing distinctive.
    Titles only, because eBay's keyword search reads titles; its description search proved unreliable.
    """
    seen_in: dict[str, int] = {}
    others = [l for l in others if l.id != listing.id]
    for l in others:
        for token in {t for run in token_runs(l.title, l.description) for t in run}:
            seen_in[token] = seen_in.get(token, 0) + 1
    too_common = max(2, FOLLOW_UP_COMMON_SHARE * len(others))
    in_title = list(dict.fromkeys(t for t in _title_words(listing.title)
                                  if t.isalpha() and len(t) >= 3 and t not in STOPWORDS and t not in GENERIC
                                  and seen_in.get(t, 0) <= too_common))
    rarest = sorted(in_title, key=lambda t: seen_in.get(t, 0))     # stable: equally rare words keep their title order
    pairs = [rarest[i:i + 2] for i in range(0, len(rarest) - 1, 2)][:max_terms]
    return [" ".join(sorted(pair, key=in_title.index)) for pair in pairs]       # each pair reads as it does in the title


def _related_from_ebay(record: dict, terms: list[str], limit: int, exclude: set[str], known_items: set[str],
                       fetched_before: dict[str, dict], next_number: int) -> tuple[list[dict], list[dict]]:
    """Blocking. Up to `limit` records related to `record`, with why each was fetched:
    (records, [{"listing_id", "found_via": "seller" | "keyword", "term": str | None}]). Raises if the API
    cannot be used at all. Items already in the stored dataset are skipped; items fetched before are reused."""
    ebay = Ebay()
    ebay._token()                                          # fail here, before any work, if the keys are bad
    records: list[dict] = []
    found: list[dict] = []
    seen = {record["source_item_id"]}                      # never fetch the flagged listing itself, or an item twice

    def take(hit: dict, via: str, term: str | None) -> bool:
        """Turn one search hit into a record if it is usable. True if it was added."""
        item_id = hit.get("itemId")
        if not item_id or item_id in seen or hit.get("adultOnly"):
            return False
        seen.add(item_id)
        if item_id in fetched_before:                      # we already hold it: reuse, never store a duplicate
            r = fetched_before[item_id]
            if r["listing"]["id"] in exclude:
                return False
        elif item_id in known_items:
            return False                                   # already in the stored dataset (the demo lane)
        else:
            status, raw = _item(ebay, item_id)
            n = normalize(raw, term or "seller") if status == 200 else None
            if n is None:
                return False                               # gone, not priced in USD, or untitled
            fresh = sum(x["source_item_id"] not in fetched_before for x in records)
            r = _make_record(f"LV{next_number + fresh:04d}", item_id, raw, n, _photo_bodies(ebay, n))
        records.append(r)
        found.append({"listing_id": r["listing"]["id"], "found_via": via, "term": term})
        return True

    # The flagged item is read again for two things eBay only gives per item: its category ids and its seller's
    # username. The username is used for the seller filter below and goes nowhere else: not stored, not logged,
    # not returned.
    status, raw = _item(ebay, record["source_item_id"])
    username = (raw.get("seller") or {}).get("username") if status == 200 else None
    categories = [c for c in (raw.get("categoryIdPath") or raw.get("categoryId") or "").split("|") if c]
    leaf = categories[-1] if categories else record.get("category_id")

    # ---- the seller's other listings, nearest category first
    seller_quota = min(FOLLOW_UP_SELLER_MAX, limit)
    if username:
        for category in list(reversed(categories))[:FOLLOW_UP_CATEGORY_LEVELS]:
            if len(records) >= seller_quota:
                break
            _, hits = ebay.search_page(category_ids=category, filter=f"sellers:{{{username}}}", sort="newlyListed")
            for hit in hits:
                if len(records) >= seller_quota:
                    break
                if (hit.get("seller") or {}).get("username") == username:      # believe the filter only if it shows
                    take(hit, "seller", None)

    # ---- other listings in the same category whose titles use the same distinctive words
    used = 0                                               # word pairs that actually brought something in
    for term in terms[:FOLLOW_UP_TERM_TRIES] if leaf else []:
        if used >= FOLLOW_UP_TERMS or len(records) >= limit:
            break
        total, hits = ebay.search_page(q=term, category_ids=leaf)
        if total > FOLLOW_UP_MAX_TOTAL:
            continue                                       # ordinary wording for this category: means nothing
        quota = min(FOLLOW_UP_PER_TERM, limit - len(records))     # the rarest pair is served first, in full
        words, kept = set(term.split()), 0
        for hit in hits:
            if kept >= quota:
                break
            if words <= set(_title_words(hit.get("title") or "")):              # eBay also matches variants: we do not
                kept += take(hit, "keyword", term)
        used += kept > 0
    return records, found


async def fetch_related(listing_id: str, limit: int = 20,
                        exclude: frozenset[str] | set[str] = frozenset()) -> tuple[list[tuple[Listing, Seller | None]], list[dict]]:
    """Follow-up fetch for a flagged live listing: the same seller's other listings, then listings in the same
    eBay category whose titles share its most distinctive words (see distinctive_terms). Every returned
    listing is already in the marketplace store.

    Returns (pairs, found); found[i] = {"listing_id", "found_via": "seller" | "keyword", "term": str | None}
    says why pairs[i] is there. `limit` caps how many are returned; listings whose ids are in `exclude` (e.g.
    already in the batch) are left out and do not count. Returns ([], []) when the listing is not a live
    fetch of ours or the eBay API cannot be used: a follow-up is never faked from recorded data.
    """
    limit = max(0, min(limit, FOLLOW_UP_SELLER_MAX + FOLLOW_UP_TERMS * FOLLOW_UP_PER_TERM))
    async with _lock():
        stored = load_records()
        record = next((r for r in stored if r["listing"]["id"] == listing_id), None)
        if record is None or limit == 0 or not Ebay.configured():
            return [], []
        market = get_marketplace_client()
        terms = distinctive_terms(Listing.model_validate(record["listing"]), await market.all_active())
        fetched_before = {r["source_item_id"]: r for r in stored}
        next_number = 1 + max((int(r["listing"]["id"][2:]) for r in stored), default=0)
        try:
            records, found = await asyncio.to_thread(
                _related_from_ebay, record, terms, limit, exclude=set(exclude),
                known_items=await _dataset_item_ids(market), fetched_before=fetched_before, next_number=next_number)
        except (Exception, SystemExit) as exc:             # Ebay() exits on a rejected token
            # Class and code location only: an HTTP error message can carry the request URL, and with it a username.
            tb = exc.__traceback__
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb else "?"
            log.warning("follow-up fetch for %s failed (%s at %s)", listing_id, exc.__class__.__name__, where)
            return [], []
        fresh = await _drop_reused_photos(market, [r for r in records if r not in stored], same_seller_only=True)
        _write_records(stored + fresh)
        why = {f["listing_id"]: f for f in found}
        pairs = []
        for r in records:
            if r in stored or r in fresh:
                listing, seller = Listing.model_validate(r["listing"]), Seller.model_validate(r["seller"])
                await market.add_listing(listing, seller)
                pairs.append((listing, seller))
        found = [why[l.id] for l, _ in pairs]
        log.info("fetch_related %s: %d by the same seller, %d by title words %s", listing_id,
                 sum(f["found_via"] == "seller" for f in found), sum(f["found_via"] == "keyword" for f in found),
                 sorted({f["term"] for f in found if f["term"]}))
        return pairs, found


# ------------------------------------------------------------------ review order
# Materials a disguised item would claim to be: only these can be "ivory sold as something cheaper".
DISGUISE_MATERIALS = frozenset({"bone", "unknown", "ivory_color", "ivory_mentioned"})


async def rank_for_review(listing_ids: list[str]) -> list[dict]:
    """Order listings for triage, most suspicious first, from facts already computed for free (code, no model):
    a stated material a disguised item would claim, then the Price Checker's ratio to the median for that
    material. Returns [{"listing_id", "ratio", "stated_material", "reason"}] for every id, none dropped: dropping
    is triage's job. Deterministic: ties keep id order."""
    from deadlang.schemas import SpecialistCall
    from deadlang.specialists.price import PriceChecker
    market = get_marketplace_client()
    checker, rows = PriceChecker(market), []
    for lid in listing_ids:
        listing = await market.get_listing_snapshot(lid)
        reply = await checker.run(SpecialistCall(case_id="rank", listing_id=lid, capability="price_check"))
        ratio = reply.drafts[0].data["ratio"] if reply.ok and reply.drafts else None
        material = listing.stated_material
        if material not in DISGUISE_MATERIALS:
            reason = f"stated material {material} is not one a disguised item would claim"
        elif ratio is None:
            reason = f"stated material {material}; too few comparables to price it"
        else:
            reason = f"stated material {material}; {ratio}x the median"
        rows.append({"listing_id": lid, "ratio": ratio, "stated_material": material, "reason": reason})
    rows.sort(key=lambda r: (r["stated_material"] not in DISGUISE_MATERIALS, -(r["ratio"] or 0), r["listing_id"]))
    return rows
