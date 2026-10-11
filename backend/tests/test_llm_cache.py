"""Prompt caching in llm.py, and usage, budget caps and pricing that count cached tokens correctly. Stub client only."""
import asyncio
from types import SimpleNamespace

import pytest

from deadlang import config, costs, llm

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5-20251001"
SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
BIG = "You are a careful reviewer. " * 400            # ~11k characters: well over every model's minimum prefix
SMALL = "sys"


def resp(tokens_in=10, tokens_out=5, read=None, write=None, inp=None):
    usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    if read is not None:
        usage.cache_read_input_tokens = read
    if write is not None:
        usage.cache_creation_input_tokens = write
    block = SimpleNamespace(type="tool_use", name="report_x", input=inp if inp is not None else {"x": 1})
    return SimpleNamespace(content=[block], usage=usage)


class Client:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.messages = self

    async def create(self, **req):
        self.requests.append(req)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(llm, "usage_hook", None)
    yield
    llm.set_client_for_tests(None)


async def call(model=SONNET, system=BIG, case_id="C-1", **kw):
    return await llm.call_json(model=model, system=system, user="hello", schema_name="report_x", schema=SCHEMA,
                               case_id=case_id, **kw)


def system_of(request):
    return request["system"]


# ---------------- what gets marked cacheable ----------------

async def test_a_big_stable_prefix_on_sonnet_is_marked_cacheable_on_the_system_block():
    client = Client(resp())
    llm.set_client_for_tests(client)
    await call()
    system = system_of(client.requests[0])
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["type"] == "text" and system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"].startswith(BIG) and "report_x" in system[0]["text"]        # includes the tool instruction
    assert "cache_control" not in client.requests[0]["tools"][0]                         # the breakpoint is on the system block;
    assert client.requests[0]["messages"][0]["content"] == "hello"                       # tools render first, so they are cached with it


async def test_haiku_is_never_marked_even_with_a_huge_prompt():
    client = Client(resp())
    llm.set_client_for_tests(client)
    await call(model=HAIKU)
    assert isinstance(system_of(client.requests[0]), str)
    assert "cache_control" not in str(client.requests[0])


async def test_a_prefix_below_the_models_minimum_is_left_alone():
    client = Client(resp())
    llm.set_client_for_tests(client)
    await call(system=SMALL)
    assert isinstance(system_of(client.requests[0]), str) and "cache_control" not in str(client.requests[0])


@pytest.mark.parametrize("model,minimum", [("claude-sonnet-5-5", 512), ("claude-opus-5-5", 512), ("claude-sonnet-5", 1024),
                                           ("claude-sonnet-4-6", 1024), ("claude-opus-4-7", 2048),
                                           ("claude-opus-4-6", 4096), ("claude-haiku-4-5-20251001", None),
                                           ("claude-haiku-5-5", None)])
def test_the_minimum_prefix_follows_the_model(model, minimum):
    assert llm.cache_min_tokens(model) == minimum


def test_cached_prefix_tokens_is_zero_unless_the_prefix_would_cache():
    assert llm.cached_prefix_tokens(SONNET, BIG, SCHEMA, "report_x") > 2000
    assert llm.cached_prefix_tokens(SONNET, SMALL, SCHEMA, "report_x") == 0
    assert llm.cached_prefix_tokens(HAIKU, BIG, SCHEMA, "report_x") == 0
    mid = "word " * 500                                                                   # ~2,100 tokens: enough for Sonnet 5.5, not Opus 4.6
    assert llm.cached_prefix_tokens("claude-opus-4-6", mid, SCHEMA, "report_x") == 0
    assert llm.cached_prefix_tokens(SONNET, mid, SCHEMA, "report_x") > 0


async def test_the_cached_block_is_identical_from_call_to_call_so_it_can_actually_hit():
    client = Client(resp(), resp())
    llm.set_client_for_tests(client)
    await call()
    await llm.call_json(model=SONNET, system=BIG, user="a completely different listing", schema_name="report_x",
                        schema=SCHEMA, case_id="C-2")
    assert system_of(client.requests[0]) == system_of(client.requests[1])
    assert client.requests[0]["tools"] == client.requests[1]["tools"]


async def test_the_follow_up_after_a_missing_tool_call_is_cacheable_too():
    words = SimpleNamespace(content=[SimpleNamespace(type="text", text="bone")], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    client = Client(words, resp())
    llm.set_client_for_tests(client)
    await call()
    assert all(isinstance(system_of(r), list) and system_of(r)[0]["cache_control"] for r in client.requests)


# ---------------- usage records the cached tokens ----------------

async def test_cached_tokens_are_recorded_separately_in_the_global_and_case_rows():
    llm.set_client_for_tests(Client(resp(300, 50, read=2000, write=0), resp(300, 50, read=0, write=400)))
    await call()
    await call()
    row = llm.usage_snapshot("C-1")
    assert row == {"input_tokens": 600, "output_tokens": 100, "calls": 2, "cache_read_tokens": 2000, "cache_write_tokens": 400}
    assert llm.usage_snapshot() == row


async def test_without_caching_the_usage_rows_look_exactly_as_before():
    llm.set_client_for_tests(Client(resp(10, 5), resp(10, 5, read=0, write=0)))
    await call(system=SMALL)
    await call(system=SMALL)
    assert llm.usage_snapshot("C-1") == {"input_tokens": 20, "output_tokens": 10, "calls": 2}


def test_effective_input_weighs_writes_and_reads_like_the_bill_and_accepts_old_rows():
    assert llm.effective_input({"input_tokens": 300, "cache_write_tokens": 400, "cache_read_tokens": 2000}) == 1000
    assert llm.effective_input({"input_tokens": 300, "output_tokens": 5, "calls": 1}) == 300       # a row from before caching
    assert llm.effective_input({}) == 0


# ---------------- the caps count cached tokens at what they cost ----------------

async def test_the_input_cap_counts_cached_tokens_at_their_cost_not_at_zero_and_not_in_full(monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 1_200)
    llm.set_client_for_tests(Client(resp(300, 5, read=2000, write=400), resp()))
    await call(system=SMALL)                                  # effective 300 + 500 + 200 = 1,000 (raw input alone would say 300)
    assert llm.effective_input(llm.usage_snapshot()) == 1000
    with pytest.raises(llm.BudgetExceeded, match="global input cap 1,200: used 1,000"):
        await call(system="s" * 1200)                         # about 340 estimated: 1,000 + 340 > 1,200


async def test_a_run_that_mostly_reads_from_the_cache_is_not_stopped_as_if_it_paid_full_price(monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 1_000)
    llm.set_client_for_tests(Client(*[resp(100, 5, read=1000, write=0) for _ in range(4)]))
    for _ in range(4):                                       # 4 x (100 + 0.1 x 1,000) = 800; counted in full it would be 4,400
        await call(system=SMALL)
    assert llm.effective_input(llm.usage_snapshot()) == 800


async def test_the_per_case_cap_counts_cached_tokens_too(monkeypatch):
    monkeypatch.setattr(config, "CASE_MAX_INPUT_TOKENS", 1_100)
    llm.set_client_for_tests(Client(resp(300, 5, read=2000, write=400), resp()))
    await call(system=SMALL, case_id="C-9")
    with pytest.raises(llm.BudgetExceeded, match="case C-9 input cap 1,100"):
        await call(system="s" * 1200, case_id="C-9")


async def test_the_usage_hook_gets_cost_equivalent_input_so_existing_pricing_is_right(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "usage_hook", lambda model, stage, case, tin, tout, ms: seen.append((model, stage, case, tin, tout)))
    llm.set_client_for_tests(Client(resp(300, 50, read=2000, write=400)))
    await call(system=SMALL)
    assert seen == [(SONNET, "report_x", "C-1", 1000, 50)]


# ---------------- pricing ----------------

def test_a_call_is_priced_with_cache_writes_at_1_25x_and_reads_at_a_tenth():
    # Sonnet 5.5: $2 in, $10 out per million
    usd = costs.call_cost_usd(SONNET, 1000, 100, cache_read=2000, cache_write=400)
    assert usd == pytest.approx((1000 * 2 + 400 * 2 * 1.25 + 2000 * 2 * 0.1 + 100 * 10) / 1e6)
    assert costs.call_cost_usd("some-unknown-model", 1000, 100) is None


def test_a_usage_row_is_priced_the_same_way():
    row = {"input_tokens": 1000, "output_tokens": 100, "calls": 1, "cache_read_tokens": 2000, "cache_write_tokens": 400}
    assert costs.usage_cost_usd(SONNET, row) == pytest.approx(costs.call_cost_usd(SONNET, 1000, 100, 2000, 400))
    assert costs.usage_cost_usd(SONNET, {"input_tokens": 10, "output_tokens": 5, "calls": 1}) == pytest.approx((10 * 2 + 5 * 10) / 1e6)


def test_the_estimate_credits_a_cached_prefix_after_the_first_call():
    plain = costs.estimate([costs.Batch("x", SONNET, 10, 3000, 100, 500)])
    cached = costs.estimate([costs.Batch("x", SONNET, 10, 3000, 100, 500, cached_prefix_tokens=2000)])
    assert plain.input_tokens == 30_000
    assert cached.input_tokens == 10 * 1000 + round(2000 * (1.25 + 0.1 * 9))                  # one write, nine reads
    assert cached.dollars < plain.dollars
    one = costs.estimate([costs.Batch("x", SONNET, 1, 3000, 100, 500, cached_prefix_tokens=2000)])
    assert one.input_tokens == 1000 + round(2000 * 1.25)                                       # a single call only pays the write premium


def test_the_report_mentions_caching_when_a_prefix_is_credited(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    assert "cache" in costs.report([costs.Batch("x", SONNET, 10, 3000, 100, 500, cached_prefix_tokens=2000)]).lower()
    assert "cache" not in costs.report([costs.Batch("x", SONNET, 10, 3000, 100, 500)]).lower()


def test_spent_tokens_in_the_report_are_cost_equivalent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "u.json")
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 10_000)
    (tmp_path / "u.json").write_text('{"global": {"input_tokens": 1000, "output_tokens": 0, "calls": 1, "cache_read_tokens": 50000, '
                                     '"cache_write_tokens": 0}, "cases": {}}')                 # 1,000 + 5,000 effective
    text = costs.report([costs.Batch("x", SONNET, 1, 4500, 10, 20)])
    assert "WARNING" in text and "only 4,000 are left" in text


async def test_the_eval_plan_credits_the_cached_prefix_only_where_it_would_cache(monkeypatch):
    from deadlang.eval import examiner_eval as ev
    from deadlang.specialists.material import QuickExaminer, ThoroughExaminer
    items = [ev.Item("a", "bone", __import__("pathlib").Path("missing.jpg"))]
    strong, quick = ThoroughExaminer(None), QuickExaminer(None)
    strong.model, quick.model = SONNET, HAIKU
    assert ev.plan("thorough", strong, items, 3).cached_prefix_tokens > 500            # the examiner prompt is over 512 tokens
    assert ev.plan("quick", quick, items, 3).cached_prefix_tokens == 0                 # Haiku is never cached
