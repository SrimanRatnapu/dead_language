"""The cross-case check, the new readiness rule, and who is woken in later rounds (no model calls anywhere)."""
import pytest

from deadlang.deliberation import crosscase, rules
from deadlang.deliberation.facilitator import CaseState, Facilitator
from deadlang.evidence.board import EvidenceBoard
from deadlang.schemas import Challenge, EvidenceDraft, Rebuttal, StancePost
from tests.fakes import FakeDiscovery, FakeMarket, FakeTransport, make_listing


def ev(capability, data, board=None, **kw):
    return EvidenceDraft(capability=capability, summary="x", data=data, produced_by="code",
                         specialist_name="t", **kw)


E0 = {"id": "L1", "seller_id": "S1", "title": "Netsuke"}


def board_with(*drafts, e0=E0):
    b = EvidenceBoard("C-1")
    b.add(ev("listing_snapshot", e0), "intake")
    for d in drafts:
        b.add(d, "intake")
    return b


def inventory(count, seller="S1"):
    return ev("seller_inventory", {"seller_id": seller, "listing_count": count})


def linked(count=0, photo_hits=0):
    items = [{"seller_id": f"S{i + 2}", "shared_photo_count": photo_hits if i == 0 else 0} for i in range(count)]
    return ev("linked_sellers", {"listing_id": "L1", "linked": items, "linked_seller_count": count})


def price(n, ratio):
    return ev("price_check", {"n": n, "ratio": ratio})


# ---------------- the check ----------------

def test_an_isolated_listing_has_nothing_to_compare():
    cc = crosscase.assess(board_with(inventory(1), linked(0), price(3, None)))
    assert (cc.seller_other_listings, cc.linked_sellers, cc.photo_reuse_hits, cc.price_comparables) == (0, 0, 0, 0)
    assert cc.nothing_to_compare and not cc.available and not cc.unknown


def test_the_sellers_other_listings_count_without_the_listing_itself():
    cc = crosscase.assess(board_with(inventory(4), linked(0), price(3, None)))
    assert cc.seller_other_listings == 3 and cc.available and not cc.nothing_to_compare


def test_a_linked_seller_is_cross_case_material():
    cc = crosscase.assess(board_with(inventory(1), linked(2), price(3, None)))
    assert cc.linked_sellers == 2 and cc.photo_reuse_hits == 0 and cc.available


def test_reused_photos_are_cross_case_material():
    cc = crosscase.assess(board_with(inventory(1), linked(1, photo_hits=3), price(3, None)))
    assert cc.photo_reuse_hits == 3 and cc.available


def test_price_comparables_are_recorded_but_do_not_count_by_default():
    cc = crosscase.assess(board_with(inventory(1), linked(0), price(12, 3.2)))
    assert cc.price_comparables == 12                              # still read from the board...
    assert not cc.available and cc.nothing_to_compare              # ...but almost every listing has them, so no gate


def test_price_comparables_count_when_the_source_is_switched_on(monkeypatch):
    board = board_with(inventory(1), linked(0), price(12, 3.2))
    monkeypatch.setattr(crosscase, "CROSS_CASE_SOURCES", (*crosscase.CROSS_CASE_SOURCES, "price_comparables"))
    assert crosscase.assess(board).available
    too_few = board_with(inventory(1), linked(0), price(3, None))   # fewer than 5: no ratio, so zero comparables
    assert crosscase.assess(too_few).nothing_to_compare


def test_the_default_sources_leave_out_price_comparables():
    assert crosscase.CROSS_CASE_SOURCES == ("seller_other_listings", "linked_sellers", "photo_reuse")


def test_a_missing_price_check_does_not_matter_unless_price_comparables_are_a_source(monkeypatch):
    board = board_with(inventory(1), linked(0))                    # the price check never reported
    assert crosscase.assess(board).nothing_to_compare
    monkeypatch.setattr(crosscase, "CROSS_CASE_SOURCES", (*crosscase.CROSS_CASE_SOURCES, "price_comparables"))
    assert crosscase.assess(board).unknown


@pytest.mark.parametrize("drafts", [
    [linked(0), price(3, None)],                                   # no inventory evidence (the specialist failed)
    [inventory(1), price(3, None)],                                # no linked-sellers evidence
    [ev("seller_inventory", {"n": 1}), linked(0), price(3, None)],  # evidence we cannot read
    [inventory(1, seller="S9"), linked(0), price(3, None)],        # inventory of a different seller
])
def test_when_a_check_is_missing_or_unreadable_the_question_is_open_not_empty(drafts):
    cc = crosscase.assess(board_with(*drafts))
    assert cc.unknown and not cc.nothing_to_compare                # never skip Caseload on a guess


def test_available_material_wins_over_a_missing_check():
    cc = crosscase.assess(board_with(inventory(5), linked(0)))     # price check missing, but the seller has others
    assert cc.available and not cc.nothing_to_compare


def test_a_later_item_for_the_same_check_replaces_the_earlier_one():
    cc = crosscase.assess(board_with(inventory(1), linked(0), price(3, None), linked(1, photo_hits=1)))
    assert cc.linked_sellers == 1 and cc.photo_reuse_hits == 1


def test_a_board_without_a_listing_snapshot_is_unknown_not_a_crash():
    cc = crosscase.assess(EvidenceBoard("C-1"))
    assert cc.unknown and not cc.nothing_to_compare


def test_the_message_for_the_ui():
    assert crosscase.NO_CROSS_CASE_TAKE.startswith("No other cases to compare")


# ---------------- readiness ----------------

def post(stance="file", conf=0.7, **kw):
    return StancePost(agent="buyer", round=2, stance=stance, confidence=conf, claims=[], **kw)


def test_the_agents_own_ready_flag_still_counts_exactly_as_before():
    assert rules.is_ready(post(ready_to_close=True, conf=0.2), unseen_evidence=3, tools_left=2)


def test_confident_and_waiting_on_nothing_is_ready():
    assert rules.is_ready(post(conf=rules.READY_CONFIDENCE), unseen_evidence=0, tools_left=1)
    assert not rules.is_ready(post(conf=rules.READY_CONFIDENCE - 0.01), unseen_evidence=0, tools_left=1)


def test_nothing_left_to_check_is_ready_even_at_low_confidence():
    assert rules.is_ready(post(conf=0.3), unseen_evidence=0, tools_left=0)


def test_something_unchecked_is_not_ready():
    assert not rules.is_ready(post(conf=0.3), unseen_evidence=1, tools_left=0)     # evidence it has not seen
    assert not rules.is_ready(post(conf=0.3), unseen_evidence=0, tools_left=1)     # a tool it could still use


def test_confidence_alone_never_overrides_unseen_evidence():
    assert not rules.is_ready(post(conf=0.99), unseen_evidence=1, tools_left=0)


def test_open_requests_challenges_and_questions_block_the_new_clauses():
    from deadlang.schemas import SpecialistRequest
    req = SpecialistRequest(capability="seller_inventory", question="q", reason="r")
    assert not rules.is_ready(post(conf=0.99, requests=[req]), unseen_evidence=0, tools_left=0)
    assert not rules.is_ready(post(conf=0.99, challenge=Challenge(target_agent="defender", question="?")),
                              unseen_evidence=0, tools_left=0)
    assert not rules.is_ready(post(conf=0.99), unseen_evidence=0, tools_left=0, questions_pending=True)


# ---------------- stop rule with an agent sitting out ----------------

A = ("buyer", "defender", "caseload")


def two(stances=("file", "dismiss"), conf=0.9, **kw):
    return {a: StancePost(agent=a, round=2, stance=s, confidence=conf, claims=[], **kw)
            for a, s in zip(A[:2], stances)}


def test_two_participants_are_unanimous_when_expected_is_two():
    assert rules.stop_reason(1, 4, two(("file", "file")), None, 0, expected=2) == "unanimous"
    assert rules.stop_reason(1, 4, two(("file", "file")), None, 0) is None          # the default still means three


def test_ready_to_close_uses_the_ready_map_when_given():
    ready = {"buyer": True, "defender": True}
    assert rules.stop_reason(2, 4, two(), None, 0, expected=2, ready=ready) == "ready_to_close"
    assert rules.stop_reason(1, 4, two(), None, 0, expected=2, ready=ready) is None   # still not before round 2
    assert rules.stop_reason(2, 4, two(), None, 0, expected=2, ready={"buyer": True, "defender": False}) is None


def test_the_ready_map_replaces_the_posts_own_flags():
    flagged = two(ready_to_close=True)
    assert rules.stop_reason(2, 4, flagged, None, 0, expected=2, ready={"buyer": True, "defender": False}) is None


@pytest.mark.parametrize("stances,expected", [
    (("file", "file"), "FILE"),
    (("dismiss", "dismiss"), "DISMISS"),
    (("file", "dismiss"), "CONTESTED"),
    (("file", "need_more"), "WATCHLIST"),
    (("need_more", "need_more"), "WATCHLIST"),
])
def test_a_listing_with_nothing_to_compare_resolves_from_buyer_and_defender(stances, expected):
    assert rules.outcome(dict(zip(A[:2], stances))) == expected


# ---------------- who is woken in later rounds ----------------

def case_state(buyer_post, n_evidence=3, seen=None):
    listing = make_listing()
    board = EvidenceBoard("C-1")
    for i in range(n_evidence):
        board.add(ev("price_check" if i else "listing_snapshot", E0), "intake")
    st = CaseState("C-1", listing, FakeMarket(listing).seller, board)
    st.attempted = {"price_check", "seller_inventory", "linked_sellers", "legal_lookup", "material_exam"}
    st.current = {"buyer": buyer_post}
    st.seen = seen if seen is not None else {a: n_evidence for a in A}
    return st


def facilitator():
    return Facilitator(FakeMarket(), FakeTransport(), FakeDiscovery(), bus=None)


def rebut(target):
    return Rebuttal(target_agent=target, target_claim="x", response="y")


def test_an_agent_with_nothing_left_is_not_woken_by_a_rebuttal_alone():
    st = case_state(post(conf=0.9))
    st.last_round_posts = [StancePost(agent="defender", round=1, stance="dismiss", confidence=0.6, claims=[],
                                      rebuttal=rebut("buyer"))]
    assert "buyer" not in facilitator()._active(st, 2)


def test_but_an_agent_that_is_not_ready_is_still_woken_by_a_rebuttal():
    st = case_state(post(conf=0.5).model_copy(update={"requests": []}), n_evidence=3)
    st.attempted = {"price_check"}                                      # tools it could still use: not ready
    st.last_round_posts = [StancePost(agent="defender", round=1, stance="dismiss", confidence=0.6, claims=[],
                                      rebuttal=rebut("buyer"))]
    assert "buyer" in facilitator()._active(st, 2)


def test_new_evidence_it_has_not_seen_always_wakes_an_agent():
    st = case_state(post(conf=0.9), n_evidence=4, seen={"buyer": 3, "defender": 4, "caseload": 4})
    assert facilitator()._active(st, 2) == ["buyer"]


def test_a_direct_question_always_wakes_an_agent():
    st = case_state(post(conf=0.9))
    st.last_round_posts = [StancePost(agent="defender", round=1, stance="dismiss", confidence=0.6, claims=[],
                                      challenge=Challenge(target_agent="buyer", question="why?"))]
    assert "buyer" in facilitator()._active(st, 2)


def test_round_one_still_calls_everyone_who_is_not_sitting_out():
    assert facilitator()._active(case_state(post()), 1) == ["buyer", "defender", "caseload"]
