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


def stop_reason(round_no: int, max_rounds: int,
                this_round: dict[AgentName, StancePost],
                prev_round: dict[AgentName, StancePost] | None,
                new_evidence_this_round: int) -> str | None:
    """this_round / prev_round hold all three agents' CURRENT posts (carried-forward ones included).
    Returns "unanimous" | "ready_to_close" | "no_movement" | "max_rounds" | None. Budget is the Facilitator's."""
    stances = {p.stance for p in this_round.values()}
    if len(this_round) == 3 and stances in ({"file"}, {"dismiss"}):
        return "unanimous"
    if round_no >= 2 and len(this_round) == 3 and all(p.ready_to_close for p in this_round.values()):
        return "ready_to_close"
    if (prev_round is not None and new_evidence_this_round == 0
            and all(a in prev_round and prev_round[a].stance == p.stance
                    and abs(prev_round[a].confidence - p.confidence) < 0.10
                    for a, p in this_round.items())):
        return "no_movement"
    if round_no >= max_rounds:
        return "max_rounds"
    return None
