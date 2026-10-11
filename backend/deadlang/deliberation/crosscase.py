"""Is there anything for the Case Officer to compare this listing with? Read from the evidence board, no model involved.

The Case Officer's job is cross-case: a seller with many items, linked sellers, reused photos. If the board shows
none of that, an empty Case Officer would just drag the outcome toward WATCHLIST, so the Facilitator lets it sit out and
says so ("No other cases to compare"). It sits out only when the board POSITIVELY shows nothing: a check that
failed to run, or evidence we cannot read, leaves the question open and the Case Officer speaks.
"""
from __future__ import annotations

from dataclasses import dataclass

from deadlang.evidence.board import EvidenceBoard
from deadlang.schemas import AgentName

# The role that sits out when there is nothing to compare. Typed as AgentName so a rename of the roster is caught
# by the type checker, and tests/test_roster_drift.py fails if this ever stops naming a real agent.
CROSS_CASE_ROLE: AgentName = "case_officer"

# What counts as something to compare. Price comparables are deliberately NOT a source: almost every listing has
# them (490 of 498 in the first dataset), so counting them would almost never let the Case Officer sit out. They are still
# read from the board (CrossCase.price_comparables); add "price_comparables" here to count them.
CROSS_CASE_SOURCES = ("seller_other_listings", "linked_sellers", "photo_reuse")

_FIELD = {"seller_other_listings": "seller_other_listings", "linked_sellers": "linked_sellers",
          "photo_reuse": "photo_reuse_hits", "price_comparables": "price_comparables"}

NO_CROSS_CASE_TAKE = "No other cases to compare, so I'm sitting this one out."


@dataclass(frozen=True)
class CrossCase:
    """Counts found on the board. None means that check has not reported (or could not be read)."""
    seller_other_listings: int | None
    linked_sellers: int | None
    photo_reuse_hits: int | None
    price_comparables: int | None

    def _counted(self) -> list[int | None]:
        return [getattr(self, _FIELD[s]) for s in CROSS_CASE_SOURCES]

    @property
    def available(self) -> bool:
        return any(c for c in self._counted() if c)

    @property
    def unknown(self) -> bool:
        return any(c is None for c in self._counted())

    @property
    def nothing_to_compare(self) -> bool:
        return not self.available and not self.unknown


def assess(board: EvidenceBoard) -> CrossCase:
    e0 = board.get("E0")
    seller_id = e0.data.get("seller_id") if e0 else None
    others = linked = photos = comparables = None
    for e in board.all():                                   # a later item for the same check replaces an earlier one
        d = e.data
        if (e.capability == "seller_inventory" and isinstance(d.get("listing_count"), int)
                and seller_id is not None and d.get("seller_id") == seller_id):
            others = max(d["listing_count"] - 1, 0)         # the inventory includes the listing itself
        elif (e.capability == "linked_sellers" and isinstance(d.get("linked_seller_count"), int)
                and isinstance(d.get("linked"), list)):
            linked = d["linked_seller_count"]
            photos = sum(int(x.get("shared_photo_count") or 0) for x in d["linked"] if isinstance(x, dict))
        elif e.capability == "price_check" and "ratio" in d and isinstance(d.get("n"), int):
            comparables = d["n"] if d["ratio"] is not None else 0     # no ratio means too few to compare with
    return CrossCase(others, linked, photos, comparables)
