"""In-memory marketplace: the fixed dataset plus the demo's remove/relist state."""
from __future__ import annotations

from pathlib import Path

from deadlang.schemas import Listing, Seller


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
        return cls([Listing.model_validate_json(r) for r in rows("listings.jsonl")],
                   [Seller.model_validate_json(r) for r in rows("sellers.jsonl")])

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
