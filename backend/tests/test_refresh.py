"""Refresh detector: removal, relist by reused photo, live price change; each change reported once."""
import json

import pytest
from PIL import Image, ImageDraw

from deadlang.marketplace import client as client_mod, live, refresh
from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from tests.conftest import make_listing, make_seller


def picture(path, seed: int):
    img = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(img)
    for k in range(4):
        x, y = (seed * 37 + k * 53) % 96, (seed * 71 + k * 29) % 96
        draw.rectangle([x, y, x + 20 + 6 * k, y + 16 + 5 * k], fill=(seed * 40 % 255, k * 60, 30))
    img.save(path, "JPEG", quality=85)


@pytest.fixture
def market(tmp_path, monkeypatch):
    (tmp_path / "images").mkdir()
    picture(tmp_path / "images" / "a.jpg", 1)
    picture(tmp_path / "images" / "b.jpg", 2)
    (tmp_path / "images" / "a_copy.jpg").write_bytes((tmp_path / "images" / "a.jpg").read_bytes())
    listings = [make_listing("L1", "S1", "Carved bone netsuke", price=900.0, image_paths=["images/a.jpg"]),
                make_listing("L2", "S1", "Resin figurine", price=20.0, image_paths=["images/b.jpg"]),
                make_listing("L3", "S2", "Carved bone netsuke again", price=880.0, image_paths=["images/a_copy.jpg"],
                             status="hidden", relist_of="L1")]
    (tmp_path / "listings.jsonl").write_text("".join(l.model_dump_json() + "\n" for l in listings))
    m = LocalMarketplaceClient(MarketplaceStore(listings, [make_seller("S1"), make_seller("S2")]), tmp_path)
    monkeypatch.setattr(client_mod, "_client", m)
    monkeypatch.setattr(client_mod, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(refresh, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(live, "data_dir", lambda: tmp_path)
    refresh.reset()
    yield m
    refresh.reset()


async def active_ids(m):
    return [l.id for l in await m.all_active()]


async def test_nothing_changed(market):
    assert await refresh.refresh_listings(await active_ids(market)) == []


async def test_removal_is_reported_once_with_time_and_snapshot_hash(market):
    await market.remove_listing("L2")
    changes = await refresh.refresh_listings(await active_ids(market))      # the caller can no longer name L2
    assert [(c.listing_id, c.kind) for c in changes] == [("L2", "removed")]
    assert changes[0].at and len(changes[0].old["snapshot_sha256"]) == 64 and changes[0].new == {"status": "removed"}
    assert await refresh.refresh_listings(await active_ids(market)) == []


async def test_relist_is_matched_by_its_reused_photo(market):
    assert await market.remove_listing("L1") == "L3"
    changes = await refresh.refresh_listings(await active_ids(market))
    assert [(c.listing_id, c.kind) for c in changes] == [("L1", "removed"), ("L3", "relisted")]
    assert changes[1].old == {"listing_id": "L1"} and changes[1].new["seller_id"] == "S2"
    assert await refresh.refresh_listings(await active_ids(market)) == []


async def test_demo_reset_is_not_reported_as_a_change(market):
    await market.remove_listing("L1")
    await refresh.refresh_listings(await active_ids(market))
    await market.reset_demo()
    assert await refresh.refresh_listings(await active_ids(market)) == []
    await market.remove_listing("L1")                                     # and it can be detected again
    assert [c.kind for c in await refresh.refresh_listings(await active_ids(market))] == ["removed", "relisted"]


class FakeEbay:
    answers: dict[str, tuple[int, dict]] = {}

    def item_status(self, item_id):
        return self.answers[item_id]


async def test_live_price_change_removal_and_unknown(market, tmp_path, monkeypatch):
    live_listing = make_listing("LV0001", "S-live-ab12", "Bone carving", price=50.0, origin="live")
    await market.add_listing(live_listing, make_seller("S-live-ab12"))
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "listings.jsonl").write_text(json.dumps({
        "listing": live_listing.model_dump(mode="json"), "seller": make_seller("S-live-ab12").model_dump(mode="json"),
        "source_item_id": "v1|1|0", "fetched_at": "2099-01-01T00:00:00+00:00", "snapshot_sha256": "f" * 64}) + "\n")
    monkeypatch.setattr(refresh, "Ebay", FakeEbay)
    monkeypatch.setattr(FakeEbay, "configured", staticmethod(lambda: True), raising=False)

    FakeEbay.answers = {"v1|1|0": (200, {"price": {"value": "50.00", "currency": "USD"}})}
    assert await refresh.refresh_listings(["LV0001"]) == []
    FakeEbay.answers = {"v1|1|0": (429, {})}                              # rate limited: unknown, not a change
    assert await refresh.refresh_listings(["LV0001"]) == []
    FakeEbay.answers = {"v1|1|0": (200, {"price": {"value": "35.00", "currency": "USD"}})}
    changes = await refresh.refresh_listings(["LV0001"])
    assert [(c.kind, c.old, c.new) for c in changes] == [("price_changed", {"price_usd": 50.0}, {"price_usd": 35.0})]
    FakeEbay.answers = {"v1|1|0": (404, {})}
    changes = await refresh.refresh_listings(["LV0001"])
    assert [c.kind for c in changes] == ["removed"] and changes[0].old["snapshot_sha256"] == "f" * 64
    assert await refresh.refresh_listings(["LV0001"]) == []
