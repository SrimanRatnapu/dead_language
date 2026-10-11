import asyncio

import pytest

from deadlang.agntcy import discovery as disc
from deadlang.agntcy import transport as tr
from deadlang.agntcy.transport import LocalTransport
from deadlang.llm import BudgetExceeded
from deadlang.schemas import DeliberationTurn, EvidenceDraft, SpecialistCall, SpecialistReply, StancePost
from deadlang.specialists import registry

CALL = SpecialistCall(case_id="C-1", listing_id="L0101", capability="price_check")


class FakeSpecialist:
    capability = "price_check"
    tier = "preferred"

    def __init__(self, name="deadlang-price-checker", behavior="ok", delay=0.0):
        self.name = name
        self.behavior = behavior
        self.delay = delay

    async def run(self, call):
        if self.delay:
            await asyncio.sleep(self.delay)
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
    behaviors = {"undercover": "ok", "counsel": "ok", "case_officer": "ok", **(agent_behaviors or {})}
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

@pytest.mark.parametrize("called", [[], ["undercover"], ["undercover", "case_officer"], ["undercover", "counsel", "case_officer"]])
async def test_broadcast_calls_only_agents_in_turns(called):
    t = transport()
    results = await t.broadcast_turns({a: turn(2) for a in called})
    assert set(results) == set(called)
    assert all(isinstance(p, StancePost) and p.agent == a for a, p in results.items())
    for a, agent in t.agents.items():
        assert len(agent.turns) == (1 if a in called else 0)


async def test_broadcast_one_agent_raising_becomes_error_string():
    t = transport({"counsel": "raise"})
    results = await t.broadcast_turns({a: turn() for a in ("undercover", "counsel", "case_officer")})
    assert isinstance(results["undercover"], StancePost) and isinstance(results["case_officer"], StancePost)
    assert results["counsel"] == "model said no"


async def test_broadcast_timeout_becomes_error_string():
    t = transport({"case_officer": "slow"})
    results = await t.broadcast_turns({a: turn() for a in ("undercover", "case_officer")}, timeout=0.05)
    assert results["case_officer"] == "timeout"
    assert isinstance(results["undercover"], StancePost)


async def test_budget_exceeded_propagates_from_broadcast_and_call_agent():
    t = transport({"undercover": "budget"})
    with pytest.raises(BudgetExceeded):
        await t.broadcast_turns({a: turn() for a in ("undercover", "counsel")})
    with pytest.raises(BudgetExceeded):
        await t.call_agent("undercover", turn())


async def test_call_agent_returns_post():
    post = await transport().call_agent("counsel", turn(3))
    assert isinstance(post, StancePost) and (post.agent, post.round) == ("counsel", 3)


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


# ---------------- demo hardening: kill switch expires, reset, per-specialist minimum timeouts ----------------

def test_timeout_for_applies_a_minimum_per_specialist():
    assert tr.timeout_for("deadlang-examiner-thorough", 45.0) == 120.0
    assert tr.timeout_for("deadlang-examiner-quick", 45.0) == 60.0
    assert tr.timeout_for("deadlang-translator", 45.0) == 60.0
    assert tr.timeout_for("deadlang-price-checker", 45.0) == 45.0           # no minimum for the fast code ones
    assert tr.timeout_for("deadlang-examiner-thorough", 300.0) == 300.0     # the larger of the two wins
    assert tr.timeout_for("deadlang-examiner-quick", 30.0) == 60.0


@pytest.mark.parametrize("name", ["deadlang-examiner-thorough", "deadlang-examiner-quick", "deadlang-translator"])
async def test_slow_model_specialists_are_not_cut_off_by_the_callers_short_timeout(name):
    t = transport(specialists=[FakeSpecialist(name=name, delay=0.15)])
    reply = await t.call_specialist(name, CALL, timeout=0.05)
    assert reply.ok                                    # the minimum (60 s or more) applied, not 0.05 s


async def test_other_specialists_still_time_out_at_the_callers_timeout():
    t = transport(specialists=[FakeSpecialist(delay=0.15)])
    assert (await t.call_specialist("deadlang-price-checker", CALL, timeout=0.05)).error == "timeout"


async def test_a_killed_specialist_comes_back_after_the_same_60_seconds_as_the_unhealthy_mark(monkeypatch):
    t = transport(specialists=[FakeSpecialist()])
    monkeypatch.setattr(disc, "UNHEALTHY_SECONDS", 0.05)
    t.disabled.add("deadlang-price-checker")           # what POST /api/demo/kill-specialist does
    assert "deadlang-price-checker" in t.disabled
    assert (await t.call_specialist("deadlang-price-checker", CALL)).error == "timeout"
    await asyncio.sleep(0.07)
    assert "deadlang-price-checker" not in t.disabled
    assert (await t.call_specialist("deadlang-price-checker", CALL)).ok


def test_killing_again_restarts_the_clock(monkeypatch):
    import time
    t = transport()
    monkeypatch.setattr(disc, "UNHEALTHY_SECONDS", 0.2)
    t.disabled.add("x")
    time.sleep(0.12)
    t.disabled.add("x")
    time.sleep(0.12)
    assert "x" in t.disabled                           # 0.24 s after the first kill, 0.12 s after the second


def test_the_expiring_set_behaves_like_the_set_the_api_expects(monkeypatch):
    t = transport()
    t.disabled.add("a")
    t.disabled.add("b")
    assert "a" in t.disabled and sorted(t.disabled) == ["a", "b"] and len(t.disabled) == 2
    t.disabled.discard("a")
    t.disabled.discard("never-there")
    assert sorted(t.disabled) == ["b"]
    assert getattr(t, "disabled", None) is not None    # the API looks it up with getattr


async def test_reset_clears_every_kill():
    t = transport(specialists=[FakeSpecialist(), FakeSpecialist(name="deadlang-translator")])
    t.disabled.add("deadlang-price-checker")
    t.disabled.add("deadlang-translator")
    assert (await t.call_specialist("deadlang-price-checker", CALL)).error == "timeout"
    t.reset()
    assert len(t.disabled) == 0
    assert (await t.call_specialist("deadlang-price-checker", CALL)).ok
    assert (await t.call_specialist("deadlang-translator", CALL)).ok
