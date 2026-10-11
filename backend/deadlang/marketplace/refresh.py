"""Refresh: re-check listings against their source and report what changed (contract: v2 plan 00 §4.4).

- Demo lane: the source is the marketplace store. A listing's first-seen state comes from the stored dataset
  (data/listings.jsonl), so a removal made through the admin path is seen on the next refresh.
- Live lane: the source is the eBay API. The item is re-fetched by id; 404 means removed, a different price
  means price_changed. Any other answer (rate limit, outage, no credentials) is "unknown", never a change.

Each change is reported once. A listing that was tracked and has since been removed is reported even if the
caller did not name it, because a caller that lists active listings can no longer see it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from deadlang.marketplace import live
from deadlang.marketplace.client import data_dir, get_marketplace_client
from deadlang.marketplace.ebay import Ebay
from deadlang.schemas import now_iso
from deadlang.specialists.network import photo_hashes, same_photo


class ListingChange(BaseModel):
    listing_id: str
    kind: Literal["price_changed", "removed", "relisted"]
    at: str = Field(default_factory=now_iso)
    old: Any = None
    new: Any = None


_seen: dict[str, dict] = {}        # listing id -> {"status", "price_usd", "snapshot_sha256"} as last reported


def reset() -> None:
    """Forget what has been reported (tests, or a demo reset)."""
    _seen.clear()


def _baseline() -> dict[str, dict]:
    """First-seen state of every stored listing, with the SHA-256 of its stored row (chain of custody)."""
    if not _seen:
        for line in (data_dir() / "listings.jsonl").read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                _seen[row["id"]] = {"status": row["status"], "price_usd": row["price_usd"],
                                    "snapshot_sha256": hashlib.sha256(line.encode()).hexdigest()}
        for r in live.load_records():
            _seen.setdefault(r["listing"]["id"], {"status": "active", "price_usd": r["listing"]["price_usd"],
                                                  "snapshot_sha256": r["snapshot_sha256"]})
    return _seen


async def _relist_of(market, listing, removed_ids: list[str]) -> str | None:
    """The removed listing whose photo this newly visible listing reuses (as in demo case D3), if any."""
    removed = [await market.get_listing_snapshot(i) for i in removed_ids]
    hashes = await asyncio.to_thread(photo_hashes, market, {p for l in [listing, *removed] for p in l.image_paths})
    for old in removed:
        if old.seller_id != listing.seller_id and any(
                same_photo(hashes[a], hashes[b]) for a in listing.image_paths for b in old.image_paths
                if a in hashes and b in hashes):
            return old.id
    return None


def _live_source_state(ebay: Ebay, item_id: str) -> dict | None:
    status, body = ebay.item_status(item_id)
    if status == 404:
        return {"status": "removed"}
    if status == 200 and (body.get("price") or {}).get("currency") == "USD":
        return {"status": "active", "price_usd": round(float(body["price"]["value"]), 2)}
    return None                                            # unknown: not evidence of anything


async def refresh_listings(listing_ids: list[str]) -> list[ListingChange]:
    market = get_marketplace_client()
    seen = _baseline()
    records = {r["listing"]["id"]: r for r in live.load_records()}
    ebay = Ebay() if records and Ebay.configured() else None

    # Current state of every listing we check: the ones asked for, plus every tracked demo-lane listing.
    now: dict[str, dict] = {}
    listings = {}
    for listing_id in dict.fromkeys([*listing_ids, *(i for i in seen if i not in records)]):
        try:
            listing = listings[listing_id] = await market.get_listing_snapshot(listing_id)
        except KeyError:
            continue
        if listing_id in records:
            r = records[listing_id]
            seen.setdefault(listing_id, {"status": "active", "price_usd": r["listing"]["price_usd"],
                                         "snapshot_sha256": r["snapshot_sha256"]})
            state = await asyncio.to_thread(_live_source_state, ebay, r["source_item_id"]) if ebay else None
            if state is not None:
                now[listing_id] = {"price_usd": seen[listing_id]["price_usd"], **state}
        else:
            now[listing_id] = {"status": listing.status, "price_usd": listing.price_usd}

    changes: list[ListingChange] = []
    for listing_id, state in now.items():                  # removals and price changes first
        before = seen.get(listing_id)
        if before is None:
            continue
        if before["status"] == "active" and state["status"] == "removed":
            changes.append(ListingChange(listing_id=listing_id, kind="removed",
                                         old={"status": "active", "snapshot_sha256": before["snapshot_sha256"]},
                                         new={"status": "removed"}))
        elif before["status"] == state["status"] == "active" and before["price_usd"] != state["price_usd"]:
            changes.append(ListingChange(listing_id=listing_id, kind="price_changed",
                                         old={"price_usd": before["price_usd"]}, new={"price_usd": state["price_usd"]}))

    removed = [i for i, s in seen.items() if s["status"] == "removed"] + [c.listing_id for c in changes if c.kind == "removed"]
    for listing_id, state in now.items():                  # then listings that became visible: relists?
        before = seen.get(listing_id)
        if state["status"] == "active" and (before is None or before["status"] == "hidden"):
            old_id = await _relist_of(market, listings[listing_id], [i for i in removed if i not in records])
            if old_id:
                changes.append(ListingChange(listing_id=listing_id, kind="relisted", old={"listing_id": old_id},
                                             new={"listing_id": listing_id, "seller_id": listings[listing_id].seller_id}))

    for listing_id, state in now.items():                  # remember, so each change is reported once
        entry = seen.setdefault(listing_id, {"snapshot_sha256": hashlib.sha256(
            listings[listing_id].model_dump_json().encode()).hexdigest()})
        entry.update(status=state["status"], price_usd=state["price_usd"])
    return changes
