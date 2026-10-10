"""Call specialists and deliberating agents (contract: plan 01 §4.3).

LocalTransport calls the handlers in-process. AgntcyTransport (plan 03 Task 7, not built yet) will send
the same JSON bodies as A2A messages over SLIM.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Iterator, Protocol

from deadlang import config
from deadlang.agntcy import discovery as _discovery
from deadlang.llm import BudgetExceeded
from deadlang.schemas import AgentName, DeliberationTurn, SpecialistCall, SpecialistReply, StancePost

log = logging.getLogger("deadlang.transport")

# The model-backed specialists make slow calls (the thorough examiner looks twice at up to 3 photos, and either
# look may retry once), so they get a floor under whatever timeout the caller passes.
MIN_SPECIALIST_TIMEOUT = {
    "deadlang-examiner-thorough": 120.0,
    "deadlang-examiner-quick": 60.0,
    "deadlang-translator": 60.0,
}


def timeout_for(specialist_name: str, requested: float) -> float:
    """The larger of the caller's timeout and the specialist's minimum."""
    return max(requested, MIN_SPECIALIST_TIMEOUT.get(specialist_name, 0.0))


class AgentTransport(Protocol):
    async def call_specialist(self, specialist_name: str, call: SpecialistCall,
                              timeout: float = 45.0) -> SpecialistReply: ...
    async def broadcast_turns(self, turns: dict[AgentName, DeliberationTurn],
                              timeout: float = 90.0) -> dict[AgentName, StancePost | str]: ...
    async def call_agent(self, agent: AgentName, turn: DeliberationTurn,
                         timeout: float = 90.0) -> StancePost | str: ...


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if type(exc).__name__ == "ListingRemoved":
        return "listing_removed"
    return str(exc) or type(exc).__name__


class ExpiringSet:
    """Names with an expiry, set-like for what the API does with `LocalTransport.disabled` (add, in, discard).
    An entry lasts as long as discovery's unhealthy mark (read when the entry is added); adding it again
    restarts the clock."""

    def __init__(self) -> None:
        self._until: dict[str, float] = {}

    def add(self, name: str) -> None:
        self._until[name] = time.monotonic() + _discovery.UNHEALTHY_SECONDS

    def discard(self, name: str) -> None:
        self._until.pop(name, None)

    def clear(self) -> None:
        self._until.clear()

    def _live(self) -> list[str]:
        now = time.monotonic()
        for name in [n for n, t in self._until.items() if t <= now]:
            del self._until[name]
        return list(self._until)

    def __contains__(self, name: object) -> bool:
        return name in self._live()

    def __iter__(self) -> Iterator[str]:
        return iter(self._live())

    def __len__(self) -> int:
        return len(self._live())


class LocalTransport:
    """In-process transport. `disabled` simulates a dead specialist process: calls to it time out at once,
    until the entry expires (same 60 s as discovery's unhealthy mark) or reset() is called."""

    def __init__(self, specialists: dict[str, Any], agents: dict[AgentName, Any], discovery: Any = None):
        self.specialists = specialists
        self.agents = agents
        self.discovery = discovery
        self.disabled = ExpiringSet()

    def reset(self) -> None:
        """Bring every killed specialist back."""
        self.disabled.clear()

    async def call_specialist(self, specialist_name: str, call: SpecialistCall,
                              timeout: float = 45.0) -> SpecialistReply:
        if specialist_name in self.disabled:
            return SpecialistReply(ok=False, error="timeout")
        specialist = self.specialists.get(specialist_name)
        if specialist is None:   # "connect" makes the Facilitator try the fallback specialist
            return SpecialistReply(ok=False, error=f"cannot connect: {specialist_name} is not running")
        start = time.perf_counter()
        try:
            reply = await asyncio.wait_for(specialist.run(call), timeout_for(specialist_name, timeout))
        except BudgetExceeded:
            return SpecialistReply(ok=False, error="budget")
        except Exception as exc:
            log.warning("specialist %s failed: %r", specialist_name, exc)
            return SpecialistReply(ok=False, error=_error_text(exc))
        if self.discovery is not None:
            self.discovery.record_latency(specialist_name, (time.perf_counter() - start) * 1000)
        return reply

    async def call_agent(self, agent: AgentName, turn: DeliberationTurn,
                         timeout: float = 90.0) -> StancePost | str:
        handler = self.agents.get(agent)
        if handler is None:
            return f"no agent named {agent}"
        try:
            return await asyncio.wait_for(handler.handle(turn), timeout)
        except BudgetExceeded:
            raise                  # the Facilitator ends the case with stop_reason "budget"
        except Exception as exc:
            log.warning("agent %s failed: %r", agent, exc)
            return _error_text(exc)

    async def broadcast_turns(self, turns: dict[AgentName, DeliberationTurn],
                              timeout: float = 90.0) -> dict[AgentName, StancePost | str]:
        """Calls only the agents present in `turns` (0-3 from round 2), all at the same time."""
        if not turns:
            return {}
        names = list(turns)
        results = await asyncio.gather(*(self.call_agent(a, turns[a], timeout) for a in names),
                                       return_exceptions=True)
        for r in results:
            if isinstance(r, BudgetExceeded):
                raise r
        return {a: (r if not isinstance(r, BaseException) else _error_text(r)) for a, r in zip(names, results)}


_transport: AgentTransport | None = None


def get_transport() -> AgentTransport:
    """AgntcyTransport if TRANSPORT=agntcy, else LocalTransport (one per process)."""
    global _transport
    if _transport is None:
        if config.TRANSPORT == "agntcy":
            log.warning("TRANSPORT=agntcy is not built yet (plan 03 Task 7); using local transport")
        _transport = _build_local()
    return _transport


def _build_local() -> LocalTransport:
    from deadlang.agntcy.discovery import get_discovery
    from deadlang.deliberation.agents import DeliberatingAgent
    from deadlang.specialists.registry import build_specialists

    try:
        from deadlang.marketplace.client import get_marketplace_client
        market = get_marketplace_client()
    except ImportError:
        log.warning("marketplace client is not available yet; specialists get no market")
        market = None
    specialists = {s.name: s for s in build_specialists(market)}
    agents = {a: DeliberatingAgent(a) for a in ("buyer", "defender", "caseload")}
    return LocalTransport(specialists, agents, discovery=get_discovery())
