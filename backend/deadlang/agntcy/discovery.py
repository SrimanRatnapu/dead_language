"""Pick a specialist by capability (contract: plan 01 §4.3).

LocalDiscovery reads AgentCards held in memory. AgntcyDirectoryDiscovery (plan 03 Task 7, not built yet)
will read the same cards from the AGNTCY Directory and reuse `choose`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from a2a.types import AgentCard

from deadlang import config
from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for, card_tags
from deadlang.schemas import Capability

log = logging.getLogger("deadlang.discovery")

UNHEALTHY_SECONDS = 60.0


@dataclass
class Selection:
    specialist_name: str
    why: str                       # plain sentence shown in the UI
    candidates: list[str]


class Discovery(Protocol):
    async def register_all(self) -> None: ...
    async def select(self, capability: Capability, exclude: set[str] = frozenset()) -> Selection | None: ...
    async def mark_unhealthy(self, specialist_name: str) -> None: ...
    def record_latency(self, specialist_name: str, ms: float) -> None: ...


class Health:
    """Unhealthy marks (expire after 60 s) and average latency per agent."""

    def __init__(self) -> None:
        self._unhealthy_until: dict[str, float] = {}
        self._latency: dict[str, tuple[float, int]] = {}   # name -> (total ms, count)

    def mark_unhealthy(self, name: str) -> None:
        self._unhealthy_until[name] = time.monotonic() + UNHEALTHY_SECONDS

    def is_healthy(self, name: str) -> bool:
        until = self._unhealthy_until.get(name)
        if until is None:
            return True
        if time.monotonic() >= until:
            del self._unhealthy_until[name]
            return True
        return False

    def record_latency(self, name: str, ms: float) -> None:
        total, n = self._latency.get(name, (0.0, 0))
        self._latency[name] = (total + ms, n + 1)

    def avg_latency(self, name: str) -> float:
        total, n = self._latency.get(name, (0.0, 0))
        return total / n if n else 0.0


def choose(cards: list[AgentCard], capability: str, exclude: set[str] | frozenset[str],
           health: Health) -> Selection | None:
    """Preferred tier first, then lowest average latency. Shared by local and Directory discovery."""
    offering = [(c.name, card_tags(c).get("tier", "preferred")) for c in cards
                if card_tags(c).get("capability") == capability]
    candidates = [(n, t) for n, t in offering if n not in exclude and health.is_healthy(n)]
    if not candidates:
        return None
    candidates.sort(key=lambda nt: (nt[1] != "preferred", health.avg_latency(nt[0])))
    name, tier = candidates[0]
    names = [n for n, _ in candidates]
    skipped_preferred = [n for n, t in offering if t == "preferred" and n not in names]
    if tier != "preferred" and skipped_preferred:
        why = (f"{skipped_preferred[0]} did not respond, so chose {name}, "
               f"which offers {capability} at a lower quality tier.")
    elif len(candidates) == 1:
        why = f"{name} is the only registered agent offering {capability}."
    else:
        why = f"Chose {name}: it offers {capability} at the preferred quality tier and is responding."
    return Selection(specialist_name=name, why=why, candidates=names)


class LocalDiscovery:
    def __init__(self, cards: list[AgentCard]):
        self.cards = cards
        self.health = Health()

    async def register_all(self) -> None:
        """Nothing to register in local mode; the cards are already in memory."""

    async def select(self, capability: Capability, exclude: set[str] = frozenset()) -> Selection | None:
        return choose(self.cards, capability, exclude, self.health)

    async def mark_unhealthy(self, specialist_name: str) -> None:
        self.health.mark_unhealthy(specialist_name)

    def record_latency(self, specialist_name: str, ms: float) -> None:
        self.health.record_latency(specialist_name, ms)


_discovery: Discovery | None = None


def get_discovery() -> Discovery:
    """AgntcyDirectoryDiscovery if DISCOVERY=agntcy, else LocalDiscovery (one per process)."""
    global _discovery
    if _discovery is None:
        if config.DISCOVERY == "agntcy":
            log.warning("DISCOVERY=agntcy is not built yet (plan 03 Task 7); using local discovery")
        _discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    return _discovery
