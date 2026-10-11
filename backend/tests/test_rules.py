import pytest

from deadlang.deliberation.rules import outcome, stop_reason
from deadlang.schemas import StancePost

A = ("undercover", "counsel", "case_officer")


def posts(stances, conf=0.7, ready=False):
    return {a: StancePost(agent=a, round=1, stance=s, confidence=c if isinstance(c := conf, float) else conf[i],
                          claims=[], ready_to_close=ready) for i, (a, s) in enumerate(zip(A, stances))}


@pytest.mark.parametrize("stances,expected", [
    (("file", "file", "file"), "FILE"),
    (("dismiss",) * 3, "DISMISS"),
    (("file", "dismiss", "need_more"), "CONTESTED"),
    (("file", "dismiss", "dismiss"), "CONTESTED"),
    (("file", "file", "need_more"), "WATCHLIST"),
    (("need_more",) * 3, "WATCHLIST"),
    (("dismiss", "dismiss", "need_more"), "WATCHLIST"),
])
def test_outcome(stances, expected):
    assert outcome(dict(zip(A, stances))) == expected


def test_unanimous_beats_everything():
    assert stop_reason(1, 4, posts(("file",) * 3), None, 5) == "unanimous"
    assert stop_reason(2, 4, posts(("dismiss",) * 3, ready=True), posts(("file",) * 3), 0) == "unanimous"


def test_ready_to_close_needs_round_2_and_all_three():
    split = ("file", "dismiss", "need_more")
    assert stop_reason(1, 4, posts(split, ready=True), None, 1) is None       # round 1 never closes early
    assert stop_reason(2, 4, posts(split, ready=True), posts(split, conf=0.3), 1) == "ready_to_close"
    mixed = posts(split, ready=True); mixed["undercover"] = mixed["undercover"].model_copy(update={"ready_to_close": False})
    assert stop_reason(2, 4, mixed, posts(split, conf=0.3), 1) is None


def test_no_movement_branches():
    split = ("file", "dismiss", "need_more")
    prev = posts(split, conf=0.7)
    assert stop_reason(1, 4, prev, None, 0) is None                                # round 1: no prev, never no_movement
    assert stop_reason(2, 4, posts(split, conf=0.75), prev, 0) == "no_movement"    # |delta| < 0.10
    assert stop_reason(2, 4, posts(split, conf=0.9), prev, 0) is None              # confidence moved
    assert stop_reason(2, 4, posts(split, conf=0.7), prev, 1) is None              # new evidence arrived
    assert stop_reason(2, 4, posts(("file", "file", "need_more")), prev, 0) is None  # stance changed


def test_carried_forward_posts_count_as_unchanged():
    split = ("file", "dismiss", "need_more")
    prev = posts(split)
    assert stop_reason(3, 4, dict(prev), prev, 0) == "no_movement"


def test_max_rounds():
    split = ("file", "dismiss", "need_more")
    assert stop_reason(4, 4, posts(split, conf=0.9), posts(split, conf=0.5), 2) == "max_rounds"
    assert stop_reason(3, 4, posts(split, conf=0.9), posts(split, conf=0.5), 2) is None
