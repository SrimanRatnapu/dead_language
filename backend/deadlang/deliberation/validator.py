"""Claim validator: code that checks every claim an agent makes against the evidence board."""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import permutations

from deadlang.evidence.board import EvidenceBoard, numbers_from_text
from deadlang.schemas import AgentName, StancePost

ID_RE = re.compile(r"\bE\d+\b")
QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')


@dataclass
class Rejection:
    agent: AgentName
    round: int
    claim_text: str
    reasons: list[str]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.5 or abs(a - b) <= 0.10 * abs(b)


def _number_ok(n: float, evidence_numbers: list[float]) -> bool:
    if any(_close(n, e) for e in evidence_numbers):
        return True
    # "about 15x" style: ratio of two cited numbers, rounded to 1 decimal
    uniq = set(evidence_numbers)
    return any(b != 0 and _close(n, round(a / b, 1)) for a, b in permutations(uniq, 2))


def _claim_reasons(text: str, ids: list[str], board: EvidenceBoard, listing_text: str) -> list[str]:
    if not ids:
        return ["no evidence cited"]
    missing = [i for i in ids if i not in board.ids()]
    if missing:
        return [f"cites {i}, which does not exist" for i in missing]

    reasons: list[str] = []
    ev_numbers = board.numbers_in(ids)
    cited = ", ".join(ids)
    for n in numbers_from_text(ID_RE.sub("", text)):
        if n.is_integer() and n <= 3:
            continue  # small counts ("2 photos") are too noisy to check
        if not _number_ok(n, ev_numbers):
            shown = int(n) if n == int(n) else n
            reasons.append(f"number {shown} not found in cited evidence {cited}")

    haystack = _norm(board.text_in(ids)) + " " + _norm(listing_text)
    for m in QUOTE_RE.finditer(text):
        quoted = _norm(m.group(1) or m.group(2))
        if len(quoted.split()) >= 3 and quoted not in haystack:
            reasons.append("quoted text not found in cited evidence or listing")
    return reasons


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta) if ta else 0.0


def validate_post(post: StancePost, board: EvidenceBoard, listing_text: str,
                  previous: StancePost | None, round_no: int,
                  last_round_posts: list[StancePost]) -> tuple[StancePost, list[Rejection], list[str]]:
    """Return (cleaned_post, rejections, post_level_problems). Call only for agents called this round."""
    kept, rejections = [], []
    for claim in post.claims:
        reasons = _claim_reasons(claim.text, claim.evidence_ids, board, listing_text)
        if reasons:
            rejections.append(Rejection(post.agent, post.round, claim.text, reasons))
        else:
            kept.append(claim)
    update: dict = {"claims": kept}
    problems: list[str] = []

    if round_no >= 2:
        r = post.rebuttal
        if r is None:
            problems.append("round 2+ requires a rebuttal of the strongest opposing claim")
        else:
            target_claims = [c.text for p in last_round_posts if p.agent == r.target_agent for c in p.claims]
            if not any(_overlap(r.target_claim, t) >= 0.6 for t in target_claims):
                problems.append("rebuttal target claim not found")
            if any(i not in board.ids() for i in r.evidence_ids):
                problems.append("rebuttal cites evidence that does not exist")

    if previous is not None and post.stance != previous.stance:
        ids = post.changed_because_evidence
        if not post.changed_because or not ids or any(i not in board.ids() for i in ids):
            problems.append("stance changed without citing the evidence that changed it")

    if len(post.requests) > 2:
        update["requests"] = post.requests[:2]
        problems.append("max 2 requests")

    if post.challenge is not None and post.challenge.target_agent == post.agent:
        update["challenge"] = None
        problems.append("cannot challenge yourself")

    return post.model_copy(update=update), rejections, problems


def apply_empty_claims_rule(post: StancePost) -> tuple[StancePost, str | None]:
    """You cannot take a side without a grounded reason: file/dismiss with zero valid claims -> need_more."""
    if not post.claims and post.stance in ("file", "dismiss"):
        return post.model_copy(update={"stance": "need_more"}), "no grounded claims left; stance set to need_more"
    return post, None
