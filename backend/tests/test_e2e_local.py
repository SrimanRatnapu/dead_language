"""Whole case through the real local stack (Facilitator + LocalTransport + LocalDiscovery + real specialists +
marketplace store + DeliberatingAgent + llm wrapper). Only the Anthropic client is faked."""
from types import SimpleNamespace as NS

import pytest

from deadlang import config, llm
from deadlang.agntcy import discovery as discovery_mod, transport as transport_mod
from deadlang.api.events import EventBus
from deadlang.deliberation import crosscase
from deadlang.deliberation.facilitator import Facilitator
from deadlang.marketplace.client import LocalMarketplaceClient
from tests.conftest import make_listing, make_seller
from deadlang.marketplace.store import MarketplaceStore


class ScriptedAnthropic:
    """Answers each forced tool call from its schema name: all three agents file, citing E0."""
    def __init__(self):
        self.messages = self
        self.names: list[str] = []

    async def create(self, **req):
        name = req["tools"][0]["name"]
        self.names.append(name)
        if name == "post_position":
            out = {"stance": "file", "confidence": 0.8, "ready_to_close": True,
                   "claims": [{"text": "The listing is priced at $900.", "evidence_ids": ["E0"]}]}
        else:
            out = {}
        block = NS(type="tool_use", name=name, input=out)
        return NS(content=[block], usage=NS(input_tokens=100, output_tokens=20))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(discovery_mod, "_discovery", None, raising=False)
    monkeypatch.setattr(transport_mod, "_transport", None)
    yield
    llm.set_client_for_tests(None)


async def test_full_case_on_real_local_stack(monkeypatch):
    store = MarketplaceStore(
        [make_listing("L1", "S1", "Carved bone netsuke", "old bone netsuke of a rat", 900.0),
         make_listing("L3", "S2", "Bone bead necklace", "hand carved beads", 35.0)],
        [make_seller("S1"), make_seller("S2")])
    market = LocalMarketplaceClient(store)
    import deadlang.marketplace.client as mc
    monkeypatch.setattr(mc, "_client", market)
    fake = ScriptedAnthropic()
    llm.set_client_for_tests(fake)

    disc = discovery_mod.get_discovery()
    await disc.register_all()
    bus = EventBus(runs_dir=None)
    fac = Facilitator(market, transport_mod.get_transport(), disc, bus)
    cf = await fac.run_case("C-1", "L1")

    assert cf.outcome == "FILE" and cf.stop_reason in ("unanimous", "ready_to_close")
    caps = {e.capability for e in cf.evidence}
    assert {"listing_snapshot", "price_check", "seller_inventory", "linked_sellers", "legal_lookup"} <= caps
    # L1 is isolated (no other listings by its seller, no links, no reused photos, too few comparables), so
    # the Case Officer sits out and only the other two agents are asked.
    assert fake.names.count("post_position") == 2
    assert next(p for p in cf.final_positions if p.agent == crosscase.CROSS_CASE_ROLE).abstained
    types = [e.type for e in bus.history("C-1")]
    assert types[0] == "case.started" and types[-1] == "case.ended"
