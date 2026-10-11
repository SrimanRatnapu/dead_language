"""Pre-agreed, published stop and outcome rules. Pure functions; the Facilitator only applies them."""
from __future__ import annotations

from deadlang.schemas import AgentName, Outcome, StancePost, Stance


def outcome(final: dict[AgentName, Stance]) -> Outcome:
    stances = set(final.values())
    if stances == {"file"}:
        return "FILE"
    if stances == {"dismiss"}:
        return "DISMISS"
    if "file" in stances and "dismiss" in stances:
        return "CONTESTED"
    return "WATCHLIST"


READY_CONFIDENCE = 0.85      # confident enough to stop, if nothing is waiting on the agent


def is_ready(post: StancePost, *, unseen_evidence: int, tools_left: int, questions_pending: bool = False) -> bool:
    """Ready to close when ANY of: the agent says so (as before); it is confident enough and waiting on nothing;
    or there is nothing left for it to check. "Waiting on something" means evidence on the board it has not
    seen, an open request or challenge of its own, or a question put to it. `tools_left` is how many specialist
    checks could still be run for this case."""
    if post.ready_to_close:
        return True
    if questions_pending or post.requests or post.challenge is not None or unseen_evidence > 0:
        return False
    return post.confidence >= READY_CONFIDENCE or tools_left == 0


def is_unanimous(stances: dict[AgentName, Stance], expected: int) -> bool:
    """Every agent taking part (`expected` of them, whoever sat out excluded) says file, or every one says dismiss."""
    return len(stances) == expected and set(stances.values()) in ({"file"}, {"dismiss"})
