import pytest

from deadlang.deliberation.rules import is_unanimous, outcome
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


def test_unanimity_needs_every_agent_taking_part_to_agree():
    stances = lambda *v: dict(zip(A, v))  # noqa: E731
    assert is_unanimous(stances("file", "file", "file"), 3) and is_unanimous(stances("dismiss", "dismiss", "dismiss"), 3)
    assert not is_unanimous(stances("file", "file", "need_more"), 3)
    assert not is_unanimous(stances("file", "dismiss", "file"), 3)
    assert is_unanimous({"undercover": "file", "counsel": "file"}, 2)       # the case officer sat out
    assert not is_unanimous({"undercover": "file", "counsel": "file"}, 3)   # one has not spoken
