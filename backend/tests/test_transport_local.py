import asyncio

import pytest

from deadlang.agntcy.transport import LocalTransport
from deadlang.llm import BudgetExceeded
from deadlang.schemas import DeliberationTurn, EvidenceDraft, SpecialistCall, SpecialistReply, StancePost
from deadlang.specialists import registry

CALL = SpecialistCall(case_id="C-1", listing_id="L0101", capability="price_check")


class FakeSpecialist:
    capability = "price_check"
    tier = "preferred"

    def __init__(self, name="deadlang-price-checker", behavior="ok"):
        self.name = name
        self.behavior = behavior

    async def run(self, call):
        if self.behavior == "slow":
            await asyncio.sleep(5)
        if self.behavior == "raise":
            raise RuntimeError("price table missing")
        if self.behavior == "budget":
            raise BudgetExceeded("cap")
        if self.behavior == "removed":
            raise type("ListingRemoved", (Exception,), {})("L0101")
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="price_check", summary="ok", data={}, produced_by="code", specialist_name=self.name)])


class FakeAgent:
    def __init__(self, name, behavior="ok"):
        self.name = name
        self.behavior = behavior
        self.turns = []

    async def handle(self, turn):
        self.turns.append(turn)
        if self.behavior == "raise":
            raise RuntimeError("model said no")
        if self.behavior == "slow":
            await asyncio.sleep(5)
        if self.behavior == "budget":
            raise BudgetExceeded("case cap")
        return StancePost(agent=self.name, round=turn.round, stance="need_more", confidence=0.5, claims=[])


class FakeDiscovery:
    def __init__(self):
        self.latency = {}

    def record_latency(self, name, ms):
        self.latency[name] = ms


def turn(r=1):
    return DeliberationTurn(case_id="C-1", round=r, max_rounds=4, evidence=[], transcript=[])


def transport(agent_behaviors=None, specialists=()):
    behaviors = {"buyer": "ok", "defender": "ok", "caseload": "ok", **(agent_behaviors or {})}
    agents = {a: FakeAgent(a, b) for a, b in behaviors.items()}
    return LocalTransport({s.name: s for s in specialists}, agents, discovery=FakeDiscovery())


# ---------------- specialists ----------------

async def test_call_specialist_ok_records_latency():
    t = transport(specialists=[FakeSpecialist()])
    reply = await t.call_specialist("deadlang-price-checker", CALL)
    assert reply.ok and reply.drafts[0].summary == "ok"
    assert "deadlang-price-checker" in t.discovery.latency


async def test_specialist_timeout_returns_error_timeout():
    t = transport(specialists=[FakeSpecialist(behavior="slow")])
    reply = await t.call_specialist("deadlang-price-checker", CALL, timeout=0.05)
    assert (reply.ok, reply.error) == (False, "timeout")


@pytest.mark.parametrize("behavior,error", [("raise", "price table missing"), ("budget", "budget"),
                                            ("removed", "listing_removed")])
async def test_specialist_exceptions_become_errors(behavior, error):
    t = transport(specialists=[FakeSpecialist(behavior=behavior)])
    reply = await t.call_specialist("deadlang-price-checker", CALL)
    assert (reply.ok, reply.error) == (False, error)


async def test_disabled_specialist_times_out_immediately():
    t = transport(specialists=[FakeSpecialist()])
    t.disabled.add("deadlang-price-checker")
    assert (await t.call_specialist("deadlang-price-checker", CALL)).error == "timeout"


async def test_missing_specialist_is_a_connect_error():
    reply = await transport().call_specialist("deadlang-examiner-thorough", CALL)
    assert not reply.ok and "connect" in reply.error   # the Facilitator falls back on "connect" errors


# ---------------- deliberators ----------------

@pytest.mark.parametrize("called", [[], ["buyer"], ["buyer", "caseload"], ["buyer", "defender", "caseload"]])
async def test_broadcast_calls_only_agents_in_turns(called):
    t = transport()
    results = await t.broadcast_turns({a: turn(2) for a in called})
    assert set(results) == set(called)
    assert all(isinstance(p, StancePost) and p.agent == a for a, p in results.items())
    for a, agent in t.agents.items():
        assert len(agent.turns) == (1 if a in called else 0)


async def test_broadcast_one_agent_raising_becomes_error_string():
    t = transport({"defender": "raise"})
    results = await t.broadcast_turns({a: turn() for a in ("buyer", "defender", "caseload")})
    assert isinstance(results["buyer"], StancePost) and isinstance(results["caseload"], StancePost)
    assert results["defender"] == "model said no"


async def test_broadcast_timeout_becomes_error_string():
    t = transport({"caseload": "slow"})
    results = await t.broadcast_turns({a: turn() for a in ("buyer", "caseload")}, timeout=0.05)
    assert results["caseload"] == "timeout"
    assert isinstance(results["buyer"], StancePost)


async def test_budget_exceeded_propagates_from_broadcast_and_call_agent():
    t = transport({"buyer": "budget"})
    with pytest.raises(BudgetExceeded):
        await t.broadcast_turns({a: turn() for a in ("buyer", "defender")})
    with pytest.raises(BudgetExceeded):
        await t.call_agent("buyer", turn())


async def test_call_agent_returns_post():
    post = await transport().call_agent("defender", turn(3))
    assert isinstance(post, StancePost) and (post.agent, post.round) == ("defender", 3)


# ---------------- registry ----------------

def test_registry_skips_specialists_not_written_yet(monkeypatch):
    monkeypatch.setattr(registry, "SPECIALIST_CLASSES",
                        [("tests.test_transport_local", "RegistryProbe"), ("deadlang.specialists.price", "Nope")])
    built = registry.build_specialists(market="M")
    assert [type(s).__name__ for s in built] == ["RegistryProbe"]
    assert built[0].market == "M"


class RegistryProbe:
    name, capability, tier = "probe", "price_check", "preferred"

    def __init__(self, market):
        self.market = market
