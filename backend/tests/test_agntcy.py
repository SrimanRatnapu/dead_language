"""AGNTCY layer without SLIM or the Directory running.

FakeSlim stands in for the SDK's SLIMTransport only (the network). Behind it, every agent is served by the
SDK's real A2A server bridge (A2AExperimentalServer -> a2a JSON-RPC handler -> our executor), so the
request/reply envelopes are the real ones.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from agntcy_app_sdk.directory.oasf_converter import agent_card_to_oasf
from agntcy_app_sdk.semantic.a2a.server.experimental_patterns import A2AExperimentalServer
from agntcy_app_sdk.semantic.message import Message

from deadlang import config
from deadlang.agntcy import discovery as disc
from deadlang.agntcy import serve
from deadlang.agntcy import transport as tr
from deadlang.agntcy.cards import ALL_AGENT_NAMES, DELIBERATOR_NAMES, card_for
from deadlang.agntcy.discovery import AgntcyDirectoryDiscovery
from deadlang.agntcy.transport import AgntcyTransport
from deadlang.agntcy.wire import WireError, reply_text, request_message, slim_name
from deadlang.llm import BudgetExceeded
from deadlang.schemas import DeliberationTurn, EvidenceDraft, SpecialistCall, SpecialistReply, StancePost

CALL = SpecialistCall(case_id="C-1", listing_id="L0101", capability="material_exam")


# ---------------------------------------------------------------- fakes

class FakeSpecialist:
    capability, tier = "material_exam", "preferred"

    def __init__(self, name="deadlang-examiner-thorough", behavior="ok", delay=0.0):
        self.name, self.behavior, self.delay = name, behavior, delay
        self.calls = []

    async def run(self, call):
        self.calls.append(call)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behavior == "raise":
            raise RuntimeError("examiner broke")
        if self.behavior == "budget":
            raise BudgetExceeded("cap")
        return SpecialistReply(ok=True, drafts=[EvidenceDraft(
            capability="material_exam", summary=f"{self.name} looked at {call.listing_id}", data={"n": 1},
            produced_by="model", confidence=0.7, specialist_name=self.name)])


class FakeAgent:
    def __init__(self, name, behavior="ok", delay=0.0):
        self.name, self.behavior, self.delay = name, behavior, delay
        self.turns = []

    async def handle(self, turn):
        self.turns.append(turn)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.behavior == "raise":
            raise RuntimeError("model said no")
        if self.behavior == "budget":
            raise BudgetExceeded("case cap")
        return StancePost(agent=self.name, round=turn.round, stance="need_more", confidence=0.5, claims=[])


class FakeSlim:
    """Stands in for SLIMTransport. Messages are serialized and parsed as on the wire."""

    def __init__(self):
        self.servers: dict[str, A2AExperimentalServer] = {}
        self.requests: list[tuple[str, float]] = []
        self.broadcasts: list[tuple[str, list[str], Message]] = []
        self.silent: set[str] = set()          # names that never answer (a dead process)
        self.fail: Exception | None = None     # SLIM itself unreachable

    async def serve(self, name, app):
        srv = A2AExperimentalServer()
        srv.bind_server(app)
        await srv.setup()
        self.servers[slim_name(name)] = srv

    async def _deliver(self, topic, message):
        srv = self.servers.get(topic)
        if srv is None or topic in self.silent:
            await asyncio.sleep(3600)
        reply = await srv.handle_message(Message.deserialize(message.serialize()))
        return Message.deserialize(reply.serialize())

    async def request(self, topic, message, timeout=6, **kwargs):
        self.requests.append((topic, timeout))
        if self.fail:
            raise self.fail
        try:
            return await asyncio.wait_for(self._deliver(topic, message), timeout)
        except asyncio.TimeoutError:
            return None                        # what SLIMTransport.request does on a timeout

    async def gather_stream(self, topic, message, recipients, message_limit=None, timeout=60, **kwargs):
        self.broadcasts.append((topic, list(recipients), message))
        if self.fail:
            raise self.fail
        tasks = [asyncio.ensure_future(self._deliver(r, message)) for r in recipients]
        try:
            async with asyncio.timeout(timeout):
                got = 0
                for fut in asyncio.as_completed(tasks):
                    yield await fut
                    got += 1
                    if message_limit is not None and got >= message_limit:
                        return
        finally:
            for t in tasks:
                t.cancel()


def sent_text(message: Message) -> str:
    rpc = json.loads(message.payload)
    return rpc["params"]["message"]["parts"][0]["text"]


async def network(specialists=(), agents=None):
    """A FakeSlim with servers built by serve.py for the given fakes."""
    slim = FakeSlim()
    for s in specialists:
        await slim.serve(s.name, serve.build_app(s.name, serve.specialist_handler(s)))
    for agent_name, agent in (agents or {}).items():
        name = DELIBERATOR_NAMES[agent_name]
        await slim.serve(name, serve.build_app(name, serve.deliberator_handler(agent_name, agent)))
    return slim


def turn(r=1, case_id="C-1"):
    return DeliberationTurn(case_id=case_id, round=r, max_rounds=4, evidence=[], transcript=[])


def three_agents(**behaviors):
    return {a: FakeAgent(a, behaviors.get(a, "ok")) for a in ("undercover", "counsel", "case_officer")}


class FakeDiscovery:
    def __init__(self):
        self.latency = {}

    def record_latency(self, name, ms):
        self.latency[name] = ms


# ---------------------------------------------------------------- wire

def test_request_message_is_an_a2a_message_send_with_one_text_part():
    msg = request_message('{"x": 1}')
    rpc = json.loads(msg.payload)
    assert rpc["jsonrpc"] == "2.0" and rpc["method"] == "message/send"
    assert rpc["params"]["message"]["role"] == "user"
    assert sent_text(msg) == '{"x": 1}'
    assert slim_name("deadlang-undercover") == "default/default/deadlang-undercover"


def test_reply_text_reads_a_message_result_and_raises_on_errors():
    ok = Message(type="A2AResponse", payload=json.dumps({"jsonrpc": "2.0", "id": "1", "result": {
        "kind": "message", "messageId": "m", "role": "agent", "parts": [{"kind": "text", "text": "hello"}]}}).encode())
    assert reply_text(ok) == "hello"
    bad = Message(type="A2AResponse", payload=json.dumps({"jsonrpc": "2.0", "id": "1",
                                                          "error": {"code": -32603, "message": "boom"}}).encode())
    with pytest.raises(WireError, match="boom"):
        reply_text(bad)
    empty = Message(type="A2AResponse", payload=json.dumps({"jsonrpc": "2.0", "id": "1", "result": {
        "kind": "message", "messageId": "m", "role": "agent", "parts": []}}).encode())
    with pytest.raises(WireError):
        reply_text(empty)


# ---------------------------------------------------------------- serve.py

def test_groups_cover_every_running_agent_once_and_isolate_the_thorough_examiner():
    groups = {g: names for g, names in serve.GROUPS.items() if g != "all"}
    flat = [n for names in groups.values() for n in names]
    assert sorted(flat) == sorted(ALL_AGENT_NAMES) and len(flat) == len(set(flat))
    assert groups["examiner-thorough"] == ["deadlang-examiner-thorough"]
    assert groups["examiner-quick"] == ["deadlang-examiner-quick"]
    assert sorted(groups["deliberators"]) == sorted(DELIBERATOR_NAMES.values())
    assert sorted(serve.GROUPS["all"]) == sorted(ALL_AGENT_NAMES)


async def test_specialist_handler_round_trips_a_call():
    s = FakeSpecialist()
    reply = SpecialistReply.model_validate_json(await serve.specialist_handler(s)(CALL.model_dump_json()))
    assert reply.ok and reply.drafts[0].summary == "deadlang-examiner-thorough looked at L0101"


@pytest.mark.parametrize("behavior,error", [("raise", "examiner broke"), ("budget", "budget")])
async def test_specialist_handler_turns_exceptions_into_error_replies(behavior, error):
    reply = SpecialistReply.model_validate_json(
        await serve.specialist_handler(FakeSpecialist(behavior=behavior))(CALL.model_dump_json()))
    assert (reply.ok, reply.error) == (False, error)


async def test_specialist_handler_rejects_a_bad_request():
    reply = SpecialistReply.model_validate_json(await serve.specialist_handler(FakeSpecialist())("not json"))
    assert not reply.ok and reply.error.startswith("bad request")


async def test_deliberator_handler_answers_a_direct_turn_and_its_own_entry_of_a_broadcast():
    agent = FakeAgent("counsel")
    handle = serve.deliberator_handler("counsel", agent)
    direct = StancePost.model_validate_json(await handle(turn(2).model_dump_json()))
    assert (direct.agent, direct.round) == ("counsel", 2)
    payload = json.dumps({"kind": "turns", "turns": {"undercover": json.loads(turn(3, "C-B").model_dump_json()),
                                                      "counsel": json.loads(turn(3, "C-D").model_dump_json())}})
    post = StancePost.model_validate_json(await handle(payload))
    assert post.round == 3 and agent.turns[-1].case_id == "C-D"          # picked its own entry


async def test_deliberator_handler_errors_carry_the_agent_name():
    handle = serve.deliberator_handler("case_officer", FakeAgent("case_officer"))
    missing = json.loads(await handle(json.dumps({"kind": "turns", "turns": {}})))
    assert missing["agent"] == "case_officer" and "no turn" in missing["error"]
    broken = json.loads(await serve.deliberator_handler("undercover", FakeAgent("undercover", "raise"))(turn().model_dump_json()))
    assert broken == {"agent": "undercover", "error": "model said no"}
    over = json.loads(await serve.deliberator_handler("undercover", FakeAgent("undercover", "budget"))(turn().model_dump_json()))
    assert over["agent"] == "undercover" and over["budget"] is True


async def test_build_app_serves_the_agent_card():
    app = serve.build_app("deadlang-examiner-quick", serve.specialist_handler(FakeSpecialist("deadlang-examiner-quick")))
    assert app.agent_card.name == "deadlang-examiner-quick"
    assert app.agent_card.skills[0].id == "material_exam"


async def test_executor_replies_through_the_real_sdk_server_bridge():
    slim = await network(specialists=[FakeSpecialist()])
    msg = await slim.request(slim_name("deadlang-examiner-thorough"), request_message(CALL.model_dump_json()), timeout=5)
    assert SpecialistReply.model_validate_json(reply_text(msg)).ok


# ---------------------------------------------------------------- AgntcyTransport: specialists

async def test_call_specialist_over_the_link():
    s = FakeSpecialist()
    slim = await network(specialists=[s])
    t = AgntcyTransport(discovery=FakeDiscovery(), slim=slim)
    reply = await t.call_specialist("deadlang-examiner-thorough", CALL)
    assert reply.ok and s.calls[0].listing_id == "L0101"
    assert slim.requests[0][0] == "default/default/deadlang-examiner-thorough"
    assert "deadlang-examiner-thorough" in t.discovery.latency


async def test_call_specialist_applies_the_per_specialist_minimum_timeout():
    slim = await network(specialists=[FakeSpecialist(), FakeSpecialist("deadlang-legal-table")])
    t = AgntcyTransport(slim=slim)
    await t.call_specialist("deadlang-examiner-thorough", CALL, timeout=45.0)
    await t.call_specialist("deadlang-legal-table", CALL, timeout=45.0)
    assert [timeout for _, timeout in slim.requests] == [120.0, 45.0]


async def test_a_silent_specialist_times_out(monkeypatch):
    monkeypatch.setitem(tr.MIN_SPECIALIST_TIMEOUT, "deadlang-examiner-thorough", 0.0)
    slim = await network(specialists=[FakeSpecialist()])
    slim.silent.add(slim_name("deadlang-examiner-thorough"))         # the process was killed
    reply = await AgntcyTransport(slim=slim).call_specialist("deadlang-examiner-thorough", CALL, timeout=0.05)
    assert (reply.ok, reply.error) == (False, "timeout")


async def test_slim_unreachable_is_a_connect_error_so_the_facilitator_falls_back():
    slim = FakeSlim()
    slim.fail = ConnectionError("connection refused")
    reply = await AgntcyTransport(slim=slim).call_specialist("deadlang-examiner-thorough", CALL)
    assert not reply.ok and "connect" in reply.error.lower()


async def test_specialist_errors_come_back_as_replies():
    slim = await network(specialists=[FakeSpecialist(behavior="raise")])
    reply = await AgntcyTransport(slim=slim).call_specialist("deadlang-examiner-thorough", CALL)
    assert (reply.ok, reply.error) == (False, "examiner broke")


async def test_kill_switch_and_reset_work_in_agntcy_mode_too():
    slim = await network(specialists=[FakeSpecialist()])
    t = AgntcyTransport(slim=slim)
    t.disabled.add("deadlang-examiner-thorough")                       # POST /api/demo/kill-specialist
    assert (await t.call_specialist("deadlang-examiner-thorough", CALL)).error == "timeout"
    assert slim.requests == []                                         # nothing was sent
    t.reset()
    assert (await t.call_specialist("deadlang-examiner-thorough", CALL)).ok


async def test_slim_that_never_answers_becomes_a_connect_error_not_a_hang(monkeypatch):
    class HangingLink:
        async def setup(self):
            await asyncio.sleep(3600)                          # what the SLIM bindings do when SLIM is down

    class Factory:
        def create_transport(self, *args, **kwargs):
            return HangingLink()

    monkeypatch.setattr(tr, "LINK_TIMEOUT", 0.05)
    t = AgntcyTransport(factory=Factory())
    reply = await asyncio.wait_for(t.call_specialist("deadlang-legal-table", CALL), 2)
    assert not reply.ok and "connect" in reply.error and "did not answer" in reply.error
    assert "connect" in await asyncio.wait_for(t.call_agent("undercover", turn()), 2)
    assert all("connect" in v for v in (await asyncio.wait_for(t.broadcast_turns({"undercover": turn()}), 2)).values())


# ---------------------------------------------------------------- AgntcyTransport: deliberators

@pytest.mark.parametrize("called", [["undercover"], ["undercover", "case_officer"], ["undercover", "counsel", "case_officer"]])
async def test_broadcast_goes_only_to_the_agents_named_in_turns(called):
    agents = three_agents()
    slim = await network(agents=agents)
    results = await AgntcyTransport(slim=slim).broadcast_turns({a: turn(2) for a in called})

    assert set(results) == set(called)
    assert all(isinstance(p, StancePost) and p.agent == a for a, p in results.items())
    (_, recipients, message), = slim.broadcasts
    assert sorted(recipients) == sorted(slim_name(DELIBERATOR_NAMES[a]) for a in called)
    payload = json.loads(sent_text(message))
    assert payload["kind"] == "turns" and sorted(payload["turns"]) == sorted(called)   # only their turns are sent
    for a, agent in agents.items():
        assert len(agent.turns) == (1 if a in called else 0)


async def test_empty_turns_returns_an_empty_dict_without_sending():
    slim = FakeSlim()
    slim.fail = AssertionError("must not touch the network")
    assert await AgntcyTransport(slim=slim).broadcast_turns({}) == {}
    assert slim.broadcasts == []


async def test_each_agent_gets_its_own_turn():
    agents = three_agents()
    slim = await network(agents=agents)
    await AgntcyTransport(slim=slim).broadcast_turns({"undercover": turn(2, "C-buyer"), "counsel": turn(2, "C-def")})
    assert agents["undercover"].turns[0].case_id == "C-buyer" and agents["counsel"].turns[0].case_id == "C-def"


async def test_broadcast_one_agent_failing_becomes_its_error_string():
    slim = await network(agents=three_agents(counsel="raise"))
    results = await AgntcyTransport(slim=slim).broadcast_turns({a: turn() for a in ("undercover", "counsel", "case_officer")})
    assert results["counsel"] == "model said no"
    assert isinstance(results["undercover"], StancePost) and isinstance(results["case_officer"], StancePost)


async def test_broadcast_keeps_the_answers_that_arrived_when_one_agent_is_silent():
    slim = await network(agents=three_agents())
    slim.silent.add(slim_name("deadlang-case_officer"))
    results = await AgntcyTransport(slim=slim).broadcast_turns({a: turn() for a in ("undercover", "case_officer")}, timeout=0.2)
    assert isinstance(results["undercover"], StancePost) and results["case_officer"] == "timeout"


async def test_broadcast_raises_budget_exceeded_like_the_local_transport():
    slim = await network(agents=three_agents(undercover="budget"))
    with pytest.raises(BudgetExceeded):
        await AgntcyTransport(slim=slim).broadcast_turns({a: turn() for a in ("undercover", "counsel")})


async def test_broadcast_with_slim_down_gives_each_agent_an_error():
    slim = FakeSlim()
    slim.fail = ConnectionError("connection refused")
    results = await AgntcyTransport(slim=slim).broadcast_turns({a: turn() for a in ("undercover", "counsel")})
    assert set(results) == {"undercover", "counsel"} and all("connect" in v for v in results.values())


async def test_point_to_point_mode_sends_one_request_per_agent():
    agents = three_agents()
    slim = await network(agents=agents)
    t = AgntcyTransport(slim=slim, broadcast=False)               # the fallback if broadcast misbehaves
    results = await t.broadcast_turns({a: turn() for a in ("undercover", "case_officer")})
    assert set(results) == {"undercover", "case_officer"} and slim.broadcasts == []
    assert sorted(topic for topic, _ in slim.requests) == ["default/default/deadlang-case_officer",
                                                           "default/default/deadlang-undercover"]


async def test_call_agent_for_repairs():
    agents = three_agents(case_officer="raise")
    slim = await network(agents=agents)
    t = AgntcyTransport(slim=slim)
    post = await t.call_agent("counsel", turn(3))
    assert isinstance(post, StancePost) and (post.agent, post.round) == ("counsel", 3)
    assert await t.call_agent("case_officer", turn(3)) == "model said no"
    budget = await network(agents=three_agents(undercover="budget"))
    with pytest.raises(BudgetExceeded):
        await AgntcyTransport(slim=budget).call_agent("undercover", turn())


async def test_a_silent_agent_times_out_on_a_direct_call():
    slim = await network(agents=three_agents())
    slim.silent.add(slim_name("deadlang-undercover"))
    assert await AgntcyTransport(slim=slim).call_agent("undercover", turn(), timeout=0.05) == "timeout"


# ---------------------------------------------------------------- AgntcyDirectoryDiscovery

class FakeDirectory:
    """Stands in for the SDK's AgentDirectory: stores OASF records, searches by name like the real one."""

    def __init__(self):
        self.records: list[dict] = []
        self.fail: Exception | None = None
        self.hang = False
        self.searches: list[str] = []

    async def setup(self):
        if self.fail:
            raise self.fail

    async def push_agent_record(self, card, *args, **kwargs):
        if self.fail:
            raise self.fail
        self.records.append(agent_card_to_oasf(card))
        return f"cid-{len(self.records)}"

    async def search_agent_records(self, query, limit=10, *args, **kwargs):
        self.searches.append(query)
        if self.fail:
            raise self.fail
        if self.hang:
            await asyncio.sleep(3600)
        return [r for r in self.records if query in r["name"]][:limit]   # substring, to prove we filter


async def test_directory_finds_registered_agents_and_says_so():
    d = FakeDirectory()
    dd = AgntcyDirectoryDiscovery(directory=d)
    await dd.register(["deadlang-examiner-thorough", "deadlang-examiner-quick"])
    sel = await dd.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-thorough"
    assert sel.candidates == ["deadlang-examiner-thorough", "deadlang-examiner-quick"]
    assert sel.why == ("Chose deadlang-examiner-thorough: it offers material_exam at the preferred quality tier "
                       "and is responding. Found via the AGNTCY Directory.")
    assert dd.cids == {"deadlang-examiner-thorough": "cid-1", "deadlang-examiner-quick": "cid-2"}


async def test_only_agents_that_registered_are_offered():
    dd = AgntcyDirectoryDiscovery(directory=FakeDirectory())
    await dd.register(["deadlang-examiner-quick"])
    sel = await dd.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-quick" and sel.candidates == ["deadlang-examiner-quick"]
    assert sel.why == ("deadlang-examiner-quick is the only registered agent offering material_exam. "
                       "Found via the AGNTCY Directory.")
    assert await dd.select("price_check") is None                     # nobody registered it


async def test_unhealthy_preferred_falls_back_with_the_same_sentence_plus_the_directory_note():
    dd = AgntcyDirectoryDiscovery(directory=FakeDirectory())
    await dd.register(["deadlang-examiner-thorough", "deadlang-examiner-quick"])
    await dd.mark_unhealthy("deadlang-examiner-thorough")
    sel = await dd.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-quick"
    assert sel.why == ("deadlang-examiner-thorough did not respond, so chose deadlang-examiner-quick, which offers "
                       "material_exam at a lower quality tier. Found via the AGNTCY Directory.")


async def test_exclude_and_name_filtering():
    d = FakeDirectory()
    dd = AgntcyDirectoryDiscovery(directory=d)
    await dd.register(["deadlang-examiner-thorough", "deadlang-examiner-quick"])
    other = card_for("deadlang-examiner-quick").model_copy(deep=True)
    other.name = "deadlang-examiner-thorough-copycat"                 # a substring match that must be ignored
    d.records.append(agent_card_to_oasf(other))
    await dd.register(["deadlang-examiner-thorough"])                  # pushed twice: still one candidate
    sel = await dd.select("material_exam", exclude={"deadlang-examiner-thorough"})
    assert sel.specialist_name == "deadlang-examiner-quick" and sel.candidates == ["deadlang-examiner-quick"]
    assert sorted(d.searches[-2:]) == ["deadlang-examiner-quick", "deadlang-examiner-thorough"]


@pytest.mark.parametrize("problem", ["error", "hang"])
async def test_directory_trouble_falls_back_to_local_discovery(problem, monkeypatch):
    monkeypatch.setattr(disc, "DIRECTORY_TIMEOUT", 0.05)
    d = FakeDirectory()
    dd = AgntcyDirectoryDiscovery(directory=d)
    if problem == "error":
        d.fail = ConnectionError("directory down")
    else:
        d.hang = True
    sel = await dd.select("material_exam")
    assert sel.specialist_name == "deadlang-examiner-thorough"
    assert "AGNTCY Directory" not in sel.why                         # honest: this one came from local cards


async def test_after_a_directory_failure_it_is_skipped_for_a_while_then_retried(monkeypatch):
    monkeypatch.setattr(disc, "DIRECTORY_RETRY_AFTER", 0.2)
    d = FakeDirectory()
    d.fail = ConnectionError("directory down")
    dd = AgntcyDirectoryDiscovery(directory=d)
    await dd.select("material_exam")                    # real failure: starts the window
    failed_searches = len(d.searches)
    d.fail = None
    d.records.append(agent_card_to_oasf(card_for("deadlang-price-checker")))
    for _ in range(3):                                  # inside the window: local cards, no Directory calls
        assert "AGNTCY Directory" not in (await dd.select("price_check")).why
        await asyncio.sleep(0.05)
    assert len(d.searches) == failed_searches           # and these skips did not extend the window
    await asyncio.sleep(0.1)                            # now 0.25 s after the failure
    assert (await dd.select("price_check")).why.endswith("Found via the AGNTCY Directory.")


async def test_health_is_shared_with_the_local_fallback():
    d = FakeDirectory()
    d.fail = ConnectionError("down")
    dd = AgntcyDirectoryDiscovery(directory=d)
    await dd.mark_unhealthy("deadlang-examiner-thorough")
    assert (await dd.select("material_exam")).specialist_name == "deadlang-examiner-quick"


async def test_register_all_never_breaks_api_startup():
    d = FakeDirectory()
    d.fail = ConnectionError("down")
    await AgntcyDirectoryDiscovery(directory=d).register_all()         # logs, does not raise
    assert d.records == []                                              # serve processes register their own agents


async def test_register_raises_so_serve_can_report_it():
    d = FakeDirectory()
    d.fail = ConnectionError("down")
    with pytest.raises(ConnectionError):
        await AgntcyDirectoryDiscovery(directory=d).register(["deadlang-undercover"])


# ---------------------------------------------------------------- factories

def test_factories_pick_the_agntcy_versions_from_env(monkeypatch):
    monkeypatch.setattr(config, "TRANSPORT", "agntcy")
    monkeypatch.setattr(config, "DISCOVERY", "agntcy")
    monkeypatch.setattr(tr, "_transport", None)
    monkeypatch.setattr(disc, "_discovery", None)
    d = disc.get_discovery()
    t = tr.get_transport()
    assert isinstance(d, AgntcyDirectoryDiscovery) and isinstance(t, AgntcyTransport)
    assert t.discovery is d and t.broadcast is config.AGNTCY_BROADCAST
    monkeypatch.setattr(tr, "_transport", None)
    monkeypatch.setattr(disc, "_discovery", None)
