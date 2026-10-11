"""AGNTCY end to end: real SLIM and the real AGNTCY Directory, fake agents (no model calls, no spend).

Needs `docker compose -f infra/docker-compose.yaml up -d` (SLIM on 46357, Directory on 8888); skipped otherwise.
Run:  cd backend && uv run pytest -m integration tests/test_agntcy_e2e.py -v
Stop any `serve` processes first: these tests serve the same agent names themselves.
"""
import asyncio
import socket
from urllib.parse import urlparse

import pytest

from deadlang import config
from deadlang.agntcy import serve
from deadlang.agntcy import transport as tr
from deadlang.agntcy.discovery import AgntcyDirectoryDiscovery
from deadlang.agntcy.transport import AgntcyTransport
from deadlang.schemas import DeliberationTurn, EvidenceDraft, SpecialistCall, SpecialistReply, StancePost


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


_slim = urlparse(config.SLIM_ENDPOINT)
_dir_host, _, _dir_port = config.DIRECTORY_ADDRESS.rpartition(":")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (_reachable(_slim.hostname or "localhost", _slim.port or 46357)
                            and _reachable(_dir_host or "127.0.0.1", int(_dir_port or 8888))),
                       reason="needs SLIM and the AGNTCY Directory: docker compose -f infra/docker-compose.yaml up -d"),
]

CALL = SpecialistCall(case_id="C-E2E", listing_id="L0101", capability="material_exam")


class StubSpecialist:
    capability, tier = "material_exam", "preferred"

    def __init__(self, name):
        self.name = name

    async def run(self, call):
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="material_exam", summary=f"{self.name} examined {call.listing_id}", data={"n": 1},
            produced_by="model", confidence=0.5, specialist_name=self.name)])


class StubAgent:
    def __init__(self, name):
        self.name = name
        self.turns = []

    async def handle(self, turn):
        self.turns.append(turn)
        return StancePost(agent=self.name, round=turn.round, stance="need_more", confidence=0.4, claims=[])


def turn(r=1):
    return DeliberationTurn(case_id="C-E2E", round=r, max_rounds=4, evidence=[], transcript=[])


async def test_point_to_point_call_to_a_specialist():
    session = await serve.start({"deadlang-examiner-quick": serve.specialist_handler(StubSpecialist("deadlang-examiner-quick"))})
    try:
        await asyncio.sleep(1)
        reply = await AgntcyTransport().call_specialist("deadlang-examiner-quick", CALL, timeout=20)
        assert reply.ok, reply.error
        assert reply.drafts[0].summary == "deadlang-examiner-quick examined L0101"
    finally:
        await session.stop_all_sessions()


async def test_broadcast_reaches_only_the_named_agents():
    agents = {a: StubAgent(a) for a in ("undercover", "counsel", "case_officer")}
    session = await serve.start({f"deadlang-{a}": serve.deliberator_handler(a, agent) for a, agent in agents.items()})
    try:
        await asyncio.sleep(1)
        t = AgntcyTransport()
        results = await t.broadcast_turns({"undercover": turn(2), "case_officer": turn(2)}, timeout=30)
        assert set(results) == {"undercover", "case_officer"}
        assert all(isinstance(p, StancePost) and p.agent == a for a, p in results.items()), results
        assert agents["counsel"].turns == []
        three = await t.broadcast_turns({a: turn(3) for a in agents}, timeout=30)
        assert all(isinstance(p, StancePost) for p in three.values()), three
        repair = await t.call_agent("counsel", turn(3), timeout=20)
        assert isinstance(repair, StancePost) and repair.agent == "counsel"
    finally:
        await session.stop_all_sessions()


async def test_directory_register_then_select():
    dd = AgntcyDirectoryDiscovery()
    await dd.register(["deadlang-examiner-thorough", "deadlang-examiner-quick"])
    sel = await dd.select("material_exam")
    assert sel is not None and sel.specialist_name == "deadlang-examiner-thorough"
    assert sel.why.endswith("Found via the AGNTCY Directory.")


async def test_kill_the_thorough_examiner_and_fall_back_to_quick(monkeypatch):
    monkeypatch.setitem(tr.MIN_SPECIALIST_TIMEOUT, "deadlang-examiner-thorough", 0.0)   # do not wait 120 s here
    handlers = {name: serve.specialist_handler(StubSpecialist(name))
                for name in ("deadlang-examiner-thorough", "deadlang-examiner-quick")}
    session = await serve.start(handlers)
    dd = AgntcyDirectoryDiscovery()
    await dd.register(list(handlers))
    t = AgntcyTransport(discovery=dd)
    try:
        await asyncio.sleep(1)
        assert (await t.call_specialist("deadlang-examiner-thorough", CALL, timeout=20)).ok

        await session.stop_session("deadlang-examiner-thorough")          # the kill
        await asyncio.sleep(1)
        dead = await t.call_specialist("deadlang-examiner-thorough", CALL, timeout=5)
        assert not dead.ok and (dead.error == "timeout" or "connect" in dead.error), dead.error

        await dd.mark_unhealthy("deadlang-examiner-thorough")             # what the Facilitator does next
        sel = await dd.select("material_exam")
        assert sel.specialist_name == "deadlang-examiner-quick"
        assert sel.why.startswith("deadlang-examiner-thorough did not respond, so chose deadlang-examiner-quick")
        assert (await t.call_specialist("deadlang-examiner-quick", CALL, timeout=20)).ok
    finally:
        await session.stop_all_sessions()
