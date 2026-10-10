import re

from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import SpecialistCall
from deadlang.specialists.price import PriceChecker
from tests.conftest import make_listing, make_seller

COMP_PRICES = [40, 50, 60, 70, 90, 100, 110, 120]          # median 80, p25 50, p75 100


def market(extra=(), comps=COMP_PRICES):
    listings = [make_listing(f"C{i}", "S2", "Carved bone netsuke", price=p) for i, p in enumerate(comps)]
    listings.append(make_listing("T1", "S1", "Carved bone netsuke of a rat", price=1000.0))
    return LocalMarketplaceClient(MarketplaceStore([*listings, *extra], [make_seller("S1"), make_seller("S2")]))


async def run(m, listing_id="T1"):
    reply = await PriceChecker(m).run(SpecialistCall(case_id="C-1", listing_id=listing_id, capability="price_check"))
    assert reply.ok and len(reply.drafts) == 1
    draft = reply.drafts[0]
    assert draft.capability == "price_check" and draft.produced_by == "code"
    assert draft.specialist_name == "deadlang-price-checker"
    return draft


def assert_summary_numbers_in_data(draft):
    stored = {float(v) for v in draft.data.values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for number in re.findall(r"\d+(?:\.\d+)?", draft.summary):
        assert float(number) in stored, f"{number} is in the summary but not in data"


async def test_ratio_against_same_type_and_material():
    draft = await run(market())
    d = draft.data
    assert (d["n"], d["median_usd"], d["p25_usd"], d["p75_usd"], d["ratio"]) == (8, 80, 50, 100, 12.5)
    assert d["weak_comparison"] is False and d["price_usd"] == 1000
    assert "T1" not in d["comparable_ids"] and len(d["comparable_ids"]) == 8
    assert draft.summary == ("Comparable bone netsuke listings (n=8) have a median price of $80 "
                             "(middle range $50–$100); this listing is $1000, 12.5x the median.")
    assert_summary_numbers_in_data(draft)


async def test_planted_and_other_material_listings_are_not_comparables():
    extra = [make_listing("R1", "S2", "Carved bone netsuke", price=5000.0, is_reconstructed=True),
             make_listing("X1", "S2", "Resin netsuke", price=9000.0),
             make_listing("H1", "S2", "Carved bone netsuke", price=7000.0, status="hidden")]
    draft = await run(market(extra))
    assert draft.data["n"] == 8 and draft.data["median_usd"] == 80


async def test_widens_to_material_when_few_same_type():
    extra = [make_listing(f"B{i}", "S2", "Bone bead necklace", price=p) for i, p in enumerate([20, 30, 40])]
    draft = await run(market(extra, comps=[60, 80, 100]))          # 3 netsuke + 3 necklaces = 6 bone
    d = draft.data
    assert d["weak_comparison"] is True and d["n"] == 6 and d["median_usd"] == 50 and d["ratio"] == 20.0
    assert draft.summary.startswith("Comparable bone listings (n=6)")
    assert draft.summary.endswith("Weak comparison: matched on material only.")
    assert_summary_numbers_in_data(draft)


async def test_not_enough_comparables():
    draft = await run(market(comps=[60, 80, 100]))
    assert draft.data["ratio"] is None and draft.data["n"] == 3 and draft.data["median_usd"] is None
    assert "too few" in draft.summary
    assert_summary_numbers_in_data(draft)


async def test_works_after_removal_and_rejects_unknown():
    m = market()
    await m.remove_listing("T1")
    assert (await run(m)).data["ratio"] == 12.5
    reply = await PriceChecker(m).run(SpecialistCall(case_id="C-1", listing_id="L999", capability="price_check"))
    assert not reply.ok and "L999" in reply.error
