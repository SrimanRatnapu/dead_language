"""The committed dataset must be internally consistent and its demo cases must tell their stories."""
import csv
import json
import re
from pathlib import Path

import pytest

from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import Label, Listing, Seller, SpecialistCall
from deadlang.specialists.legal import LegalTable
from deadlang.specialists.network import LinkedSellers, SellerInventory
from deadlang.specialists.price import PriceChecker
from deadlang.textparse import item_type, stated_material

DATA = Path(__file__).resolve().parents[2] / "data"
pytestmark = pytest.mark.skipif(not (DATA / "listings.jsonl").exists(),
                                reason="dataset not built yet (scripts/build_dataset.py)")


def rows(name):
    return [line for line in (DATA / name).read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def listings():
    return [Listing.model_validate_json(r) for r in rows("listings.jsonl")]


@pytest.fixture(scope="module")
def sellers():
    return [Seller.model_validate_json(r) for r in rows("sellers.jsonl")]


@pytest.fixture(scope="module")
def labels():
    with (DATA / "labels.csv").open(newline="") as f:
        return {r["listing_id"]: Label(listing_id=r["listing_id"], truth=r["truth"],
                                       should_flag=r["should_flag"] == "true", notes=r["notes"])
                for r in csv.DictReader(f)}


@pytest.fixture(scope="module")
def demo():
    return json.loads((DATA / "demo_cases.json").read_text())


@pytest.fixture
def market():
    return LocalMarketplaceClient(MarketplaceStore.from_dir(DATA), DATA)     # fresh state for every test


def call(listing_id, capability, **params):
    return SpecialistCall(case_id="test", listing_id=listing_id, capability=capability, params=params)


async def draft(specialist, listing_id, **params):
    reply = await specialist.run(call(listing_id, specialist.capability, **params))
    assert reply.ok, reply.error
    return reply.drafts[0]


# ---------------- structure ----------------

def test_ids_unique_and_well_formed(listings, sellers):
    assert len({l.id for l in listings}) == len(listings) and len({s.id for s in sellers}) == len(sellers)
    assert all(len(l.id) == 5 and l.id[0] == "L" and l.id[1:].isdigit() for l in listings)
    assert all(len(s.id) == 5 and s.id[0] == "S" and s.id[1:].isdigit() for s in sellers)
    assert len({s.name for s in sellers}) == len(sellers)


def test_every_seller_exists_and_sells_something(listings, sellers):
    seller_ids = {s.id for s in sellers}
    assert all(l.seller_id in seller_ids for l in listings)
    assert seller_ids == {l.seller_id for l in listings}


def test_images_exist_and_are_small(listings):
    for l in listings:
        assert len(l.image_paths) <= 3
        for n, rel in enumerate(l.image_paths):
            assert rel == f"images/{l.id}_{n}.jpg"
            assert (DATA / rel).is_file() and (DATA / rel).stat().st_size <= 300_000, rel
    assert all(l.image_paths for l in listings if l.is_reconstructed)


def test_parsed_fields_come_from_textparse(listings):
    for l in listings:
        assert l.stated_material == stated_material(l.title, l.description), l.id
        assert l.item_type == item_type(l.title, l.description), l.id
        assert l.price_usd > 0 and l.ship_from and l.posted_at


def test_every_listing_is_labeled(listings, labels):
    assert set(labels) == {l.id for l in listings}
    by_id = {l.id: l for l in listings}
    for lid, label in labels.items():
        assert label.should_flag == (label.truth == "ivory")
        if not by_id[lid].is_reconstructed:
            assert not label.should_flag                   # every real listing is a negative
    assert all(l.reconstruction_source for l in listings if l.is_reconstructed)


def test_exactly_one_hidden_relist(listings):
    hidden = [l for l in listings if l.status == "hidden"]
    assert len(hidden) == 1 and hidden[0].relist_of
    assert [l.id for l in listings if l.relist_of] == [hidden[0].id]
    original = next(l for l in listings if l.id == hidden[0].relist_of)
    assert original.status == "active" and original.seller_id != hidden[0].seller_id
    assert all(l.status == "active" for l in listings if l is not hidden[0])


def test_eval_set(listings, labels):
    ids = rows("eval_set.txt")
    assert len(ids) == len(set(ids)) and set(ids) <= {l.id for l in listings}
    hidden = next(l.id for l in listings if l.status == "hidden")
    assert hidden not in ids
    positives = {lid for lid, lab in labels.items() if lab.should_flag and lid != hidden}
    assert positives <= set(ids) and len(positives) == 27
    assert sum(not labels[i].should_flag for i in ids) == 40


def test_no_truth_hints_in_public_fields(listings, sellers):
    for s in sellers:
        assert s.name.startswith("seller_") and len(s.name) == 13
    for l in listings:
        if l.is_reconstructed:
            assert "ivory" not in l.reconstruction_source.lower(), l.id     # agents can see this field


def test_no_real_usernames_leak(listings, sellers):
    seller_map = DATA / "raw" / "seller_map.json"
    if not seller_map.exists():
        pytest.skip("data/raw/seller_map.json only exists on the machine that built the dataset")
    handle_of = {pseudo: handle for handle, pseudo in json.loads(seller_map.read_text()).items()}
    assert not {h.lower() for h in handle_of.values()} & {s.name.lower() for s in sellers}
    name_of = {s.id: s.name for s in sellers}
    for l in listings:                                 # no listing names its own seller's real handle
        handle = handle_of.get(name_of[l.seller_id])
        if handle:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(handle)}(?![A-Za-z0-9])"
            assert not re.search(pattern, f"{l.title} {l.description}", flags=re.I), l.id


def test_mix_of_reconstructed_cases(listings, labels):
    positives = [l for l in listings if labels[l.id].should_flag and l.status != "hidden"]
    kinds = [l.item_type for l in positives]
    assert (kinds.count("netsuke"), kinds.count("figurine"), kinds.count("jewelry")) == (16, 6, 5)
    assert sum(l.language == "vi" for l in positives) == 2
    assert sum(labels[l.id].notes == "ambiguous by design" for l in positives) == 3


# ---------------- demo stories (code specialists only) ----------------

def test_demo_cases_exist(demo, listings):
    assert set(demo) == {"d1_network", "d2_tagua", "d3_removed", "d4_ambiguous"}
    assert set(demo.values()) <= {l.id for l in listings if l.status == "active"}
    assert len(set(demo.values())) == 4


async def test_d1_network_story(demo, market):
    price = await draft(PriceChecker(market), demo["d1_network"])
    assert price.data["ratio"] >= 8 and not price.data["weak_comparison"]
    linked = await draft(LinkedSellers(market), demo["d1_network"])
    assert linked.data["linked_seller_count"] == 2                 # the other two sellers of the network
    assert all(e["shared_phrase_count"] >= 2 for e in linked.data["linked"])
    assert any(e["shared_photo_count"] for e in linked.data["linked"])
    rule = (await LegalTable(market).run(call(demo["d1_network"], "legal_lookup"))).drafts[1]
    assert rule.data["jurisdiction"] == "US-CA"


async def test_d2_tagua_story(demo, market, labels):
    assert labels[demo["d2_tagua"]].truth == "tagua"
    price = await draft(PriceChecker(market), demo["d2_tagua"])
    assert price.data["ratio"] is not None and price.data["ratio"] <= 2
    assert (await draft(LinkedSellers(market), demo["d2_tagua"])).data["linked_seller_count"] == 0


async def test_d3_removed_story(demo, market, listings):
    hidden = next(l for l in listings if l.status == "hidden")
    assert hidden.relist_of == demo["d3_removed"]
    tracer = LinkedSellers(market)
    before = await draft(tracer, demo["d3_removed"])
    assert hidden.seller_id not in {e["seller_id"] for e in before.data["linked"]}
    assert await market.remove_listing(demo["d3_removed"]) == hidden.id
    after = {e["seller_id"]: e for e in (await draft(tracer, demo["d3_removed"])).data["linked"]}
    assert hidden.id in after[hidden.seller_id]["listing_ids"]
    assert after[hidden.seller_id]["shared_photo_count"] >= 1      # found by its reused photo
    assert len(after) == len(before.data["linked"]) + 1            # the rest of the network is still linked
    assert (await draft(PriceChecker(market), demo["d3_removed"])).data["ratio"] >= 8


async def test_d4_ambiguous_story(demo, market, labels):
    assert labels[demo["d4_ambiguous"]].notes == "ambiguous by design"
    assert (await draft(PriceChecker(market), demo["d4_ambiguous"])).data["ratio"] >= 8
    assert (await draft(LinkedSellers(market), demo["d4_ambiguous"])).data["linked_seller_count"] == 0


async def test_shop_network_and_planted_prices(listings, labels, market):
    by_seller = {}
    for l in listings:
        if labels[l.id].should_flag and l.status == "active":
            by_seller.setdefault(l.seller_id, []).append(l)
    shop_id, shop = max(by_seller.items(), key=lambda kv: len(kv[1]))
    assert len(shop) == 6 and all(l.item_type == "netsuke" and l.stated_material == "bone" for l in shop)
    inventory = await draft(SellerInventory(market), shop[0].id)
    assert inventory.data["listing_count"] == 8 and inventory.data["same_material_count"] >= 6
    for l in listings:                                             # every planted case is priced at ivory level
        if labels[l.id].should_flag and l.status == "active":
            ratio = (await draft(PriceChecker(market), l.id)).data["ratio"]
            assert ratio is not None and 8 <= ratio <= 20.5, (l.id, ratio)


async def test_planted_photos_link_only_where_designed(listings, labels, market):
    """Different museum objects must not look like reused photos; only the designed pair (and relist) match."""
    tracer = LinkedSellers(market)
    photo_links = set()
    for l in listings:
        if l.is_reconstructed and l.status == "active":
            for e in (await draft(tracer, l.id)).data["linked"]:
                if e["shared_photo_count"]:
                    photo_links.add(frozenset((l.seller_id, e["seller_id"])))
    assert len(photo_links) == 1
