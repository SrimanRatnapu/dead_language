"""Pick a specialist by capability (contract: plan 01 §4.3).

LocalDiscovery reads AgentCards held in memory. AgntcyDirectoryDiscovery reads the cards that running agents
pushed to the AGNTCY Directory and picks with the same `choose`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from a2a.types import AgentCard

from deadlang import config
from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for, card_tags, names_for_capability
from deadlang.schemas import Capability

log = logging.getLogger("deadlang.discovery")

UNHEALTHY_SECONDS = 60.0
DIRECTORY_TIMEOUT = 5.0           # seconds for one Directory call before falling back to local cards
DIRECTORY_RETRY_AFTER = 30.0      # after a Directory failure, use local cards for this long before retrying
DIRECTORY_NOTE = " Found via the AGNTCY Directory."


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


class AgntcyDirectoryDiscovery:
    """Selection from the cards in the AGNTCY Directory.

    The Directory's skill search does not see our skills (the SDK stores the whole AgentCard in the record but
    sets the OASF skill to a placeholder), so for a capability it searches by the name of each agent that
    should offer it (cards.names_for_capability), keeps exact name matches whose skill tags carry the
    capability, and picks with the same rules and sentences as LocalDiscovery, plus DIRECTORY_NOTE. Only agents
    whose serve process registered them are found. If the Directory errors or is slow, that call uses
    LocalDiscovery (same health record, no note), and the Directory is left alone for DIRECTORY_RETRY_AFTER.
    """

    def __init__(self, directory: Any = None):
        self.health = Health()
        self.local = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
        self.local.health = self.health
        self.cids: dict[str, str] = {}
        self._directory = directory
        self._ready = False
        self._failed_at: float | None = None

    async def _dir(self) -> Any:
        if self._failed_at is not None and time.monotonic() - self._failed_at < DIRECTORY_RETRY_AFTER:
            raise _SkippingDirectory()
        if self._directory is None:
            from agntcy_app_sdk import AgentDirectory
            self._directory = AgentDirectory.from_config(endpoint=config.DIRECTORY_ADDRESS)
        if not self._ready:
            await asyncio.wait_for(self._directory.setup(), DIRECTORY_TIMEOUT)
            self._ready = True
        self._failed_at = None
        return self._directory

    def _failed(self, exc: BaseException) -> None:
        if isinstance(exc, _SkippingDirectory):
            return                                   # still inside the window from the last real failure
        self._failed_at = time.monotonic()
        log.warning("AGNTCY Directory at %s unavailable (%r); using local cards for %.0f s",
                    config.DIRECTORY_ADDRESS, exc, DIRECTORY_RETRY_AFTER)

    async def register(self, names: list[str]) -> None:
        """Push these agents' cards (serve.py calls this for the agents it runs). Raises if the Directory fails."""
        directory = await self._dir()
        for name in names:
            try:
                self.cids[name] = await asyncio.wait_for(directory.push_agent_record(card_for(name)),
                                                         DIRECTORY_TIMEOUT)
            except Exception as exc:
                if "already exists" in str(exc).lower():
                    continue
                raise

    async def register_all(self) -> None:
        """Called by the API at startup. Agents are registered by the serve processes that run them, so the
        Directory lists only what is up; here we only connect, and a Directory problem never stops startup."""
        try:
            await self._dir()
        except Exception as exc:
            self._failed(exc)

    async def select(self, capability: Capability, exclude: set[str] = frozenset()) -> Selection | None:
        names = names_for_capability(capability)
        try:
            directory = await self._dir()
            found = await asyncio.wait_for(
                asyncio.gather(*(directory.search_agent_records(n, limit=10) for n in names)), DIRECTORY_TIMEOUT)
        except Exception as exc:
            self._failed(exc)
            return await self.local.select(capability, exclude)
        cards: list[AgentCard] = []
        for name, records in zip(names, found):
            for record in records:
                card = _card_from_record(record)
                if card is not None and card.name == name:      # name search can match other names too
                    cards.append(card)
                    break                                       # a name pushed twice is still one agent
        selection = choose(cards, capability, exclude, self.health)
        if selection is not None:
            selection.why += DIRECTORY_NOTE
        return selection

    async def mark_unhealthy(self, specialist_name: str) -> None:
        self.health.mark_unhealthy(specialist_name)

    def record_latency(self, specialist_name: str, ms: float) -> None:
        self.health.record_latency(specialist_name, ms)


class _SkippingDirectory(Exception):
    """The Directory failed less than DIRECTORY_RETRY_AFTER ago; use local cards without waiting on it."""


def _card_from_record(record: dict) -> AgentCard | None:
    from agntcy_app_sdk.directory.oasf_converter import oasf_to_agent_card
    try:
        return oasf_to_agent_card(record)
    except Exception:
        return None


_discovery: Discovery | None = None


def get_discovery() -> Discovery:
    """AgntcyDirectoryDiscovery if DISCOVERY=agntcy, else LocalDiscovery (one per process)."""
    global _discovery
    if _discovery is None:
        if config.DISCOVERY == "agntcy":
            _discovery = AgntcyDirectoryDiscovery()
        else:
            _discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    return _discovery
