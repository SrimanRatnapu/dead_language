"""Shared marketplace fixtures for Person A's tests."""
import pytest

from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import Listing, Seller


def make_listing(id: str, seller_id: str, title: str, description: str = "", price: float = 50.0, **kw) -> Listing:
    from deadlang.textparse import item_type, stated_material
    return Listing(id=id, marketplace="manual", seller_id=seller_id, title=title, description=description,
                   price_usd=price, category="Antiques",
                   stated_material=kw.pop("stated_material", stated_material(title, description)),
                   item_type=kw.pop("item_type", item_type(title, description)),
                   ship_from=kw.pop("ship_from", "US-CA"), posted_at="2026-10-01T00:00:00+00:00", **kw)


def make_seller(id: str) -> Seller:
    return Seller(id=id, name=f"seller_{id.lower()}", location="US", joined="2024-01-01T00:00:00+00:00")


@pytest.fixture
def store() -> MarketplaceStore:
    """4 listings: L1 and L2 by S1, L3 by S2, L4 a hidden relist of L1 by S3."""
    return MarketplaceStore(
        [make_listing("L1", "S1", "Carved bone netsuke", "old bone netsuke of a rat", 900.0),
         make_listing("L2", "S1", "Resin figurine", "small resin figure", 20.0),
         make_listing("L3", "S2", "Bone bead necklace", "hand carved beads", 35.0),
         make_listing("L4", "S3", "Carved bone netsuke rat", "old bone netsuke", 880.0,
                      status="hidden", relist_of="L1")],
        [make_seller("S1"), make_seller("S2"), make_seller("S3")])
