"""What an unattended overnight eval must survive: odd model output, dropped connections, and honest claim counts.
Stub model clients only: no API calls."""
import asyncio
import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import pytest
from pydantic import ValidationError

from deadlang import config, lenient, llm
from deadlang.agntcy.cards import ALL_AGENT_NAMES, card_for
from deadlang.agntcy.discovery import LocalDiscovery
from deadlang.agntcy.transport import LocalTransport
from deadlang.deliberation.agents import DeliberatingAgent, post_schema
from deadlang.deliberation.facilitator import AGENTS
from deadlang.eval import full_eval as fe
from deadlang.schemas import DeliberationTurn
from deadlang.specialists.network import LinkedSellers, SellerInventory
from deadlang.specialists.price import PriceChecker
from tests.test_full_eval import (Scripted, evaluator, item_by_id, parse, pop, real_singletons, run, run_cli,  # noqa: F401
                                  sample_rows, world, OFFICER, COUNSEL, UNDERCOVER)

SCHEMA = post_schema()
GOOD_CLAIM = {"text": "The listing describes the item as bone.", "evidence_ids": ["E0"]}
REBUTTAL = {"target_agent": "counsel", "target_claim": "The listing describes the item as bone.", "response": "Bone is stated.", "evidence_ids": ["E0"]}
REQUEST = {"capability": "seller_inventory", "question": "What else do they sell?", "reason": "Look for a pattern.", "params": {"seller_id": "S1"}}


def post(**kw):
    return {"stance": "file", "confidence": 0.7, "claims": [GOOD_CLAIM], "ready_to_close": True, "take": "I think so.", **kw}


# ---------------------------------------------------------------- lenient reading

def test_a_nested_object_sent_as_a_json_string_is_decoded():
    fixed = lenient.coerce(post(rebuttal=json.dumps(REBUTTAL)), SCHEMA)
    assert fixed["rebuttal"] == REBUTTAL


def test_lists_and_items_sent_as_strings_are_decoded_at_any_depth():
    out = lenient.coerce(post(claims=json.dumps([GOOD_CLAIM]), requests=[json.dumps(REQUEST), REQUEST],
                              changed_because_evidence='["E1"]'), SCHEMA)
    assert out["claims"] == [GOOD_CLAIM] and out["requests"] == [REQUEST, REQUEST] and out["changed_because_evidence"] == ["E1"]


def test_a_fenced_block_and_null_for_an_optional_object_are_understood():
    out = lenient.coerce(post(rebuttal="```json\n" + json.dumps(REBUTTAL) + "\n```", challenge="null"), SCHEMA)
    assert out["rebuttal"] == REBUTTAL and out["challenge"] is None


def test_real_text_is_never_changed_and_the_input_is_not_mutated():
    original = post(take='{"this": "is a take that looks like json"}', changed_because="[not json")
    snapshot = json.dumps(original, sort_keys=True)
    out = lenient.coerce(original, SCHEMA)
    assert out["take"] == original["take"] and out["changed_because"] == "[not json"      # strings stay strings
    assert json.dumps(original, sort_keys=True) == snapshot


def test_text_that_does_not_parse_is_left_for_validation_to_reject():
    assert lenient.coerce(post(rebuttal="not json at all"), SCHEMA)["rebuttal"] == "not json at all"


# ---------------------------------------------------------------- the agent: lenient read + one repair

class Sequence:
    """A stub client that answers post_position calls from a list, and keeps what it was asked."""

    def __init__(self, *answers):
        self.messages, self.answers, self.requests = self, list(answers), []

    async def create(self, **req):
        self.requests.append(req)
        out = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        usage = NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return NS(content=[NS(type="tool_use", name=req["tools"][0]["name"], input=out)], usage=usage)


def turn(round_no=1):
    return DeliberationTurn(case_id="rob-1", round=round_no, max_rounds=4, evidence=[], transcript=[])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", config.REPO_ROOT / "does-not-matter.json") if False else None
    yield
    llm.set_client_for_tests(None)


async def test_a_rebuttal_sent_as_a_string_is_accepted_without_a_second_call(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    stub = Sequence(post(rebuttal=json.dumps(REBUTTAL)))
    llm.set_client_for_tests(stub)
    result = await DeliberatingAgent("counsel").handle(turn(2))
    assert result.rebuttal.target_agent == "counsel" and len(stub.requests) == 1


async def test_a_missing_required_field_gets_one_repair_call_that_names_the_problem(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    bad_request = {k: v for k, v in REQUEST.items() if k != "reason"}                        # the L0221 failure
    stub = Sequence(post(requests=[REQUEST, bad_request]), post(requests=[REQUEST, REQUEST]))
    llm.set_client_for_tests(stub)
    result = await DeliberatingAgent("counsel").handle(turn())
    assert len(result.requests) == 2 and len(stub.requests) == 2
    second_user = json.dumps(stub.requests[1]["messages"])
    assert "Fix these problems" in second_user and "requests.1.reason" in second_user
    assert "Fix these problems" not in json.dumps(stub.requests[0]["messages"])


async def test_a_second_bad_answer_raises_so_the_listing_is_recorded_as_an_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    bad = post(requests=[{k: v for k, v in REQUEST.items() if k != "reason"}])
    stub = Sequence(bad, bad)
    llm.set_client_for_tests(stub)
    with pytest.raises(ValidationError):
        await DeliberatingAgent("counsel").handle(turn())
    assert len(stub.requests) == 2                                   # one repair, not a loop


# ---------------------------------------------------------------- connection retry

def connection_error():
    return anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


class Flaky:
    def __init__(self, failures, exc=connection_error):
        self.messages, self.failures, self.exc, self.calls = self, failures, exc, 0

    async def create(self, **req):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc()
        usage = NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return NS(content=[NS(type="tool_use", name=req["tools"][0]["name"], input={"ok": True})], usage=usage)


async def call(model="claude-haiku-4-5-20251001"):
    return await llm.call_json(model=model, system="s", user="u", schema_name="t", schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                               case_id="conn-1", max_tokens=50)


@pytest.fixture
def quick(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(llm, "RETRY_SLEEP", 0)
    monkeypatch.setattr(llm, "CONNECTION_BACKOFF", (0.01, 0.02))
    yield
    llm.set_client_for_tests(None)
    monkeypatch.setattr(llm, "CONNECTION_RETRY_SECONDS", 0.0)


async def test_by_default_a_connection_error_gets_the_single_quick_retry_only(quick):
    flaky = Flaky(failures=3)
    llm.set_client_for_tests(flaky)
    with pytest.raises(anthropic.APIConnectionError):
        await call()
    assert flaky.calls == 2


async def test_with_a_retry_window_a_dropped_connection_is_ridden_out(quick, monkeypatch):
    monkeypatch.setattr(llm, "CONNECTION_RETRY_SECONDS", 5.0)
    flaky = Flaky(failures=5)
    llm.set_client_for_tests(flaky)
    assert await call() == {"ok": True}
    assert flaky.calls == 6                                          # the first, the quick retry, then 4 backed-off tries


async def test_a_timeout_is_ridden_out_the_same_way(quick, monkeypatch):
    monkeypatch.setattr(llm, "CONNECTION_RETRY_SECONDS", 5.0)
    flaky = Flaky(failures=3, exc=lambda: anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")))
    llm.set_client_for_tests(flaky)
    assert await call() == {"ok": True}


async def test_it_gives_up_when_the_window_is_over(quick, monkeypatch):
    monkeypatch.setattr(llm, "CONNECTION_RETRY_SECONDS", 0.05)
    flaky = Flaky(failures=10_000)
    llm.set_client_for_tests(flaky)
    with pytest.raises(anthropic.APIConnectionError):
        await call()
    assert 2 < flaky.calls < 50


async def test_other_errors_are_not_retried_in_the_window(quick, monkeypatch):
    monkeypatch.setattr(llm, "CONNECTION_RETRY_SECONDS", 5.0)
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    flaky = Flaky(failures=10, exc=lambda: anthropic.AuthenticationError("bad key", response=resp, body=None))
    llm.set_client_for_tests(flaky)
    with pytest.raises(anthropic.AuthenticationError):
        await call()
    assert flaky.calls == 1


@pytest.mark.parametrize("text,expected", [
    ("Connection error.", True), ("triage: APIConnectionError: Connection error.", True), ("agent counsel: timeout", True),
    ("Request timed out.", True), ("Triage could not run (APITimeoutError), so this listing goes to the agents.", True),
    ("agent counsel: Error code: 401 - invalid x-api-key", False), ("Your credit balance is too low", False),
    ("1 validation error for StancePost", False)])
def test_connection_errors_are_told_apart_from_other_errors(text, expected):
    assert fe.is_connection_error(text) is expected


async def test_connection_errors_do_not_count_toward_the_five_in_a_row_stop(world):
    ev = evaluator(world)
    orig = ev.run_listing

    async def flaky_row(item):
        row = await orig(item)
        row["errors"], row["connection_error"] = ["agent counsel: Connection error."], True
        return row

    ev.run_listing = flaky_row
    summary, lines = await run(world, ev, fe.select(pop(world), limit=8), concurrency=1)
    assert summary.done == 8 and summary.errors == 8 and summary.stopped is None


async def test_other_errors_still_stop_the_run_after_five(world):
    ev = evaluator(world)
    orig = ev.run_listing

    async def bad_row(item):
        row = await orig(item)
        row["errors"], row["connection_error"] = ["agent counsel: Error code: 401 - invalid x-api-key"], False
        return row

    ev.run_listing = bad_row
    summary, _ = await run(world, ev, fe.select(pop(world), limit=8), concurrency=1)
    assert summary.stopped == "errors" and summary.done == 5


async def test_a_long_outage_of_connection_errors_stops_the_run_too(world, monkeypatch):
    monkeypatch.setattr(fe, "GIVE_UP_CONNECTION_AFTER", 3)
    ev = evaluator(world)
    orig = ev.run_listing

    async def down(item):
        row = await orig(item)
        row["errors"], row["connection_error"] = ["Connection error."], True
        return row

    ev.run_listing = down
    summary, lines = await run(world, ev, fe.select(pop(world), limit=8), concurrency=1)
    assert summary.stopped == "connection" and summary.done == 3 and any("run the same command again" in l for l in lines)


async def test_a_row_made_only_of_connection_errors_is_marked_so(world):
    class Down:
        async def __call__(self, listing, seller=None, **kw):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    row = await evaluator(world, screen=Down()).run_listing(item_by_id(world, "L0001"))
    assert row["errors"] and row["connection_error"] is True
    other = await evaluator(world, fail=(COUNSEL,)).run_listing(item_by_id(world, "L0001"))
    assert other["errors"] and other["connection_error"] is False


# ---------------------------------------------------------------- rows explain contested cases

async def test_a_row_keeps_each_agents_final_stance_and_take_and_the_stop_reason(world):
    ev = evaluator(world, stances=("file", "dismiss", "need_more"))
    row = await ev.run_listing(item_by_id(world, "L0001"))
    assert row["stop_reason"] and set(row["final"]) == set(AGENTS)
    assert row["final"][UNDERCOVER]["stance"] == "file" and row["final"][COUNSEL]["stance"] == "dismiss"
    assert row["final"][UNDERCOVER]["take"] == "x" and row["final"][OFFICER]["abstained"] is False and row["final"][OFFICER]["stance"] == "need_more"
    assert set(row["final"][UNDERCOVER]) >= {"stance", "confidence", "take", "ready_to_close", "abstained", "claims"}


# ---------------------------------------------------------------- is the claim validator really counting?

class Fabricator:
    """A stub client whose agents invent a number and a quote on their first answer; `persist` keeps inventing after the repair."""

    def __init__(self, persist=False):
        self.messages, self.persist, self.repairs = self, persist, 0

    async def create(self, **req):
        name = req["tools"][0]["name"]
        user = json.dumps(req["messages"])
        usage = NS(input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if name == "post_position":
            repair = "Fix these problems" in user
            self.repairs += repair
            claims = [{"text": "The listing describes the item as bone.", "evidence_ids": ["E0"]}]
            if not repair or self.persist:
                claims += [{"text": "It is priced at $9,999 which is far above bone.", "evidence_ids": ["E0"]},
                           {"text": 'The seller wrote "genuine ancient royal ivory carving collection".', "evidence_ids": ["E0"]}]
            out = {"stance": "file", "confidence": 0.8, "ready_to_close": True, "take": "t", "claims": claims}
        elif name == "report_screening":
            out = {"score": 0.7, "suspicious": True, "reason": "r"}
        else:
            out = {}
        return NS(content=[NS(type="tool_use", name=name, input=out)], usage=usage)


def real_evaluator(world, run_id="val"):
    agents = {role: DeliberatingAgent(role) for role in AGENTS}
    specs = [SellerInventory(world.market), LinkedSellers(world.market), PriceChecker(world.market)]
    discovery = LocalDiscovery([card_for(n) for n in ALL_AGENT_NAMES])
    return fe.Evaluator(run_id, world.market, LocalTransport({s.name: s for s in specs}, agents, discovery=discovery), discovery)


async def test_the_validator_runs_on_real_agent_claims_and_the_row_counts_a_fabricated_number_and_quote(world, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODEL_STRONG", "claude-sonnet-5-5")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    stub = Fabricator()
    llm.set_client_for_tests(stub)
    try:
        ev = real_evaluator(world)
        monkeypatch.setattr(ev, "screen", lambda *a, **k: _triage_ok())
        row = await ev.run_listing(item_by_id(world, "L0001"))
    finally:
        llm.set_client_for_tests(None)
    assert row["errors"] == [], row["errors"]
    c = row["claims"][UNDERCOVER]
    assert c["made"] >= 3 and c["rejected"] >= 2                      # the invented $9,999 and the invented quote were caught
    assert c["repairs"] >= 1 and c["rejected_after_repair"] == 0      # and the repair call removed them
    assert stub.repairs >= 2
    assert row["final"][UNDERCOVER]["claims"] == 1                    # only the grounded claim is left in the final post


async def test_an_agent_that_keeps_inventing_after_the_repair_is_counted_both_ways(world, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODEL_STRONG", "claude-sonnet-5-5")
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    llm.set_client_for_tests(Fabricator(persist=True))
    try:
        ev = real_evaluator(world)
        monkeypatch.setattr(ev, "screen", lambda *a, **k: _triage_ok())
        row = await ev.run_listing(item_by_id(world, "L0001"))
    finally:
        llm.set_client_for_tests(None)
    c = row["claims"][UNDERCOVER]
    assert c["rejected"] >= 2 and c["rejected_after_repair"] >= 2 and c["rejected_after_repair"] <= c["rejected"]


async def _triage_ok():
    from deadlang.schemas import TriageResult
    return TriageResult(score=0.7, suspicious=True, reason="r")


def test_claim_quality_reports_the_first_pass_rate_and_what_survived_the_repair():
    rows = sample_rows()
    for r in rows:
        for a in AGENTS:
            r["claims"][a].update(rejected_after_repair=0, repairs=1)
    cq = fe.score_rows(rows, threshold=0.2)["claim_quality"][UNDERCOVER]
    assert cq["rejected"] == 10 and cq["rejection_rate"] == 0.25 and cq["rejected_after_repair"] == 0 and cq["repair_calls"] == 10


# ---------------------------------------------------------------- triage only

def triage_rows(n_pos=3, n_neg=7):
    rows = []
    for i in range(n_pos + n_neg):
        pos = i < n_pos
        score = [0.9, 0.3, 0.12, 0.4, 0.02, 0.05, 0.08, 0.6, 0.1, 0.2][i % 10]
        rows.append({"run_id": "t", "listing_id": f"T{i}", "label": pos, "category": "ivory" if pos else ("tagua" if i % 2 else "legal_bone"),
                     "triage": {"score": score, "flagged": score >= 0.5, "reason": "r"}, "errors": [],
                     "cost_usd": {"triage": 0.001, "total": 0.001}})
    return rows


def test_triage_only_scoring_gives_recall_and_clearance_at_every_threshold():
    res = fe.score_triage(triage_rows(), threshold=0.15)
    assert res["population"]["n_scored"] == 10 and res["population"]["n_positives"] == 3
    at = {s["threshold"]: s for s in res["sweep"]}
    assert [s["threshold"] for s in res["sweep"]] == [round(0.05 * i, 2) for i in range(1, 11)]
    # positives: 0.9 flagged, 0.3, 0.12; negatives 0.4 .02 .05 .08 .6(flagged) .1 .2
    assert at[0.15]["recall"]["text"] == "2 of 3" and at[0.15]["missed_positives"] == ["T2"]
    assert at[0.05]["recall"]["text"] == "3 of 3" and at[0.05]["cleared"]["text"] == "1 of 10"
    assert at[0.5]["cleared"]["count"] == 8 and at[0.5]["recall"]["text"] == "1 of 3"
    assert at[0.15]["is_current_threshold"] and res["at_current_threshold"]["cleared"]["text"] == "5 of 10"
    assert res["total_cost_usd"] == pytest.approx(0.01)


def test_writing_triage_full_keeps_every_other_key(world):
    path = fe.eval_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"A": {"n_pos": 1}, "full_eval": {"run_id": "s100", "configs": {"x": 1}}}))
    fe.write_triage_full(fe.score_triage(triage_rows(), 0.15), "t1")
    data = json.loads(path.read_text())
    assert data["A"] == {"n_pos": 1} and data["full_eval"]["run_id"] == "s100" and data["full_eval"]["configs"] == {"x": 1}
    assert data["full_eval"]["triage_full"]["run_id"] == "t1"
    fe.write_eval(fe.score_rows(sample_rows(), 0.2), "s101")                   # a later full score keeps the triage result
    data = json.loads(path.read_text())
    assert data["full_eval"]["run_id"] == "s101" and data["full_eval"]["triage_full"]["run_id"] == "t1"


def test_triage_only_creates_eval_json_when_there_is_none(world):
    fe.write_triage_full(fe.score_triage(triage_rows(), 0.15), "t1")
    assert "triage_full" in json.loads(fe.eval_json_path().read_text())["full_eval"]


async def test_the_triage_only_row_runs_nothing_but_triage(world):
    ev = evaluator(world, triage_scores={"L0001": 0.8})
    row = await ev.run_triage(item_by_id(world, "L0001"))
    assert row["errors"] == [] and row["triage"]["score"] == 0.8 and row["triage"]["flagged"] is True
    assert all(not a.turns for a in ev.agents.values())              # no agent was called
    assert row["cost_usd"]["total"] == 0 and ev.fake_triage.calls[0]["case_id"] == "ev-r1-L0001-tonly"


def test_triage_only_end_to_end_with_the_real_local_market_resumes_and_writes_the_result(real_singletons, monkeypatch):
    llm.set_client_for_tests(Scripted())
    try:
        argv = ["--triage-only", "--run-id", "tri", "--yes", "--limit", "5", "--concurrency", "2"]
        code, out = run_cli(real_singletons, monkeypatch, argv, market=None)
        assert code == 0, out
        rows = fe.read_rows("tri.triage")
        assert len(rows) == 5 and all(r["triage"]["score"] == 0.7 and not r["errors"] for r in rows.values())
        assert not fe.rows_path("tri").exists()                      # the full-run rows are a different file
        full = json.loads(fe.eval_json_path().read_text())["full_eval"]["triage_full"]
        assert full["run_id"] == "tri" and full["population"]["n_scored"] == 5 and len(full["sweep"]) == 10
        code, out = run_cli(real_singletons, monkeypatch, argv, market=None)
        assert code == 0 and "Nothing left to run" in out
        code, out = run_cli(real_singletons, monkeypatch, ["--triage-only", "--score-only", "--run-id", "tri", "--threshold", "0.3"], market=None)
        assert code == 0 and json.loads(fe.eval_json_path().read_text())["full_eval"]["triage_full"]["threshold"] == 0.3
    finally:
        llm.set_client_for_tests(None)


def test_triage_only_dry_run_prices_only_triage_and_stays_off_the_network(world, monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda **kw: pytest.fail("a dry run must not call a model"))
    code, out = run_cli(world, monkeypatch, ["--triage-only", "--dry-run"])
    assert code == 0 and "triage only: 16 x" in out and "thorough examiner" not in out and "three agents" not in out
    assert "--triage-only" in out and "Dry run" in out
