"""Call specialists and deliberating agents (contract: plan 01 §4.3).

LocalTransport calls the handlers in-process. AgntcyTransport sends the same JSON bodies as A2A
`message/send` requests over SLIM to the servers started by serve.py.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any, Iterator, Protocol
from uuid import uuid4

from pydantic import ValidationError

from deadlang import config
from deadlang.agntcy import discovery as _discovery
from deadlang.llm import BudgetExceeded
from deadlang.agntcy.wire import WireError, reply_text, request_message, slim_name
from deadlang.schemas import AgentName, DeliberationTurn, SpecialistCall, SpecialistReply, StancePost

log = logging.getLogger("deadlang.transport")

# The model-backed specialists make slow calls (the thorough examiner looks twice at up to 3 photos, and either
# look may retry once), so they get a floor under whatever timeout the caller passes.
MIN_SPECIALIST_TIMEOUT = {
    "deadlang-examiner-thorough": 120.0,
    "deadlang-examiner-quick": 60.0,
    "deadlang-translator": 60.0,
}


LINK_TIMEOUT = 10.0     # seconds to connect to SLIM before calls report "cannot connect"


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


def error_text(exc: BaseException) -> str:
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
            return SpecialistReply(ok=False, error=error_text(exc))
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
            return error_text(exc)

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
        return {a: (r if not isinstance(r, BaseException) else error_text(r)) for a, r in zip(names, results)}


class AgntcyTransport:
    """Calls agents over SLIM: point-to-point for specialists and repairs, one broadcast per round.

    It talks to the SDK's SLIMTransport directly, with the same A2A JSON-RPC envelope as the SDK's A2A client
    (wire.py), for two reasons found in agntcy-app-sdk 0.5.5: the client's point-to-point send_message calls
    SLIMTransport.request() without a timeout, so every call is cut off at its 6-second default (our agents
    take longer), and broadcast_message() raises on a timeout and drops the replies it already has. Here every
    call carries our timeout, and a broadcast keeps whatever arrived.

    `broadcast=False` sends a round as one point-to-point call per agent instead (the plan's fallback if
    broadcast misbehaves; DL_AGNTCY_BROADCAST=0). `disabled` / `reset()` work as in LocalTransport, so the
    API's kill switch works in both modes.
    """

    GRACE = 5.0       # extra seconds on our own guard, beyond the timeout handed to SLIM

    def __init__(self, discovery: Any = None, slim: Any = None, factory: Any = None, broadcast: bool = True):
        self.discovery = discovery
        self.broadcast = broadcast
        self.disabled = ExpiringSet()
        self._slim = slim
        self._factory = factory
        self._setup_lock: asyncio.Lock | None = None

    def reset(self) -> None:
        self.disabled.clear()

    async def _link(self) -> Any:
        """The facilitator's own SLIM identity, connected once."""
        if self._slim is not None:
            return self._slim
        if self._setup_lock is None:
            self._setup_lock = asyncio.Lock()
        async with self._setup_lock:
            if self._slim is None:
                from agntcy_app_sdk import AgntcyFactory
                factory = self._factory or AgntcyFactory("deadlang-facilitator")
                # one identity per process, so the API and a CLI run can both be connected at once
                slim = factory.create_transport("SLIM", endpoint=config.SLIM_ENDPOINT,
                                                name=slim_name(f"deadlang-facilitator-{os.getpid()}"),
                                                shared_secret_identity=config.SLIM_SHARED_SECRET)
                try:                          # the SLIM bindings retry a refused connection forever
                    await asyncio.wait_for(slim.setup(), LINK_TIMEOUT)
                except asyncio.TimeoutError:
                    raise ConnectionError(f"SLIM at {config.SLIM_ENDPOINT} did not answer within "
                                          f"{LINK_TIMEOUT:.0f} s") from None
                self._slim = slim
        return self._slim

    async def _request(self, server_name: str, text: str, timeout: float) -> str:
        """One request/reply. Raises asyncio.TimeoutError, WireError, or the link's own error."""
        slim = await self._link()
        message = await asyncio.wait_for(
            slim.request(slim_name(server_name), request_message(text), timeout=timeout), timeout + self.GRACE)
        if message is None:                       # SLIMTransport.request returns None on a timeout or failed publish
            raise asyncio.TimeoutError()
        return reply_text(message)

    # ---------------------------------------------------------------- specialists

    async def call_specialist(self, specialist_name: str, call: SpecialistCall,
                              timeout: float = 45.0) -> SpecialistReply:
        if specialist_name in self.disabled:
            return SpecialistReply(ok=False, error="timeout")
        start = time.perf_counter()
        try:
            text = await self._request(specialist_name, call.model_dump_json(), timeout_for(specialist_name, timeout))
            reply = SpecialistReply.model_validate_json(text)
        except asyncio.TimeoutError:
            return SpecialistReply(ok=False, error="timeout")
        except (WireError, ValidationError, ValueError) as exc:
            return SpecialistReply(ok=False, error=f"bad reply from {specialist_name}: {exc}")
        except Exception as exc:                  # SLIM unreachable etc.; "connect" makes the Facilitator fall back
            log.warning("SLIM call to %s failed: %r", specialist_name, exc)
            return SpecialistReply(ok=False, error=f"cannot connect to {specialist_name}: {exc}")
        if self.discovery is not None:
            self.discovery.record_latency(specialist_name, (time.perf_counter() - start) * 1000)
        return reply

    # ---------------------------------------------------------------- deliberators

    @staticmethod
    def _post_or_error(text: str) -> tuple[str | None, StancePost | str, bool]:
        """(agent, post or error string, budget hit) from a deliberator's reply text."""
        data = json.loads(text)
        if isinstance(data, dict) and "error" in data:
            return data.get("agent"), str(data["error"]), bool(data.get("budget"))
        post = StancePost.model_validate(data)
        return post.agent, post, False

    async def call_agent(self, agent: AgentName, turn: DeliberationTurn,
                         timeout: float = 90.0) -> StancePost | str:
        from deadlang.agntcy.cards import DELIBERATOR_NAMES
        try:
            text = await self._request(DELIBERATOR_NAMES[agent], turn.model_dump_json(), timeout)
            who, value, budget = self._post_or_error(text)
        except asyncio.TimeoutError:
            return "timeout"
        except (WireError, ValidationError, ValueError) as exc:
            return f"bad reply from {agent}: {exc}"
        except Exception as exc:
            log.warning("SLIM call to %s failed: %r", agent, exc)
            return f"cannot connect to {agent}: {exc}"
        if budget:
            raise BudgetExceeded(str(value))      # the Facilitator ends the case with stop_reason "budget"
        if isinstance(value, StancePost) and who != agent:
            return f"reply came from {who}, not {agent}"
        return value

    async def broadcast_turns(self, turns: dict[AgentName, DeliberationTurn],
                              timeout: float = 90.0) -> dict[AgentName, StancePost | str]:
        """One message to the agents named in `turns` only (0-3 from round 2); each takes its own entry."""
        if not turns:
            return {}
        if not self.broadcast:
            names = list(turns)
            results = await asyncio.gather(*(self.call_agent(a, turns[a], timeout) for a in names),
                                           return_exceptions=True)
            for r in results:
                if isinstance(r, BudgetExceeded):
                    raise r
            return {a: (r if not isinstance(r, BaseException) else error_text(r)) for a, r in zip(names, results)}

        from deadlang.agntcy.cards import DELIBERATOR_NAMES
        payload = json.dumps({"kind": "turns",
                              "turns": {a: json.loads(t.model_dump_json()) for a, t in turns.items()}})
        recipients = [slim_name(DELIBERATOR_NAMES[a]) for a in turns]
        channel = slim_name(f"deadlang-round-{uuid4().hex[:12]}")      # one group channel per broadcast
        results: dict[str, StancePost | str] = {}
        budget_hit: str | None = None
        try:
            slim = await self._link()
            async with asyncio.timeout(timeout + self.GRACE):
                stream = slim.gather_stream(channel, request_message(payload), recipients=recipients,
                                            message_limit=len(recipients), timeout=timeout)
                async with contextlib.aclosing(stream):
                    async for message in stream:
                        try:
                            who, value, budget = self._post_or_error(reply_text(message))
                        except (WireError, ValidationError, ValueError) as exc:
                            log.warning("unreadable broadcast reply: %s", exc)
                            continue
                        if who not in turns or who in results:
                            continue
                        results[who] = value
                        if budget:
                            budget_hit = str(value)
                        if len(results) == len(turns):
                            break
        except (TimeoutError, asyncio.TimeoutError):
            pass                                  # keep what arrived; the rest are "timeout" below
        except Exception as exc:
            log.warning("SLIM broadcast failed: %r", exc)
            for a in turns:
                results.setdefault(a, f"cannot connect to {a}: {exc}")
        if budget_hit is not None:
            raise BudgetExceeded(budget_hit)
        return {a: results.get(a, "timeout") for a in turns}


_transport: AgentTransport | None = None


def get_transport() -> AgentTransport:
    """AgntcyTransport if TRANSPORT=agntcy, else LocalTransport (one per process)."""
    global _transport
    if _transport is None:
        if config.TRANSPORT == "agntcy":
            from deadlang.agntcy.discovery import get_discovery
            _transport = AgntcyTransport(discovery=get_discovery(), broadcast=config.AGNTCY_BROADCAST)
        else:
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
