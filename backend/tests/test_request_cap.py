"""Specialist requests (Facilitator._dispatch_requests): translation on an English listing never uses a slot, and a request the per-case
cap drops is reported. Real Facilitator, LocalTransport, discovery and specialists; stub agents and a stub model."""
import pytest

from deadlang import llm
from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for
from deadlang.agntcy.discovery import LocalDiscovery
from deadlang.agntcy.transport import LocalTransport
from deadlang.deliberation.facilitator import Facilitator
from deadlang.eval.run_eval import CollectBus
from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import Claim, SpecialistRequest, StancePost
from deadlang.specialists.legal import LegalTable
from deadlang.specialists.language import Translator
from deadlang.specialists.network import LinkedSellers, SellerInventory
from deadlang.specialists.price import PriceChecker
from tests.conftest import make_listing, make_seller

LIMIT = "request limit reached (6 per case)"


class Asker:
    def __init__(self, name, asks, varied=False):
        self.name, self.asks, self.varied = name, asks, varied

    async def handle(self, turn):
        reqs = [SpecialistRequest(capability=c, question="q", reason="r", params={"n": f"{self.name}{turn.round}{i}"} if self.varied else {})
                for i, c in enumerate(self.asks)] if turn.round <= (2 if self.varied else 1) else []
        return StancePost(agent=self.name, round=turn.round, stance="need_more", confidence=0.5, requests=reqs,
                          claims=[Claim(text="The listing is on the board.", evidence_ids=["E0"])],
                          ready_to_close=turn.round >= 2, take="t")


@pytest.fixture
def translations(monkeypatch):
    calls = []

    async def fake_call_json(**kw):
        calls.append(kw)
        assert kw["schema_name"] == "report_translation"
        return {"title_en": "Old bone bangle", "description_en": "An old bone bangle.",
                "notable_phrases": [{"original": "xương xưa", "literal_en": "old bone"}]}

    monkeypatch.setattr(llm, "call_json", fake_call_json)
    return calls


def market():
    return LocalMarketplaceClient(MarketplaceStore(
        [make_listing("L1", "S1", "Carved bone figure", "old bone", 120.0),
         make_listing("L0245", "S2", "Vòng tay xương xưa nguyên khối", "Vòng tay xương xưa", 300.0, language="vi")],
        [make_seller("S1"), make_seller("S2")]))


async def run_case(listing_id, undercover=(), counsel=(), officer=(), varied=False):
    m = market()
    # No material examiner: these listings have no photos and the model is stubbed for translation only.
    specs = [SellerInventory(m), LinkedSellers(m), PriceChecker(m), LegalTable(m), Translator(m)]
    agents = {"undercover": Asker("undercover", list(undercover), varied), "counsel": Asker("counsel", list(counsel), varied),
              "case_officer": Asker("case_officer", list(officer), varied)}
    disc = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    bus = CollectBus()
    fac = Facilitator(m, LocalTransport({s.name: s for s in specs}, agents, discovery=disc), disc, bus, max_rounds=2)
    await fac.run_case(f"cap-{listing_id}", listing_id)
    return bus.events


def evidence(events, cap=None):
    return [p["evidence"] for t, p in events if t == "evidence.added" and (cap is None or p["evidence"]["capability"] == cap)]


def selected(events):
    return [(p["capability"], p["requested_by"]) for t, p in events if t == "specialist.selected"]


def failed(events):
    return [p for t, p in events if t == "specialist.failed"]


# (a)
async def test_translation_on_an_english_listing_makes_no_call_uses_no_slot_and_adds_the_note(translations):
    events = await run_case("L1", undercover=["price_check", "seller_inventory"], officer=["translation", "linked_sellers"])
    assert translations == []                                                           # no translator model call
    assert ("translation", "case_officer") not in selected(events)                      # the translator was never called
    notes = evidence(events, "translation")
    assert len(notes) == 1 and notes[0]["data"]["already_english"] is True and notes[0]["requested_by"] == "case_officer"
    assert notes[0]["produced_by"] == "code" and "already in English" in notes[0]["summary"]
    # translation took no slot: price_check, seller_inventory and linked_sellers all fit under the 6-per-case cap
    assert [c for c, by in selected(events) if by != "intake"] == ["price_check", "seller_inventory", "linked_sellers"]
    assert [f for f in failed(events) if f["error"].startswith("request limit")] == []


async def test_the_note_goes_on_the_board_once_even_if_two_agents_ask(translations):
    events = await run_case("L1", undercover=["translation"], officer=["translation"])
    assert len(evidence(events, "translation")) == 1 and translations == []


# (b)
async def test_a_vietnamese_listing_is_translated_as_before(translations):
    events = await run_case("L0245", officer=["translation"])
    assert len(translations) == 2                                                       # intake, then case_officer's request
    assert [by for c, by in selected(events) if c == "translation"] == ["intake", "case_officer"]
    notes = evidence(events, "translation")
    assert [n["requested_by"] for n in notes] == ["intake", "case_officer"]
    assert all(n["produced_by"] == "model" and n["data"]["title_en"] == "Old bone bangle" for n in notes)


# (c)
async def test_requests_past_the_case_cap_are_reported_for_the_agent_that_made_it(translations):
    both = ["price_check", "seller_inventory"]
    events = await run_case("L1", undercover=both, counsel=both, officer=both, varied=True)   # asks again when woken by evidence
    dropped = [f for f in failed(events) if f["error"].startswith("request limit")]
    assert dropped and all(f["error"] == LIMIT and f["specialist_name"] == "" and f["requested_by"] in ("undercover", "counsel", "case_officer") for f in dropped)
    assert len([1 for c, by in selected(events) if by != "intake"]) == 6


# (d)
async def test_under_the_cap_nothing_is_reported_and_requests_and_evidence_are_as_before(translations):
    events = await run_case("L1", undercover=["price_check"], counsel=["legal_lookup"], officer=["linked_sellers"])
    assert [f for f in failed(events) if f["error"].startswith("request limit")] == []
    assert [(c, by) for c, by in selected(events) if by != "intake"] == [
        ("price_check", "undercover"), ("legal_lookup", "counsel"), ("linked_sellers", "case_officer")]
    asked = {(e["capability"], e["requested_by"]) for e in evidence(events) if e["requested_by"] != "intake"}
    assert asked == {("price_check", "undercover"), ("legal_lookup", "counsel"), ("linked_sellers", "case_officer")}
    assert evidence(events, "translation") == []                       # nobody asked: no note either
