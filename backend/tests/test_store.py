import pytest

from deadlang.marketplace.store import ListingRemoved, MarketplaceStore


def test_get_listing_and_seller(store):
    assert store.get_listing("L1").price_usd == 900.0
    assert store.get_seller("S2").id == "S2"
    with pytest.raises(KeyError):
        store.get_listing("L999")
    with pytest.raises(KeyError):
        store.get_seller("S999")


def test_hidden_listing_is_invisible(store):
    with pytest.raises(KeyError):
        store.get_listing("L4")
    assert store.get_listing_any_status("L4").status == "hidden"
    assert "L4" not in [l.id for l in store.active_listings()]
    assert store.seller_listings("S3") == []


def test_remove_raises_and_reveals_relist(store):
    assert store.remove_listing("L1") == "L4"
    with pytest.raises(ListingRemoved) as exc:
        store.get_listing("L1")
    assert exc.value.listing_id == "L1"
    assert store.get_listing_any_status("L1").status == "removed"
    assert [l.id for l in store.active_listings()] == ["L2", "L3", "L4"]
    assert store.get_listing("L4").status == "active"
    assert store.remove_listing("L1") is None          # second removal reveals nothing new
    assert store.remove_listing("L3") is None          # no relist waiting
    with pytest.raises(KeyError):
        store.remove_listing("L999")


def test_seller_listings_include_removed_when_asked(store):
    store.remove_listing("L1")
    assert [l.id for l in store.seller_listings("S1")] == ["L1", "L2"]
    assert [l.id for l in store.seller_listings("S1", include_removed=False)] == ["L2"]


def test_search_needs_every_word_and_only_active(store):
    assert [l.id for l in store.search("bone netsuke")] == ["L1"]
    assert [l.id for l in store.search("BONE")] == ["L1", "L3"]
    assert store.search("bone", limit=1)[0].id == "L1"
    store.remove_listing("L1")
    assert [l.id for l in store.search("bone netsuke")] == ["L4"]


def test_reset_demo_state_restores(store):
    original = store.statuses()
    assert original == {"L1": "active", "L2": "active", "L3": "active", "L4": "hidden"}
    store.remove_listing("L1")
    store.reset_demo_state(original)
    assert store.statuses() == original
    assert store.get_listing("L1").status == "active"


def test_from_dir(tmp_path, store):
    (tmp_path / "listings.jsonl").write_text(
        "\n".join(store.get_listing_any_status(i).model_dump_json() for i in ("L1", "L2", "L3", "L4")) + "\n")
    (tmp_path / "sellers.jsonl").write_text(
        "\n".join(store.get_seller(i).model_dump_json() for i in ("S1", "S2", "S3")) + "\n")
    loaded = MarketplaceStore.from_dir(tmp_path)
    assert loaded.statuses() == store.statuses()
    assert loaded.get_seller("S3").name == "seller_s3"
