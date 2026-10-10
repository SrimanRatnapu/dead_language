"""Facilitator: referee of process. Runs intake, wakes agents, validates claims, applies published rules.

It never decides an outcome; `rules.outcome` and `rules.stop_reason` do.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from deadlang.deliberation import rules
from deadlang.deliberation.casefile import build_case_file
from deadlang.deliberation.validator import Rejection, apply_empty_claims_rule, validate_post
from deadlang.evidence.board import EvidenceBoard
from deadlang.llm import BudgetExceeded
from deadlang.schemas import (AgentName, Capability, CaseFile, DeliberationTurn, EvidenceDraft, Listing,
                              PeerQuestion, Requester, Seller, SpecialistCall, StancePost)

AGENTS: tuple[AgentName, ...] = ("buyer", "defender", "caseload")
MAX_CALLS_PER_ROUND = 3
MAX_CALLS_PER_CASE = 6


@dataclass
class CaseState:
    case_id: str
    listing: Listing
    seller: Seller
    board: EvidenceBoard
    current: dict[AgentName, StancePost] = field(default_factory=dict)   # each agent's latest validated post
    transcript: list[StancePost] = field(default_factory=list)           # every validated post, in order
    last_round_posts: list[StancePost] = field(default_factory=list)
    seen: dict[AgentName, int] = field(default_factory=dict)             # board size at each agent's last turn
    requested_calls: int = 0
    removal_noted: bool = False
    relist_noted: bool = False
    answered: set[tuple[str, str]] = field(default_factory=set)         # (asker, question) already delivered

    @property
    def listing_text(self) -> str:
        return f"{self.listing.title}\n{self.listing.description}"


class Facilitator:
    def __init__(self, market: Any, transport: Any, discovery: Any, bus: Any, max_rounds: int = 4):
        self.market, self.transport, self.discovery, self.bus = market, transport, discovery, bus
        self.max_rounds = max_rounds
        self._running: dict[str, CaseState] = {}

    # ------------------------------------------------------------------ evidence + specialists
    def _add(self, st: CaseState, draft: EvidenceDraft, requested_by: Requester) -> None:
        ev = st.board.add(draft, requested_by)
        self.bus.emit(st.case_id, "evidence.added", {"evidence": ev.model_dump(mode="json")})

    def _emit_selected(self, st: CaseState, capability: str, sel: Any, requested_by: str) -> None:
        self.bus.emit(st.case_id, "specialist.selected", {
            "capability": capability, "specialist_name": sel.specialist_name, "why": sel.why,
            "requested_by": requested_by, "candidates": list(sel.candidates)})

    async def _run_specialist(self, st: CaseState, capability: Capability, params: dict[str, Any],
                              requested_by: Requester, question: str = "") -> None:
        tried: set[str] = set()
        sel = await self.discovery.select(capability, exclude=tried)
        if sel is None:
            self.bus.emit(st.case_id, "specialist.failed", {
                "capability": capability, "specialist_name": "", "error": "no specialist registered", "fallback": None})
            return
        for hop in range(2):                                   # preferred, then one fallback hop
            self._emit_selected(st, capability, sel, requested_by)
            reply = await self.transport.call_specialist(sel.specialist_name, SpecialistCall(
                case_id=st.case_id, listing_id=st.listing.id, capability=capability, question=question, params=params))
            if reply.ok:
                for draft in reply.drafts:
                    self._add(st, draft, requested_by)
                return
            err = reply.error or ""
            if err == "listing_removed":
                await self.notify_listing_removed(st.listing.id, None)
                return
            if hop == 0 and (err == "timeout" or "connect" in err.lower()):
                await self.discovery.mark_unhealthy(sel.specialist_name)
                tried.add(sel.specialist_name)
                nxt = await self.discovery.select(capability, exclude=tried)
                self.bus.emit(st.case_id, "specialist.failed", {
                    "capability": capability, "specialist_name": sel.specialist_name, "error": err,
                    "fallback": nxt.specialist_name if nxt else None})
                if nxt is None:
                    return
                sel = nxt
                continue
            self.bus.emit(st.case_id, "specialist.failed", {
                "capability": capability, "specialist_name": sel.specialist_name, "error": err, "fallback": None})
            return

    async def notify_listing_removed(self, listing_id: str, relisted_as: str | None) -> None:
        """Idempotent; a later call may add the relist id to an already-recorded removal."""
        for st in list(self._running.values()):
            if st.listing.id != listing_id:
                continue
            if st.removal_noted and (relisted_as is None or st.relist_noted):
                continue
            notice = lambda summary, data: EvidenceDraft(  # noqa: E731
                capability="system_notice", summary=summary, data=data, produced_by="code", specialist_name="facilitator")
            if not st.removal_noted:
                st.removal_noted = True
                hhmm = datetime.now(timezone.utc).strftime("%H:%M")
                self._add(st, notice(f"Listing {listing_id} was removed by the seller at {hhmm}; the review continues "
                                     "from the snapshot in E0.", {"listing_id": listing_id, "removed_at": hhmm}), "system")
            if relisted_as:
                st.relist_noted = True
                self._add(st, notice(f"A new listing {relisted_as} appeared after the removal; linked_sellers can "
                                     "check whether it is related.",
                                     {"listing_id": listing_id, "relisted_as": relisted_as}), "system")
            self.bus.emit(st.case_id, "listing.removed", {"listing_id": listing_id, "relisted_as": relisted_as})

    # ------------------------------------------------------------------ rounds
    def _active(self, st: CaseState, r: int) -> list[AgentName]:
        # Speaking order rotates each round so no agent always goes first or last.
        order = [AGENTS[(r - 1 + i) % len(AGENTS)] for i in range(len(AGENTS))]
        if r == 1:
            return order
        targeted = {p.rebuttal.target_agent for p in st.last_round_posts if p.rebuttal}
        targeted |= {p.challenge.target_agent for p in st.last_round_posts if p.challenge
                     and (p.agent, p.challenge.question) not in st.answered}
        return [a for a in order if st.board.count() > st.seen.get(a, 0) or a in targeted]

    def _turn(self, st: CaseState, a: AgentName, r: int, this_round: list[StancePost]) -> DeliberationTurn:
        # Questions from last round, plus any asked earlier in this round (answered once, never re-delivered).
        questions = []
        for p in [*st.last_round_posts, *this_round]:
            if p.challenge and p.challenge.target_agent == a and (p.agent, p.challenge.question) not in st.answered:
                st.answered.add((p.agent, p.challenge.question))
                questions.append(PeerQuestion(asker=p.agent, question=p.challenge.question))
        return DeliberationTurn(case_id=st.case_id, round=r, max_rounds=self.max_rounds,
                                evidence=st.board.all(), transcript=list(st.transcript),
                                your_previous=st.current.get(a), questions_for_you=questions)

    @staticmethod
    def _fallback_post(st: CaseState, a: AgentName, r: int) -> StancePost:
        prev = st.current.get(a)
        if prev is None:
            return StancePost(agent=a, round=r, stance="need_more", confidence=0.0, claims=[])
        return prev.model_copy(update={"round": r, "rebuttal": None, "requests": [], "challenge": None,
                                       "changed_because": None, "changed_because_evidence": []})

    async def _resolve(self, st: CaseState, a: AgentName, turn: DeliberationTurn, result: Any,
                       latest: list[StancePost], r: int) -> tuple[StancePost, list[Rejection]]:
        if not isinstance(result, StancePost):                      # error string: carry the previous stance over
            return self._fallback_post(st, a, r), []
        prev = st.current.get(a)
        cleaned, rejections, problems = validate_post(result, st.board, st.listing_text, prev, r, latest)
        if rejections or problems:
            feedback = problems + [f'Your claim "{rj.claim_text}" was removed: {"; ".join(rj.reasons)}'
                                   for rj in rejections]
            second = await self.transport.call_agent(a, turn.model_copy(update={"repair_feedback": feedback}))
            if isinstance(second, StancePost):
                cleaned, rejections, _ = validate_post(second, st.board, st.listing_text, prev, r, latest)
        cleaned, _ = apply_empty_claims_rule(cleaned)
        return cleaned, rejections

    async def _run_round(self, st: CaseState, r: int, active: list[AgentName]) -> int:
        """Run one round for the active agents. Returns the number of evidence items added during it."""
        start_count = st.board.count()
        posts: list[StancePost] = []
        for a in active:                                    # one at a time: each agent reads the posts made before it
            st.seen[a] = start_count
            turn = self._turn(st, a, r, posts)
            results = await self.transport.broadcast_turns({a: turn})
            post, rejections = await self._resolve(st, a, turn, results.get(a, "no reply"), list(st.current.values()), r)
            for rj in rejections:
                self.bus.emit(st.case_id, "claim.rejected", {
                    "agent": rj.agent, "round": rj.round, "claim_text": rj.claim_text, "reasons": rj.reasons})
            self.bus.emit(st.case_id, "stance.posted", {"post": post.model_dump(mode="json")})
            posts.append(post)
            st.transcript.append(post)
            st.current[a] = post
        st.last_round_posts = posts

        seen_keys: set[tuple[str, str]] = set()
        jobs = []
        for p in posts:
            for req in p.requests:
                key = (req.capability, json.dumps(req.params, sort_keys=True))
                if key in seen_keys:
                    continue
                if len(jobs) >= MAX_CALLS_PER_ROUND or st.requested_calls >= MAX_CALLS_PER_CASE:
                    continue
                seen_keys.add(key)
                st.requested_calls += 1
                jobs.append(self._run_specialist(st, req.capability, req.params, p.agent, req.question))
        await asyncio.gather(*jobs)
        return st.board.count() - start_count

    # ------------------------------------------------------------------ case
    async def _new_state(self, case_id: str, listing_id: str) -> CaseState:
        listing = await self.market.get_listing_snapshot(listing_id)
        seller = await self.market.get_seller(listing.seller_id)
        st = CaseState(case_id, listing, seller, EvidenceBoard(case_id))
        self.bus.emit(case_id, "case.started", {"listing": listing.model_dump(mode="json"),
                                                "seller": seller.model_dump(mode="json")})
        return st

    async def _intake(self, st: CaseState) -> None:
        listing, seller = st.listing, st.seller
        self._add(st, EvidenceDraft(
            capability="listing_snapshot", produced_by="code", specialist_name="intake", data=listing.model_dump(mode="json"),
            summary=(f'Listing {listing.id} by {seller.name}: "{listing.title}" for ${listing.price_usd:,.0f}, '
                     f"described as {listing.stated_material}, ships from {listing.ship_from}, "
                     f"{len(listing.image_paths)} photos.")), "intake")
        caps: list[Capability] = ["price_check", "seller_inventory", "linked_sellers", "legal_lookup", "material_exam"]
        if listing.language != "en":
            caps.append("translation")
        await asyncio.gather(*(self._run_specialist(st, c, {}, "intake") for c in caps))

    async def run_intake(self, case_id: str, listing_id: str) -> CaseState:
        """Intake only (E0 + specialists). The eval runner computes it once and reuses it via run_case(intake=...)."""
        st = await self._new_state(case_id, listing_id)
        self._running[case_id] = st
        try:
            await self._intake(st)
        finally:
            self._running.pop(case_id, None)
        return st

    async def run_case(self, case_id: str, listing_id: str, intake: CaseState | None = None) -> CaseFile:
        st = await self._new_state(case_id, listing_id)
        self._running[case_id] = st
        try:
            return await self._run(st, intake)
        finally:
            self._running.pop(case_id, None)

    async def _run(self, st: CaseState, intake: CaseState | None) -> CaseFile:
        case_id, listing, seller = st.case_id, st.listing, st.seller
        reason: str | None = None
        rounds_used = 0
        try:
            if intake is None:
                await self._intake(st)
            else:                                           # replay precomputed intake evidence in order
                for ev in intake.board.all():
                    self._add(st, EvidenceDraft.model_validate(ev.model_dump(include=set(EvidenceDraft.model_fields))),
                              ev.requested_by)

            for r in range(1, self.max_rounds + 1):
                rounds_used = r
                active = self._active(st, r)
                self.bus.emit(case_id, "round.started", {"round": r, "active": active})
                before = dict(st.current) or None            # all three agents' posts before this round
                new_evidence = await self._run_round(st, r, active) if active else 0
                reason = rules.stop_reason(r, self.max_rounds, dict(st.current), before, new_evidence)
                if reason:
                    break
        except BudgetExceeded as exc:
            self.bus.emit(case_id, "budget.exceeded", {"detail": str(exc)})
            reason = "budget"

        finals = [st.current.get(a) or StancePost(agent=a, round=rounds_used, stance="need_more", confidence=0.0, claims=[])
                  for a in AGENTS]
        outcome = rules.outcome({p.agent: p.stance for p in finals})
        case_file = build_case_file(case_id, listing, seller, outcome, rounds_used, reason or "max_rounds", finals, st.board)
        self.bus.emit(case_id, "case.ended", {"case_file": case_file.model_dump(mode="json")})
        return case_file


async def _main(listing_id: str) -> None:
    from deadlang.agntcy.discovery import get_discovery
    from deadlang.agntcy.transport import get_transport
    from deadlang.api.events import EventBus
    from deadlang.marketplace.client import get_marketplace_client

    discovery = get_discovery()
    await discovery.register_all()
    cid = f"C-CLI-{int(datetime.now().timestamp())}"  # unique: per-case token caps persist in .usage.json
    bus = EventBus()
    fac = Facilitator(get_marketplace_client(), get_transport(), discovery, bus)

    async def printer() -> None:
        async for e in bus.subscribe(cid):
            print(f"[{e.seq:02d}] {e.type}: {json.dumps(e.payload, default=str)[:160]}")

    task = asyncio.create_task(printer())
    case_file = await fac.run_case(cid, listing_id)
    await task
    print("\nOUTCOME:", case_file.outcome, "| stop:", case_file.stop_reason)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--listing", required=True)
    asyncio.run(_main(ap.parse_args().listing))
