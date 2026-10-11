"""Live connector with a faked eBay client: mode, ids, pseudonyms, hashes, dedupe, caps, recorded fallback."""
import io
import json

import pytest
from PIL import Image

from deadlang.marketplace import client as client_mod, live
from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore, load_demo_set
from tests.conftest import make_listing, make_seller


def jpeg(seed: int) -> bytes:
    img = Image.new("RGB", (64, 64), (seed * 50 % 255, seed * 90 % 255, 40))
    for x in range(0, 64, 8):
        img.putpixel((x, (x * seed) % 64), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def item(n: int, price="45.00", currency="USD", seller="realname_bob") -> dict:
    return {"itemId": f"v1|{n}|0", "title": f"Carved bone netsuke number {n}", "description": "<p>Old bone.</p>",
            "price": {"value": price, "currency": currency}, "image": {"imageUrl": f"https://img.test/{n}.jpg"},
            "seller": {"username": seller, "feedbackScore": 12}, "itemLocation": {"country": "US", "stateOrProvince": "CA"},
            "categoryPath": "Antiques|Asian Antiques", "itemWebUrl": f"https://www.ebay.com/itm/{n}"}


class FakeEbay:
    items = {n: item(n) for n in (1, 2, 3, 4)}
    fail = False

    def __init__(self):
        self.http = self

    def _token(self):
        if FakeEbay.fail:
            raise RuntimeError("token rejected")

    @staticmethod
    def configured():
        return True

    def search(self, query, limit=50, offset=0):
        return [{"itemId": i["itemId"]} for i in self.items.values()] if offset == 0 else []

    searches: list[dict] = []

    def search_page(self, **params):                      # used by sweeps
        FakeEbay.searches.append(params)
        return len(self.items), list(self.items.values())

    def item_status(self, item_id):
        n = int(item_id.split("|")[1])
        return (200, self.items[n]) if n in self.items else (404, {})

    def get(self, url):                                   # photo download
        n = int(url.rsplit("/", 1)[1].split(".")[0])
        return type("R", (), {"content": jpeg(n)})()


@pytest.fixture
def market(tmp_path, monkeypatch):
    stored = make_listing("L1", "S1", "Bone netsuke already in the dataset", source_url="https://www.ebay.com/itm/3")
    m = LocalMarketplaceClient(MarketplaceStore([stored], [make_seller("S1")]), tmp_path)
    monkeypatch.setattr(client_mod, "_client", m)
    monkeypatch.setattr(client_mod, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(live, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(live, "get_marketplace_client", lambda: m)
    monkeypatch.setattr(live, "Ebay", FakeEbay)
    monkeypatch.setattr(FakeEbay, "items", {n: item(n) for n in (1, 2, 3, 4)})
    monkeypatch.setattr(FakeEbay, "fail", False)
    monkeypatch.setattr(FakeEbay, "searches", [])
    return m


async def test_live_fetch_adds_pseudonymized_listings_to_the_store(market, tmp_path):
    pairs, mode = await live.fetch_live("bone netsuke", cap=10)
    assert mode == "live"
    assert [l.id for l, _ in pairs] == ["LV0001", "LV0002", "LV0003"]      # item 3 is already in the dataset
    listing, seller = pairs[0]
    assert (listing.origin, listing.marketplace, listing.stated_material, listing.ship_from) == ("live", "ebay", "bone", "US-CA")
    assert seller.id.startswith("S-live-") and seller.name.startswith("seller_")
    assert (await market.get_listing("LV0001")).title == listing.title and (await market.get_seller(seller.id)).name == seller.name
    assert market.image_path(listing.image_paths[0]).is_file()
    on_disk = (tmp_path / "live" / "listings.jsonl").read_text()
    assert "realname_bob" not in on_disk and "realname_bob" not in json.dumps([l.model_dump() for l, _ in pairs])
    assert len(live.snapshot_hash("LV0001")) == 64 and live.snapshot_hash("L1") is None
    assert not (tmp_path / "phash_cache.json").exists()                   # live photos never enter the committed cache


async def test_cap_is_enforced_and_a_repeat_fetch_reuses_ids(market):
    first, _ = await live.fetch_live("bone netsuke", cap=2)
    assert [l.id for l, _ in first] == ["LV0001", "LV0002"]
    again, mode = await live.fetch_live("bone netsuke", cap=10)
    assert mode == "live" and [l.id for l, _ in again] == ["LV0001", "LV0002", "LV0003"]
    assert len(live.load_records()) == 3
    assert len((await live.fetch_live("bone netsuke", cap=999))[0]) <= live.MAX_CAP


async def test_reused_photo_and_unusable_items_are_dropped(market, monkeypatch):
    items = {1: item(1), 2: item(2, currency="EUR"), 4: item(4), 5: {**item(5), "image": {"imageUrl": "https://img.test/1.jpg"}}}
    monkeypatch.setattr(FakeEbay, "items", items)
    pairs, _ = await live.fetch_live("bone netsuke", cap=10)
    assert [l.source_url[-1] for l, _ in pairs] == ["1", "4"]            # EUR item skipped; item 5 reuses item 1's photo


async def test_recorded_fallback_when_the_api_fails_or_has_no_keys(market, tmp_path, monkeypatch):
    recorded = tmp_path / "rec.jsonl"
    rec = make_listing("LV9001", "S-live-aaaa", "Recorded bone carving", origin="live", image_paths=["images/live/LV9001_0.jpg"])
    recorded.write_text(json.dumps({"listing": rec.model_dump(mode="json"), "seller": make_seller("S-live-aaaa").model_dump(mode="json"),
                                    "source_item_id": "v1|9|0", "fetched_at": "2026-10-10T00:00:00+00:00", "snapshot_sha256": "a" * 64}) + "\n")
    (tmp_path / "recimg").mkdir()
    (tmp_path / "recimg" / "LV9001_0.jpg").write_bytes(jpeg(9))
    monkeypatch.setattr(live, "RECORDED", recorded)
    monkeypatch.setattr(live, "RECORDED_IMAGES", tmp_path / "recimg")
    monkeypatch.setattr(FakeEbay, "fail", True)
    pairs, mode = await live.fetch_live("anything", cap=5)
    assert mode == "recorded" and [l.id for l, _ in pairs] == ["LV9001"]
    assert (await market.get_listing("LV9001")).origin == "live" and market.image_path("images/live/LV9001_0.jpg").is_file()
    monkeypatch.setattr(FakeEbay, "configured", staticmethod(lambda: False))
    assert (await live.fetch_live("anything"))[1] == "recorded"


async def test_old_live_records_are_purged(market, tmp_path):
    await live.fetch_live("bone netsuke", cap=1)
    records = live.load_records()
    records[0]["fetched_at"] = "2020-01-01T00:00:00+00:00"
    photo = tmp_path / records[0]["listing"]["image_paths"][0]
    live._write_records(records)
    assert photo.is_file()
    await live.fetch_live("bone netsuke", cap=1)
    assert not photo.exists() and all(r["fetched_at"] > "2026" for r in live.load_records())


def test_store_runtime_listings_market_stats_and_lanes(market):
    store = market.store
    store.add(make_listing("LV0001", "S-live-1", "Resin duck", price=10.0, origin="live", ship_from="JP"), make_seller("S-live-1"))
    stats = store.market_stats()
    assert stats["by_material"]["bone"] == {"count": 1, "median_price_usd": 50.0}
    assert stats["by_country"]["JP"]["count"] == 1 and stats["by_marketplace"]["manual"]["count"] == 2


def test_committed_demo_set_and_recorded_fixture():
    from pathlib import Path
    data = Path(__file__).resolve().parents[2] / "data"
    rows = json.loads((data / "demo_set.json").read_text())
    ids = load_demo_set(data)
    assert ids == [r["listing_id"] for r in rows] and len(set(ids)) == 12
    outcomes = [r["designed_outcome"] for r in rows]
    assert sorted(set(outcomes)) == ["CONTESTED", "DISMISS", "FILE", "WATCHLIST"]
    assert outcomes.count("DISMISS") == 3 and outcomes.count("CONTESTED") == 2 and outcomes.count("WATCHLIST") == 2
    store = MarketplaceStore.from_dir(data)
    by_role = {r["role"].split(":")[0].split(" ")[0]: store.get_listing(r["listing_id"]) for r in rows}   # every pointer resolves
    assert by_role["non-English"].language != "en"
    assert "ignore all previous instructions" in by_role["injection"].description.lower()
    stored_ids = {json.loads(x)["id"] for x in (data / "listings.jsonl").read_text().splitlines()}
    assert by_role["injection"].id not in stored_ids                      # kept apart from the labeled dataset
    recorded = [json.loads(x) for x in live.RECORDED.read_text().splitlines()]
    assert recorded and all(r["listing"]["origin"] == "live" and r["seller"]["id"].startswith("S-live-") for r in recorded)
    assert all((live.RECORDED_IMAGES / Path(p).name).is_file() for r in recorded for p in r["listing"]["image_paths"])


async def test_sweep_searches_by_category_and_price_without_a_keyword(market):
    pairs, mode = await live.fetch_live(sweep="netsuke", cap=10)
    assert mode == "live" and pairs
    assert len(FakeEbay.searches) == len(live.SWEEPS["netsuke"])
    for p, (category, floor) in zip(FakeEbay.searches, live.SWEEPS["netsuke"]):
        assert "q" not in p and p["category_ids"] == category and p["sort"] == "newlyListed"
        assert p["filter"].startswith(f"price:[{floor}..]")


async def test_query_and_sweep_are_exclusive_and_names_are_checked(market):
    with pytest.raises(ValueError):
        await live.fetch_live("x", sweep="netsuke")
    with pytest.raises(ValueError):
        await live.fetch_live(sweep="nope")


async def test_rank_for_review_puts_disguise_materials_first_and_drops_nothing(market):
    ids = [l.id for l, _ in (await live.fetch_live(cap=4))[0]]
    rows = await live.rank_for_review(ids)
    assert sorted(r["listing_id"] for r in rows) == sorted(ids)
