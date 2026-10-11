"""In-memory marketplace: the fixed dataset plus the demo's remove/relist state."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from deadlang.schemas import Listing, Seller


def load_demo_set(data_dir: Path | None = None) -> list[str]:
    """Listing ids of the curated demo set (data/demo_set.json), in demo order. A pointer list: the rows
    themselves stay in the dataset. Its designed outcomes are for people and evaluation code only."""
    if data_dir is None:
        from deadlang import config
        data_dir = config.DATA_DIR
    return [row["listing_id"] for row in json.loads((Path(data_dir) / "demo_set.json").read_text())]


class ListingRemoved(Exception):
    def __init__(self, listing_id: str):
        super().__init__(f"listing {listing_id} was removed")
        self.listing_id = listing_id


class MarketplaceStore:
    def __init__(self, listings: list[Listing], sellers: list[Seller]):
        self._listings = {l.id: l for l in listings}      # insertion order = file order
        self._sellers = {s.id: s for s in sellers}

    @classmethod
    def from_dir(cls, data_dir: Path) -> MarketplaceStore:
        def rows(name: str) -> list[str]:
            return [line for line in (Path(data_dir) / name).read_text().splitlines() if line.strip()]
        store = cls([Listing.model_validate_json(r) for r in rows("listings.jsonl")],
                    [Seller.model_validate_json(r) for r in rows("sellers.jsonl")])
        # Demo-only listings that are not part of the labeled evaluation set (e.g. the injection attempt).
        extra = Path(data_dir) / "extra" / "listings.jsonl"
        if extra.exists():
            for row in rows("extra/listings.jsonl"):
                record = json.loads(row)
                store.add(Listing.model_validate(record["listing"]), Seller.model_validate(record["seller"]))
        return store

    def add(self, listing: Listing, seller: Seller | None = None) -> None:
        """Add (or replace) one listing at runtime, e.g. a live fetch. Stored files are not touched."""
        if seller is not None:
            self._sellers[seller.id] = seller
        self._listings[listing.id] = listing

    def market_stats(self) -> dict:
        """Counts and median price of active listings by marketplace, country and stated material."""
        groups: dict[str, dict[str, list[float]]] = {"by_marketplace": defaultdict(list), "by_country": defaultdict(list),
                                                     "by_material": defaultdict(list)}
        for l in self.active_listings():
            groups["by_marketplace"][l.marketplace].append(l.price_usd)
            groups["by_country"][l.ship_from.split("-")[0]].append(l.price_usd)
            groups["by_material"][l.stated_material].append(l.price_usd)
        return {name: {key: {"count": len(prices), "median_price_usd": round(statistics.median(prices), 2)}
                       for key, prices in sorted(by.items())} for name, by in groups.items()}

    def get_listing(self, listing_id: str) -> Listing:
        listing = self._listings[listing_id]
        if listing.status == "removed":
            raise ListingRemoved(listing_id)
        if listing.status == "hidden":                     # a hidden relist does not exist yet
            raise KeyError(listing_id)
        return listing

    def get_listing_any_status(self, listing_id: str) -> Listing:
        return self._listings[listing_id]

    def get_seller(self, seller_id: str) -> Seller:
        return self._sellers[seller_id]

    def active_listings(self) -> list[Listing]:
        return [l for l in self._listings.values() if l.status == "active"]

    def seller_listings(self, seller_id: str, include_removed: bool = True) -> list[Listing]:
        wanted = {"active", "removed"} if include_removed else {"active"}
        return [l for l in self._listings.values() if l.seller_id == seller_id and l.status in wanted]

    def search(self, query: str, limit: int = 50) -> list[Listing]:
        words = query.lower().split()
        hits = [l for l in self.active_listings()
                if all(w in f"{l.title} {l.description}".lower() for w in words)]
        return hits[:limit]

    def remove_listing(self, listing_id: str) -> str | None:
        """Mark a listing removed. If a hidden relist was waiting for it, reveal that and return its id."""
        self._listings[listing_id].status = "removed"
        for l in self._listings.values():
            if l.status == "hidden" and l.relist_of == listing_id:
                l.status = "active"
                return l.id
        return None

    def statuses(self) -> dict[str, str]:
        return {l.id: l.status for l in self._listings.values()}

    def reset_demo_state(self, original: dict[str, str]) -> None:
        for listing_id, status in original.items():
            self._listings[listing_id].status = status
