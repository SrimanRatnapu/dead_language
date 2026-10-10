"""Scripted fakes for transport, discovery and marketplace so the Facilitator can be tested without B or A."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from deadlang.llm import BudgetExceeded
from deadlang.schemas import (Claim, DeliberationTurn, EvidenceDraft, Listing, Seller, SpecialistCall,
                              SpecialistReply, StancePost)

CAP_SPECIALISTS = {
    "price_check": ["deadlang-price-checker"],
    "seller_inventory": ["deadlang-seller-inventory"],
    "linked_sellers": ["deadlang-linked-sellers"],
    "legal_lookup": ["deadlang-legal-table"],
    "material_exam": ["deadlang-examiner-thorough", "deadlang-examiner-quick"],
    "translation": ["deadlang-translator"],
}


def make_listing(**kw) -> Listing:
    base = dict(id="L0101", marketplace="reconstructed", seller_id="S0042", title="Antique carved bone netsuke",
                description="Old bone netsuke from a family collection", price_usd=1450.0, category="Antiques",
                stated_material="bone", item_type="netsuke", ship_from="HK", image_paths=["images/L0101_0.jpg"],
                posted_at="2026-10-01T09:30:00+00:00")
    return Listing(**{**base, **kw})


class FakeMarket:
    def __init__(self, listing: Listing | None = None):
        self.listing = listing or make_listing()
        self.seller = Seller(id=self.listing.seller_id, name="OrientalCuriosHK", location="HK", joined="2024-01-01")

    async def get_listing_snapshot(self, listing_id: str) -> Listing:
        return self.listing

    async def all_active(self) -> list[Listing]:
        return [self.listing]

    async def remove_listing(self, listing_id: str) -> str | None:
        return "L0456"

    async def reset_demo(self) -> None: ...

    async def get_seller(self, seller_id: str) -> Seller:
        return self.seller


@dataclass
class Selection:
    specialist_name: str
    why: str
    candidates: list[str]


class FakeDiscovery:
    def __init__(self, table: dict[str, list[str]] | None = None):
        self.table = table or CAP_SPECIALISTS
        self.unhealthy: set[str] = set()

    async def register_all(self) -> None: ...

    async def select(self, capability, exclude=frozenset()):
        cands = [n for n in self.table.get(capability, []) if n not in exclude and n not in self.unhealthy]
        if not cands:
            return None
        return Selection(cands[0], f"{cands[0]} chosen for {capability}.", cands)

    async def mark_unhealthy(self, name: str) -> None:
        self.unhealthy.add(name)

    def record_latency(self, name: str, ms: float) -> None: ...


def draft(capability, summary="ok", data=None, name="fake") -> EvidenceDraft:
    return EvidenceDraft(capability=capability, summary=summary, data=data or {}, produced_by="code", specialist_name=name)


@dataclass
class FakeTransport:
    posts: dict[tuple[str, int], StancePost | str] = field(default_factory=dict)       # (agent, round) -> reply
    repairs: dict[tuple[str, int], StancePost | str] = field(default_factory=dict)
    replies: dict[str, SpecialistReply] = field(default_factory=dict)                   # specialist name -> reply
    timeouts: set[str] = field(default_factory=set)
    budget_in_round: int | None = None
    on_broadcast: Callable[[int], Awaitable[None]] | None = None
    broadcasts: list[tuple[int, list[str]]] = field(default_factory=list)
    calls: list[tuple[str, SpecialistCall]] = field(default_factory=list)
    repair_calls: list[tuple[str, DeliberationTurn]] = field(default_factory=list)

    async def call_specialist(self, name: str, call: SpecialistCall, timeout: float = 45.0) -> SpecialistReply:
        self.calls.append((name, call))
        if name in self.timeouts:
            return SpecialistReply(ok=False, error="timeout")
        if name in self.replies:
            return self.replies[name]
        return SpecialistReply(ok=True, drafts=[draft(call.capability, f"{call.capability} result", {"n": 1}, name)])

    async def broadcast_turns(self, turns, timeout: float = 90.0):
        r = next(iter(turns.values())).round
        self.broadcasts.append((r, list(turns)))
        if self.on_broadcast:
            await self.on_broadcast(r)
        if self.budget_in_round == r:
            raise BudgetExceeded("case token cap reached")
        return {a: self.posts.get((a, r), "no script") for a in turns}

    async def call_agent(self, agent, turn: DeliberationTurn, timeout: float = 90.0):
        self.repair_calls.append((agent, turn))
        return self.repairs.get((agent, turn.round), "no repair")


def post(agent, rnd, stance, conf=0.7, claims=None, **kw) -> StancePost:
    claims = claims if claims is not None else [("Listed at $1,450.", ["E0"])]
    return StancePost(agent=agent, round=rnd, stance=stance, confidence=conf,
                      claims=[Claim(text=t, evidence_ids=i) for t, i in claims], **kw)
