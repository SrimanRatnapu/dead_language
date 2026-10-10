import pytest

from deadlang.agntcy import discovery as disc
from deadlang.agntcy.cards import ALL_AGENT_NAMES, DELIBERATOR_NAMES, SPECIALIST_NAMES, card_for, card_tags
from deadlang.agntcy.discovery import LocalDiscovery

CONTRACT = {   # plan 01 §4.2
    "deadlang-price-checker": ("price_check", "preferred"),
    "deadlang-seller-inventory": ("seller_inventory", "preferred"),
    "deadlang-linked-sellers": ("linked_sellers", "preferred"),
    "deadlang-legal-table": ("legal_lookup", "preferred"),
    "deadlang-examiner-thorough": ("material_exam", "preferred"),
    "deadlang-examiner-quick": ("material_exam", "fallback"),
    "deadlang-translator": ("translation", "preferred"),
}


def test_every_contract_specialist_has_a_card_with_parsable_tags():
    assert set(SPECIALIST_NAMES) == set(CONTRACT)
    for name, (capability, tier) in CONTRACT.items():
        card = card_for(name)
        tags = card_tags(card)
        assert card.name == name
        assert (tags["capability"], tags["tier"]) == (capability, tier)
        assert tags["produced_by"] in ("code", "model")
        assert card.additional_interfaces[0].url.endswith(f"/default/default/{name}")


def test_deliberator_cards():
    assert DELIBERATOR_NAMES == {"buyer": "deadlang-buyer", "defender": "deadlang-defender",
                                 "caseload": "deadlang-caseload"}
    for name in DELIBERATOR_NAMES.values():
        assert card_tags(card_for(name))["capability"] == "deliberate"
    assert len(ALL_AGENT_NAMES) == 10


@pytest.fixture
def d():
    return LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])


async def test_prefers_thorough_over_quick(d):
    sel = await d.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-thorough"
    assert sel.candidates == ["deadlang-examiner-thorough", "deadlang-examiner-quick"]
    assert sel.why == ("Chose deadlang-examiner-thorough: it offers material_exam at the preferred "
                       "quality tier and is responding.")


async def test_unhealthy_preferred_falls_back_with_sentence(d):
    await d.mark_unhealthy("deadlang-examiner-thorough")
    sel = await d.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-quick"
    assert sel.candidates == ["deadlang-examiner-quick"]
    assert sel.why == ("deadlang-examiner-thorough did not respond, so chose deadlang-examiner-quick, "
                       "which offers material_exam at a lower quality tier.")


async def test_unhealthy_expires(d, monkeypatch):
    monkeypatch.setattr(disc, "UNHEALTHY_SECONDS", 0)
    await d.mark_unhealthy("deadlang-examiner-thorough")
    assert (await d.select("material_exam")).specialist_name == "deadlang-examiner-thorough"


async def test_exclude_and_only_one_sentence(d):
    sel = await d.select("price_check")
    assert sel.why == "deadlang-price-checker is the only registered agent offering price_check."
    assert await d.select("price_check", exclude={"deadlang-price-checker"}) is None
    sel = await d.select("material_exam", exclude={"deadlang-examiner-thorough"})
    assert sel.specialist_name == "deadlang-examiner-quick"
    assert sel.why.startswith("deadlang-examiner-thorough did not respond")


async def test_unknown_capability_returns_none(d):
    assert await d.select("system_notice") is None


async def test_latency_orders_within_a_tier():
    cards = [card_for("deadlang-examiner-thorough"), card_for("deadlang-examiner-quick")]
    second = cards[0].model_copy(deep=True)
    second.name = "deadlang-examiner-thorough-2"
    d = LocalDiscovery(cards + [second])
    d.record_latency("deadlang-examiner-thorough", 900)
    d.record_latency("deadlang-examiner-thorough-2", 100)
    sel = await d.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-thorough-2"
    assert sel.candidates[-1] == "deadlang-examiner-quick"
