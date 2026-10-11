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


def stop_reason(round_no: int, max_rounds: int,
                this_round: dict[AgentName, StancePost],
                prev_round: dict[AgentName, StancePost] | None,
                new_evidence_this_round: int,
                expected: int = 3,
                ready: dict[AgentName, bool] | None = None) -> str | None:
    """this_round / prev_round hold the CURRENT posts (carried-forward ones included) of the agents taking part:
    all three, or two when Caseload sits out (then pass expected=2). `ready` says who is ready to close; without
    it each post's own ready_to_close flag is used.
    Returns "unanimous" | "ready_to_close" | "no_movement" | "max_rounds" | None. Budget is the Facilitator's."""
    stances = {p.stance for p in this_round.values()}
    if len(this_round) == expected and stances in ({"file"}, {"dismiss"}):
        return "unanimous"
    flags = ready if ready is not None else {a: p.ready_to_close for a, p in this_round.items()}
    if round_no >= 2 and len(this_round) == expected and all(flags.get(a, False) for a in this_round):
        return "ready_to_close"
    if (prev_round is not None and new_evidence_this_round == 0
            and all(a in prev_round and prev_round[a].stance == p.stance
                    and abs(prev_round[a].confidence - p.confidence) < 0.10
                    for a, p in this_round.items())):
        return "no_movement"
    if round_no >= max_rounds:
        return "max_rounds"
    return None
