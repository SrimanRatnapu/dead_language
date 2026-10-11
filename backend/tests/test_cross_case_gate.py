"""The Case Officer only argues when there is something to compare, end to end.

Real Facilitator, real transport and discovery, and the real seller-inventory, linked-sellers and price-check
specialists over a tiny in-memory marketplace. Only the three deliberating agents are stubs (no model calls).
"""
import pytest

from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for
from deadlang.agntcy.discovery import LocalDiscovery
from deadlang.agntcy.transport import LocalTransport
from deadlang.api.events import EventBus
from deadlang.deliberation import crosscase
from deadlang.deliberation.facilitator import Facilitator
from deadlang.marketplace.client import LocalMarketplaceClient
from deadlang.marketplace.store import MarketplaceStore
from deadlang.schemas import Claim, StancePost
from deadlang.specialists.network import LinkedSellers, SellerInventory
from deadlang.specialists.price import PriceChecker
from tests.conftest import make_listing, make_seller
from tests.test_network import RARE_1, RARE_2, picture
from deadlang.deliberation.facilitator import AGENTS

OFFICER = crosscase.CROSS_CASE_ROLE                               # the roles come from the roster, never from literals
UNDERCOVER, COUNSEL = [a for a in AGENTS if a != OFFICER]


class StubAgent:
    """Always takes the same position; records every turn it is given."""

    def __init__(self, name, stance, conf=0.9):
        self.name, self.stance, self.conf = name, stance, conf
        self.turns = []

    async def handle(self, turn):
        self.turns.append(turn)
        return StancePost(agent=self.name, round=turn.round, stance=self.stance, confidence=self.conf,
                          claims=[Claim(text="The listing describes the item as bone.", evidence_ids=["E0"])],
                          take=f"{self.name} here.")


def market_of(tmp_path, listings, n_sellers=8):
    return LocalMarketplaceClient(MarketplaceStore(listings, [make_seller(f"S{i}") for i in range(1, n_sellers + 1)]),
                                  tmp_path)


async def run_case(market, undercover="file", counsel="file", case_officer="need_more", listing="L1", specialists=None):
    specialists = specialists or [SellerInventory(market), LinkedSellers(market), PriceChecker(market)]
    agents = {UNDERCOVER: StubAgent(UNDERCOVER, undercover), COUNSEL: StubAgent(COUNSEL, counsel),
              OFFICER: StubAgent(OFFICER, case_officer, conf=0.6)}
    discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    transport = LocalTransport({s.name: s for s in specialists}, agents, discovery=discovery)
    bus = EventBus(runs_dir=None)
    case_file = await Facilitator(market, transport, discovery, bus).run_case("C-1", listing)
    return case_file, agents, bus


def events(bus, type_):
    return [e for e in bus.history("C-1") if e.type == type_]


def position(case_file, agent):
    return next(p for p in case_file.final_positions if p.agent == agent)


# ---------------- scenario 1: an isolated listing ----------------

@pytest.fixture
def isolated(tmp_path):
    """One listing, one seller, nobody else: no other listings, no links, no reused photos, no comparables."""
    return market_of(tmp_path, [make_listing("L1", "S1", "Carved bone netsuke", "old bone netsuke of a rat", 900.0)])


async def test_isolated_listing_case_officer_sits_out_and_undercover_and_counsel_decide(isolated):
    case_file, agents, bus = await run_case(isolated, undercover="file", counsel="file", case_officer="need_more")

    assert agents[OFFICER].turns == []                                    # not called: nothing to argue about
    assert [len(agents[a].turns) for a in (UNDERCOVER, COUNSEL)] == [1, 1]
    assert [e.payload["active"] for e in events(bus, "round.started")] == [[UNDERCOVER, COUNSEL]]

    sat_out = position(case_file, OFFICER)
    assert sat_out.abstained and sat_out.take.startswith("No other cases to compare")
    assert (case_file.outcome, case_file.stop_reason, case_file.rounds_used) == ("FILE", "unanimous", 1)
    assert "Case Officer abstained" in case_file.tip_draft                       # shown in the draft, not as a stance
    shown = [e.payload["post"] for e in events(bus, "stance.posted") if e.payload["post"]["agent"] == OFFICER]
    assert len(shown) == 1 and shown[0]["abstained"] is True                 # the UI gets an explicit event, once


async def test_without_the_gate_an_empty_case_officer_would_have_dragged_the_outcome_to_watchlist(isolated, monkeypatch):
    monkeypatch.setattr(crosscase, "assess", lambda board: crosscase.CrossCase(None, None, None, None))   # no gate
    case_file, agents, _ = await run_case(isolated, undercover="file", counsel="file", case_officer="need_more")
    assert len(agents[OFFICER].turns) >= 1 and case_file.outcome == "WATCHLIST"


@pytest.mark.parametrize("undercover,counsel,outcome,stop,rounds", [
    ("file", "file", "FILE", "unanimous", 1),
    ("dismiss", "dismiss", "DISMISS", "unanimous", 1),
    ("file", "dismiss", "CONTESTED", "ready_to_close", 2),     # nothing left to check, so no pointless extra rounds
    ("file", "need_more", "WATCHLIST", "ready_to_close", 2),
])
async def test_how_an_isolated_listing_resolves(isolated, undercover, counsel, outcome, stop, rounds):
    case_file, agents, _ = await run_case(isolated, undercover=undercover, counsel=counsel)
    assert (case_file.outcome, case_file.stop_reason, case_file.rounds_used) == (outcome, stop, rounds)
    assert agents[OFFICER].turns == []


# ---------------- scenario 2: a linked seller ----------------

async def test_a_linked_seller_gives_case_officer_something_to_weigh(tmp_path):
    market = market_of(tmp_path, [
        make_listing("L1", "S1", "Carved bone netsuke", f"Old piece. {RARE_1}. {RARE_2}."),
        make_listing("L2", "S2", "Bone figure", f"{RARE_1}! Lovely thing. {RARE_2}.")])

    case_file, agents, bus = await run_case(market, undercover="file", counsel="file", case_officer="need_more")

    assert len(agents[OFFICER].turns) >= 1                                # it argues
    assert [e.payload["active"] for e in events(bus, "round.started")][0] == [UNDERCOVER, COUNSEL, OFFICER]
    assert not position(case_file, OFFICER).abstained
    assert case_file.outcome == "WATCHLIST"                                  # a real need_more counts, as before
    inputs = crosscase.assess(_board_of(case_file))
    assert inputs.linked_sellers == 1 and inputs.photo_reuse_hits == 0 and inputs.seller_other_listings == 0


# ---------------- scenario 3: reused photos ----------------

async def test_reused_photos_give_case_officer_something_to_weigh(tmp_path):
    (tmp_path / "images").mkdir()
    picture(tmp_path / "images" / "a.jpg", 1)
    (tmp_path / "images" / "a_copy.jpg").write_bytes((tmp_path / "images" / "a.jpg").read_bytes())
    market = market_of(tmp_path, [
        make_listing("L1", "S1", "Carved bone netsuke", "old bone netsuke of a rat", image_paths=["images/a.jpg"]),
        make_listing("L2", "S2", "Small carving", "Nothing in common in the words here at all.",
                     image_paths=["images/a_copy.jpg"])])

    case_file, agents, _ = await run_case(market, undercover="file", counsel="file", case_officer="file")

    assert len(agents[OFFICER].turns) >= 1
    assert (case_file.outcome, case_file.stop_reason) == ("FILE", "unanimous")   # all three file: unchanged rule
    inputs = crosscase.assess(_board_of(case_file))
    assert inputs.photo_reuse_hits == 1 and inputs.seller_other_listings == 0


# ---------------- the edges ----------------

async def test_price_comparables_alone_do_not_keep_case_officer_in_unless_switched_on(tmp_path, monkeypatch):
    others = [make_listing(f"L{i}", f"S{i}", "Bone netsuke", f"Old bone carving number {i}.", 60.0 + i)
              for i in range(2, 9)]                                           # 7 same-material comparables
    market = market_of(tmp_path, [make_listing("L1", "S1", "Carved bone netsuke", "old bone netsuke", 900.0)] + others)

    case_file, agents, _ = await run_case(market)                             # the default: comparables do not count
    assert agents[OFFICER].turns == [] and position(case_file, OFFICER).abstained

    monkeypatch.setattr(crosscase, "CROSS_CASE_SOURCES", (*crosscase.CROSS_CASE_SOURCES, "price_comparables"))
    _, agents, _ = await run_case(market)
    assert len(agents[OFFICER].turns) >= 1                                # switched on: comparables are material


async def test_when_a_cross_case_check_could_not_run_case_officer_is_not_skipped(isolated):
    market = isolated
    only_price = [PriceChecker(market)]                                      # seller inventory and links unavailable
    case_file, agents, _ = await run_case(market, specialists=only_price)
    assert len(agents[OFFICER].turns) >= 1                                # an unanswered question is not "nothing"
    assert not position(case_file, OFFICER).abstained


async def test_the_abstained_post_is_never_shown_to_the_other_agents(isolated):
    _, agents, _ = await run_case(isolated, undercover="file", counsel="dismiss")
    for turn in agents[UNDERCOVER].turns + agents[COUNSEL].turns:
        assert all(not p.abstained and p.agent != OFFICER for p in turn.transcript)


def _board_of(case_file):
    from deadlang.evidence.board import EvidenceBoard
    from deadlang.schemas import EvidenceDraft
    board = EvidenceBoard(case_file.case_id)
    for e in case_file.evidence:                              # same ids come back, since the order is kept
        board.add(EvidenceDraft.model_validate(e.model_dump(include=set(EvidenceDraft.model_fields))), e.requested_by)
    return board
