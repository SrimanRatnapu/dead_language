"""Case file assembly. The tip draft is a code template over validated claims only; no model is involved."""
from __future__ import annotations

from deadlang.evidence.board import EvidenceBoard
from deadlang.schemas import CaseFile, Listing, Outcome, Seller, StancePost

ORDER = ("undercover", "counsel", "case_officer")


def _linked(board: EvidenceBoard) -> list[tuple[str, str]]:
    out: dict[str, str] = {}
    for e in board.all():
        if e.capability == "linked_sellers":
            for item in e.data.get("linked", []):
                out[item["seller_id"]] = item.get("seller_name") or item["seller_id"]
    return list(out.items())


def build_case_file(case_id: str, listing: Listing, seller: Seller, outcome: Outcome, rounds_used: int,
                    stop_reason: str, final_posts: list[StancePost], board: EvidenceBoard) -> CaseFile:
    legal = [e.summary for e in board.all() if e.capability == "legal_lookup"]
    linked = _linked(board)
    ordered = sorted(final_posts, key=lambda p: ORDER.index(p.agent))
    tip = None
    if outcome in ("FILE", "CONTESTED"):
        seen, key_lines = set(), []
        for p in ordered:
            for c in p.claims:
                if c.text not in seen and len(key_lines) < 6:
                    seen.add(c.text)
                    key_lines.append(f"- {c.text} [{', '.join(c.evidence_ids)}]")
        tip = "\n".join([
            "Possible elephant ivory offered for sale — prepared for human review, not sent.",
            f'Listing: {listing.id} "{listing.title}" — ${listing.price_usd:,.0f} — ships from {listing.ship_from}'
            f" — seller {seller.name} ({seller.id})",
            f"Outcome of agent review: {outcome}",
            "Key evidence:", *key_lines,
            "Linked sellers: " + (", ".join(f"{n} ({i})" for i, n in linked) or "none found"),
            "Legal basis: " + (" ".join(legal) or "none on the board"),
            "Positions: " + ", ".join(f"{p.agent.replace("_", " ").title()} {p.stance} ({p.confidence:.2f})" for p in ordered),
        ])
    return CaseFile(case_id=case_id, listing_id=listing.id, seller_id=seller.id, outcome=outcome,
                    rounds_used=rounds_used, stop_reason=stop_reason, final_positions=ordered,
                    evidence=board.all(), legal_basis=legal, linked_seller_ids=[i for i, _ in linked],
                    tip_draft=tip)
