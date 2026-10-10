import re

import pytest
from PIL import Image, ImageDraw

from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import SpecialistCall
from deadlang.specialists.network import LinkedSellers, SellerInventory
from tests.conftest import make_listing, make_seller

RARE_1 = "kindly message our family before buying anything at all"
RARE_2 = "parcels leave quietly from the harbour warehouse each friday"
COMMON = "thank you for looking at my other items"          # used by 5 sellers: not rare
ALL_STOPWORDS = "it is of the and it is in"                 # only function words: ignored


def picture(path, seed: int):
    """A small real JPEG whose large-scale structure depends on the seed, so perceptual hashes differ."""
    img = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(img)
    for k in range(4):
        x, y = (seed * 37 + k * 53) % 96, (seed * 71 + k * 29) % 96
        draw.rectangle([x, y, x + 20 + 6 * k, y + 16 + 5 * k], fill=(seed * 40 % 255, k * 60, 30))
    img.save(path, "JPEG", quality=85)


def call(listing_id, capability, **params):
    return SpecialistCall(case_id="C-1", listing_id=listing_id, capability=capability, params=params)


# ---------------- seller_inventory ----------------

@pytest.fixture
def inventory_market():
    listings = [make_listing("L1", "S1", "Carved bone netsuke", price=1200.0),
                make_listing("L2", "S1", "Bone netsuke of a monkey", price=950.5),
                make_listing("L3", "S1", "Resin figurine", price=20.0),
                make_listing("L4", "S1", "Bone bead necklace", price=30.0, status="removed"),
                make_listing("L5", "S1", "Hidden bone netsuke", price=999.0, status="hidden"),
                make_listing("L6", "S2", "Bone netsuke", price=60.0)]
    return LocalMarketplaceClient(MarketplaceStore(listings, [make_seller("S1"), make_seller("S2")]))


async def test_seller_inventory(inventory_market):
    reply = await SellerInventory(inventory_market).run(call("L1", "seller_inventory"))
    assert reply.ok and len(reply.drafts) == 1
    draft = reply.drafts[0]
    d = draft.data
    assert (d["seller_id"], d["listing_count"], d["removed_count"]) == ("S1", 4, 1)     # hidden not counted
    assert (d["same_material_count"], d["same_type_count"], d["total_value_usd"]) == (3, 2, 2200)
    assert [i["id"] for i in d["items"]] == ["L1", "L2", "L3", "L4"]
    assert d["items"][3] == {"id": "L4", "title": "Bone bead necklace", "price_usd": 30.0,
                             "stated_material": "bone", "item_type": "jewelry", "status": "removed"}
    assert draft.summary == ("Seller seller_s1 has 4 listings (1 removed); 3 are described as bone and "
                             "2 are netsuke items, worth $2,200 in total.")
    stored = {float(v) for v in d.values() if isinstance(v, (int, float))}
    for number in re.findall(r"\d[\d,]*", draft.summary.replace("seller_s1", "")):
        assert float(number.replace(",", "")) in stored
    assert draft.produced_by == "code" and draft.specialist_name == "deadlang-seller-inventory"


async def test_seller_inventory_of_another_seller_and_unknown(inventory_market):
    reply = await SellerInventory(inventory_market).run(call("L1", "seller_inventory", seller_id="S2"))
    assert reply.drafts[0].data["seller_id"] == "S2" and reply.drafts[0].data["listing_count"] == 1
    assert not (await SellerInventory(inventory_market).run(call("L1", "seller_inventory", seller_id="S9"))).ok
    assert not (await SellerInventory(inventory_market).run(call("L999", "seller_inventory"))).ok


async def test_seller_inventory_caps_items_at_12():
    listings = [make_listing(f"L{i}", "S1", "Bone netsuke", price=10.0) for i in range(15)]
    m = LocalMarketplaceClient(MarketplaceStore(listings, [make_seller("S1")]))
    d = (await SellerInventory(m).run(call("L0", "seller_inventory"))).drafts[0].data
    assert d["listing_count"] == 15 and len(d["items"]) == 12 and d["total_value_usd"] == 150


# ---------------- linked_sellers ----------------

@pytest.fixture
def linked_market(tmp_path):
    (tmp_path / "images").mkdir()
    for name, seed in [("a", 1), ("b", 2), ("c", 3), ("d", 4)]:
        picture(tmp_path / "images" / f"{name}.jpg", seed)
    (tmp_path / "images" / "a_copy.jpg").write_bytes((tmp_path / "images" / "a.jpg").read_bytes())
    listings = [
        make_listing("L1", "S1", "Carved bone netsuke", f"Old piece. {RARE_1}. {RARE_2}. {COMMON}. {ALL_STOPWORDS}.",
                     image_paths=["images/a.jpg", "images/missing.jpg"]),
        make_listing("L2", "S2", "Bone figure", f"{RARE_1}! Lovely thing. {RARE_2}. {COMMON}.",
                     image_paths=["images/b.jpg"]),
        make_listing("L3", "S3", "Small carving", "Nothing in common in the words here at all.",
                     image_paths=["images/c.jpg", "images/a_copy.jpg"]),
        make_listing("L4", "S4", "Resin duck", f"{COMMON}. {ALL_STOPWORDS}.", image_paths=["images/d.jpg"]),
        make_listing("L5", "S5", "Wooden bowl", f"{COMMON}."),
        make_listing("L6", "S6", "Glass vase", f"{COMMON}. {RARE_1}."),        # only ONE rare phrase: no link
        make_listing("L7", "S1", "Second item of S1", f"{RARE_1}. {RARE_2}."),  # same seller: never linked
        make_listing("L8", "S7", "Relist", f"Slightly reworded. {RARE_1}. {RARE_2}.",
                     image_paths=["images/a_copy.jpg"], status="hidden", relist_of="L1"),
    ]
    sellers = [make_seller(f"S{i}") for i in range(1, 8)]
    return LocalMarketplaceClient(MarketplaceStore(listings, sellers), tmp_path), tmp_path


async def linked(specialist, listing_id="L1"):
    reply = await specialist.run(call(listing_id, "linked_sellers"))
    assert reply.ok and len(reply.drafts) == 1
    return reply.drafts[0]


async def test_links_by_rare_phrases_and_by_reused_photo(linked_market):
    market, _ = linked_market
    draft = await linked(LinkedSellers(market))
    by_seller = {e["seller_id"]: e for e in draft.data["linked"]}
    # S6 shares only ONE rare sentence: not enough for a phrase link (two long phrases are needed).
    assert set(by_seller) == {"S2", "S3"}
    assert draft.data["linked_seller_count"] == 2

    s2 = by_seller["S2"]
    assert s2["listing_ids"] == ["L2"] and s2["shared_photo_pairs"] == []
    assert sorted(s2["shared_phrases"]) == sorted([RARE_1, RARE_2])           # merged back, verbatim words
    assert s2["shared_phrase_count"] == 2 and s2["shared_photo_count"] == 0

    s3 = by_seller["S3"]
    assert s3["shared_phrases"] == [] and s3["shared_photo_pairs"] == [["images/a.jpg", "images/a_copy.jpg"]]
    assert s3["shared_photo_count"] == 1 and s3["seller_name"] == "seller_s3"

    assert draft.summary.startswith("2 other sellers share rare phrasing or reused photos with this listing: ")
    assert "seller_s2 (2 shared phrases, 0 shared photos)" in draft.summary
    assert "seller_s3 (0 shared phrases, 1 shared photos)" in draft.summary


async def test_common_and_stopword_phrases_do_not_link(linked_market):
    market, _ = linked_market
    draft = await linked(LinkedSellers(market))
    assert not {"S4", "S5"} & {e["seller_id"] for e in draft.data["linked"]}
    for entry in draft.data["linked"]:
        assert COMMON not in entry["shared_phrases"]
    lonely = await linked(LinkedSellers(market), "L5")                        # only the common phrase
    assert lonely.data == {"listing_id": "L5", "linked": [], "linked_seller_count": 0}
    assert lonely.summary == "No other sellers share rare phrasing or photos with this listing."


async def test_relist_appears_after_removal(linked_market):
    market, _ = linked_market
    specialist = LinkedSellers(market)
    assert "S7" not in {e["seller_id"] for e in (await linked(specialist)).data["linked"]}
    assert await market.remove_listing("L1") == "L8"
    after = {e["seller_id"]: e for e in (await linked(specialist)).data["linked"]}   # same instance: cache refreshed
    assert after["S7"]["listing_ids"] == ["L8"]
    assert after["S7"]["shared_photo_pairs"] == [["images/a.jpg", "images/a_copy.jpg"]]
    assert sorted(after["S7"]["shared_phrases"]) == sorted([RARE_1, RARE_2])
    assert "S2" in after                                                     # the network is still visible


async def test_single_link_grammar_and_cache_file(linked_market):
    market, tmp_path = linked_market
    draft = await linked(LinkedSellers(market), "L4")                         # d.jpg is unique; words are common
    assert draft.data["linked_seller_count"] == 0
    draft = await linked(LinkedSellers(market), "L3")
    assert draft.summary == ("1 other seller shares rare phrasing or reused photos with this listing: "
                             "seller_s1 (0 shared phrases, 1 shared photos).")
    assert (tmp_path / "phash_cache.json").exists()
    assert not (await LinkedSellers(market).run(call("L999", "linked_sellers"))).ok
