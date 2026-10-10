import re
from pathlib import Path

import pytest

from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import SpecialistCall
from deadlang.specialists.legal import LegalTable
from tests.conftest import make_listing, make_seller

DATA_DIR = Path(__file__).resolve().parents[2] / "data"       # uses the real, committed legal.json


@pytest.fixture
def market():
    listings = [make_listing("L1", "S1", "Bone netsuke", ship_from="US-CA"),
                make_listing("L2", "S1", "Bone netsuke", ship_from="US-NY"),
                make_listing("L3", "S1", "Bone netsuke", ship_from="HK"),
                make_listing("L4", "S1", "Bone netsuke", ship_from="US")]
    return LocalMarketplaceClient(MarketplaceStore(listings, [make_seller("S1")]), DATA_DIR)


async def lookup(market, listing_id, **params):
    reply = await LegalTable(market).run(
        SpecialistCall(case_id="C-1", listing_id=listing_id, capability="legal_lookup", params=params))
    assert reply.ok and len(reply.drafts) == 2
    for d in reply.drafts:
        assert d.capability == "legal_lookup" and d.produced_by == "code"
        assert d.specialist_name == "deadlang-legal-table" and d.data["source"].startswith("https://")
        blob = repr(d.data)                                    # every number in a summary is in its data
        for number in re.findall(r"\d[\d,]*", d.summary):
            assert number in blob
    return reply.drafts


async def test_california_rule(market):
    species, rule = await lookup(market, "L1")
    assert species.summary == "CITES listing for African or Asian elephant ivory: Asian elephant: Appendix I."
    assert "Botswana" in species.data["cites"]
    assert rule.summary == ("California Fish and Game Code section 2022 makes it unlawful to purchase, sell, "
                            "offer for sale, or possess with intent to sell ivory "
                            "(applies because the item ships from US-CA).")
    d = rule.data
    assert (d["jurisdiction"], d["ship_from"]) == ("US-CA", "US-CA")
    assert (d["antique_min_age_years"], d["antique_max_ivory_percent"],
            d["instrument_max_ivory_percent"], d["instrument_latest_year"]) == (100, 5, 20, 1975)
    assert "misdemeanor" in d["rule"]


async def test_other_us_state_gets_federal_rule(market):
    for listing_id, ship_from in (("L2", "US-NY"), ("L4", "US")):
        _, rule = await lookup(market, listing_id)
        assert rule.data["jurisdiction"] == "US-federal" and rule.data["ship_from"] == ship_from
        assert rule.summary.startswith("Interstate sale of African elephant ivory is prohibited except ESA antiques")
        assert rule.summary.endswith(f"(applies because the item ships from {ship_from}).")


async def test_non_us_gets_default_rule(market):
    _, rule = await lookup(market, "L3")
    assert rule.data["jurisdiction"] == "default"
    assert rule.summary == ("For non-US sellers, CITES Appendix I bars commercial international trade "
                            "(applies because the item ships from HK).")


async def test_explicit_hypothesis_and_errors(market):
    assert (await lookup(market, "L1", material_hypothesis="elephant_ivory"))[0].data["material_hypothesis"] == "elephant_ivory"
    table = LegalTable(market)
    bad = await table.run(SpecialistCall(case_id="C-1", listing_id="L1", capability="legal_lookup",
                                         params={"material_hypothesis": "bone"}))
    assert not bad.ok and "bone" in bad.error
    assert not (await table.run(SpecialistCall(case_id="C-1", listing_id="L999", capability="legal_lookup"))).ok
