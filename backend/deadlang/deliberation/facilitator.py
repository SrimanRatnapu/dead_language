"""Facilitator: referee of process. Runs intake, wakes agents, validates claims, applies published rules.

It never decides an outcome; `rules.outcome` does, and the discussion ends when nobody has anything left to say.
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
from deadlang.specialists.language import english_note
from deadlang.llm import BudgetExceeded
from deadlang.schemas import (AgentName, Capability, CaseFile, DeliberationTurn, EvidenceDraft, Listing,
                              PeerQuestion, Requester, Seller, SpecialistCall, StancePost)

AGENTS: tuple[AgentName, ...] = ("undercover", "counsel", "case_officer")
MAX_CALLS_PER_CASE = 6


@dataclass
class CaseState:
    case_id: str
    listing: Listing
    seller: Seller
    board: EvidenceBoard
    current: dict[AgentName, StancePost] = field(default_factory=dict)   # each agent's latest validated post
    transcript: list[StancePost] = field(default_factory=list)           # every validated post, in order
    seen: dict[AgentName, int] = field(default_factory=dict)             # board size at each agent's last turn
    seen_posts: dict[AgentName, int] = field(default_factory=dict)       # transcript length at each agent's last turn
    turns: dict[AgentName, int] = field(default_factory=dict)            # turns each agent has taken (a post's `round`)
    jobs: set[asyncio.Task] = field(default_factory=set)                 # specialist calls in flight
    request_keys: set[tuple[str, str]] = field(default_factory=set)      # (capability, params) already requested
    requested_calls: int = 0
    removal_noted: bool = False
    relist_noted: bool = False
    attempted: set[str] = field(default_factory=set)                     # capabilities already run, or tried and failed
    answered: set[tuple[str, str]] = field(default_factory=set)         # (asker, question) already delivered

    @property
    def listing_text(self) -> str:
        return f"{self.listing.title}\n{self.listing.description}"


class Facilitator:
    def __init__(self, market: Any, transport: Any, discovery: Any, bus: Any, max_rounds: int = 4):
        self.market, self.transport, self.discovery, self.bus = market, transport, discovery, bus
        self.max_rounds = max_rounds
        # An evaluation turns this on to learn how often the validator rejected claims *before* the repair call
        # (the events only carry what was still rejected after it). Off by default so a long-running server keeps nothing.
        self.claim_stats: dict[str, dict[str, dict[str, int]]] | None = None
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
        st.attempted.add(capability)
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

    # ------------------------------------------------------------------ the discussion
    # No rounds. An agent runs as soon as it has a reason to: it has not spoken yet, there is evidence it has not seen,
    # someone asked it a question, or someone rebutted it and it is not ready to close. Agents run at the same time,
    # post the moment they finish, and a post's specialist requests start at once. The discussion ends when nobody is
    # working and nobody has a reason to run; max_rounds caps how many turns one agent may take.
    def _pending_questions(self, st: CaseState, a: AgentName) -> list[PeerQuestion]:
        return [PeerQuestion(asker=p.agent, question=p.challenge.question) for p in st.transcript
                if p.challenge and p.challenge.target_agent == a and (p.agent, p.challenge.question) not in st.answered]

    def _wants_turn(self, st: CaseState, a: AgentName) -> bool:
        post = st.current.get(a)
        if post is None:
            return True
        if st.board.count() > st.seen.get(a, 0) or self._pending_questions(st, a):
            return True
        rebutted = any(p.agent != a and p.rebuttal and p.rebuttal.target_agent == a
                       for p in st.transcript[st.seen_posts.get(a, 0):])
        return rebutted and (post.abstained or not self._ready(st, a, post))   # a rebuttal alone does not call a ready agent

    def _tools_left(self, st: CaseState) -> int:
        """Specialist checks that could still be run for this case (never tried, and the request budget is not spent)."""
        wanted = {"price_check", "seller_inventory", "linked_sellers", "legal_lookup", "material_exam"}
        if st.listing.language != "en":
            wanted.add("translation")
        return 0 if st.requested_calls >= MAX_CALLS_PER_CASE else len(wanted - st.attempted)

    def _ready(self, st: CaseState, a: AgentName, post: StancePost) -> bool:
        unseen = max(st.board.count() - st.seen.get(a, 0), 0)
        return rules.is_ready(post, unseen_evidence=unseen, tools_left=self._tools_left(st),
                              questions_pending=bool(self._pending_questions(st, a)))

    def _turn(self, st: CaseState, a: AgentName, r: int) -> DeliberationTurn:
        questions = self._pending_questions(st, a)             # answered once, never re-delivered
        st.answered.update((q.asker, q.question) for q in questions)
        return DeliberationTurn(case_id=st.case_id, round=r, max_rounds=self.max_rounds,
                                evidence=st.board.all(), transcript=list(st.transcript),
                                your_previous=None if (prev := st.current.get(a)) and prev.abstained else prev,
                                questions_for_you=questions)

    @staticmethod
    def _fallback_post(st: CaseState, a: AgentName, r: int) -> StancePost:
        prev = st.current.get(a)
        if prev is None:
            return StancePost(agent=a, round=r, stance="need_more", confidence=0.0, claims=[])
        return prev.model_copy(update={"round": r, "rebuttal": None, "requests": [], "challenge": None,
                                       "changed_because": None, "changed_because_evidence": []})

    async def _agent_turn(self, st: CaseState, a: AgentName) -> str | None:
        """One turn for one agent: read the board and the thread as they are now, post, start its specialist requests.
        Returns the transport error if the agent did not answer."""
        st.turns[a] = r = st.turns.get(a, 0) + 1
        st.seen[a], st.seen_posts[a] = st.board.count(), len(st.transcript)
        self.bus.emit(st.case_id, "agent.thinking", {"agent": a, "turn": r})
        turn = self._turn(st, a, r)
        result = (await self.transport.broadcast_turns({a: turn})).get(a, "no reply")
        post, rejections = await self._resolve(st, a, turn, result, list(st.current.values()), r)
        for rj in rejections:
            self.bus.emit(st.case_id, "claim.rejected", {
                "agent": rj.agent, "round": rj.round, "claim_text": rj.claim_text, "reasons": rj.reasons})
        self.bus.emit(st.case_id, "stance.posted", {"post": post.model_dump(mode="json")})
        st.transcript.append(post)
        st.current[a] = post
        self._dispatch_requests(st, post)
        return None if isinstance(result, StancePost) else str(result)

    def _dispatch_requests(self, st: CaseState, post: StancePost) -> None:
        """Start the specialist calls an agent asked for, now. The evidence they return wakes whoever has not seen it."""
        for req in post.requests:
            key = (req.capability, json.dumps(req.params, sort_keys=True))
            if key in st.request_keys:
                continue
            if req.capability == "translation" and st.listing.language == "en":
                # Nothing to translate: the note goes on the board once, with no specialist call and no slot used.
                st.request_keys.add(key)
                if "translation" not in st.attempted:
                    st.attempted.add("translation")
                    self._add(st, english_note(st.listing.id), post.agent)
                continue
            if st.requested_calls >= MAX_CALLS_PER_CASE:       # a post holds at most 2 requests (validator)
                self.bus.emit(st.case_id, "specialist.failed", {
                    "capability": req.capability, "specialist_name": "", "requested_by": post.agent,
                    "error": f"request limit reached ({MAX_CALLS_PER_CASE} per case)", "fallback": None})
                continue
            st.request_keys.add(key)
            st.requested_calls += 1
            job = asyncio.create_task(self._run_specialist(st, req.capability, req.params, post.agent, req.question))
            st.jobs.add(job)
            job.add_done_callback(st.jobs.discard)

    async def _discuss(self, st: CaseState) -> str:
        """Run the agents until nothing is left to say. Returns the stop reason."""
        running: dict[asyncio.Task, AgentName] = {}
        first_errors: dict[AgentName, str] = {}
        capped = False
        try:
            while True:
                if not running and not st.jobs and len(st.current) == len(AGENTS) and rules.is_unanimous(
                        {a: p.stance for a, p in st.current.items() if not p.abstained}, sum(not p.abstained for p in st.current.values())):
                    return "unanimous"
                if len(first_errors) == len(AGENTS):
                    # Nobody answered at all (bad API key, outage): an error, not an outcome. Empty "need more" posts
                    # would otherwise close as WATCHLIST and look like a real review.
                    raise RuntimeError(f"no agent answered: {next(iter(first_errors.values()))[:300]}")
                for a in AGENTS:
                    if a in running.values() or not self._wants_turn(st, a):
                        continue
                    if st.turns.get(a, 0) >= self.max_rounds:
                        capped = True                          # backstop: this agent has spoken as often as it may
                        continue
                    running[asyncio.create_task(self._agent_turn(st, a))] = a
                if not running and not st.jobs:
                    break
                done, _ = await asyncio.wait({*running, *st.jobs}, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task in running:
                        a = running.pop(task)
                        err = task.result()
                        if err and st.turns[a] == 1:
                            first_errors[a] = err
                    elif task.exception():
                        raise task.exception()                 # a specialist call that blew up (not a failed reply)
        finally:
            for t in [*running, *st.jobs]:
                t.cancel()
        return "max_rounds" if capped else "ready_to_close"

    async def _resolve(self, st: CaseState, a: AgentName, turn: DeliberationTurn, result: Any,
                       latest: list[StancePost], r: int) -> tuple[StancePost, list[Rejection]]:
        if not isinstance(result, StancePost):                      # error string: carry the previous stance over
            return self._fallback_post(st, a, r), []
        prev = st.current.get(a)
        cleaned, rejections, problems = validate_post(result, st.board, st.listing_text, prev, r, latest)
        stats = None
        if self.claim_stats is not None:
            stats = self.claim_stats.setdefault(st.case_id, {}).setdefault(
                a, {"claims": 0, "rejected_first": 0, "repairs": 0, "rejected_final": 0})
            stats["claims"] += len(result.claims)
            stats["rejected_first"] += len(rejections)
            stats["rejected_final"] += len(rejections)
        if rejections or problems:
            feedback = problems + [f'Your claim "{rj.claim_text}" was removed: {"; ".join(rj.reasons)}'
                                   for rj in rejections]
            second = await self.transport.call_agent(a, turn.model_copy(update={"repair_feedback": feedback}))
            if stats is not None:
                stats["repairs"] += 1
            if isinstance(second, StancePost):
                first_pass = len(rejections)
                cleaned, rejections, _ = validate_post(second, st.board, st.listing_text, prev, r, latest)
                if stats is not None:
                    stats["rejected_final"] += len(rejections) - first_pass         # what is still rejected after the repair
        cleaned, _ = apply_empty_claims_rule(cleaned)
        return cleaned, rejections

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
        try:
            if intake is None:
                await self._intake(st)
            else:                                           # replay precomputed intake evidence in order
                st.attempted |= intake.attempted
                for ev in intake.board.all():
                    self._add(st, EvidenceDraft.model_validate(ev.model_dump(include=set(EvidenceDraft.model_fields))),
                              ev.requested_by)

            reason = await self._discuss(st)
        except BudgetExceeded as exc:
            self.bus.emit(case_id, "budget.exceeded", {"detail": str(exc)})
            reason = "budget"

        rounds_used = max(st.turns.values(), default=0)
        finals = [st.current.get(a) or StancePost(agent=a, round=rounds_used, stance="need_more", confidence=0.0, claims=[])
                  for a in AGENTS]
        outcome = rules.outcome({p.agent: p.stance for p in finals if not p.abstained})   # whoever sat out does not count
        if (reason or "max_rounds") == "max_rounds" and outcome in ("FILE", "DISMISS"):
            outcome = "WATCHLIST"   # out of rounds without agreement is never a clean FILE/DISMISS
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
