import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from PIL import Image

from deadlang import config, llm

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
LEGACY = "claude-haiku-4-5-20251001"


def _resp(inp=None, tokens_in=10, tokens_out=5, name="report_x"):
    blocks = [] if inp is None else [SimpleNamespace(type="tool_use", name=name, input=inp)]
    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out))


def _status_error(cls, code):
    response = httpx2.Response(code, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls("boom", response=response, body=None)


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.messages = self

    async def create(self, **req):
        self.requests.append(req)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(llm, "RETRY_SLEEP", 0)
    yield
    llm.set_client_for_tests(None)


async def _call(case_id="C-1", model=LEGACY, **kw):
    return await llm.call_json(model=model, system="sys", user="hello", schema_name="report_x",
                               schema=SCHEMA, case_id=case_id, **kw)


async def test_returns_tool_input_and_forces_tool_on_legacy_model():
    fake = FakeClient(_resp({"x": 3}))
    llm.set_client_for_tests(fake)
    assert await _call() == {"x": 3}
    req = fake.requests[0]
    assert req["tool_choice"] == {"type": "tool", "name": "report_x"}
    assert req["temperature"] == 0.0


async def test_new_models_use_auto_tool_choice_and_no_temperature():
    fake = FakeClient(_resp({"x": 1}), _resp({"x": 2}))
    llm.set_client_for_tests(fake)
    await _call(model="claude-sonnet-5-5", temperature=0.2)
    await _call(model="claude-opus-5-5")
    sonnet, opus = fake.requests
    for req in (sonnet, opus):
        assert req["tool_choice"]["type"] == "auto"
        assert "temperature" not in req
        assert "report_x" in req["system"]
    assert sonnet["thinking"] == {"type": "between_tools"}
    assert opus["output_config"] == {"effort": "low"}


async def test_global_cap_raises_before_calling_api(monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 100)
    fake = FakeClient()
    llm.set_client_for_tests(fake)
    with pytest.raises(llm.BudgetExceeded):
        await llm.call_json(model=LEGACY, system="s" * 1000, user="u", schema_name="report_x",
                            schema=SCHEMA, case_id=None)
    assert fake.requests == []


async def test_case_cap_is_independent_of_global(monkeypatch):
    monkeypatch.setattr(config, "CASE_MAX_OUTPUT_TOKENS", 30)
    llm.set_client_for_tests(FakeClient(_resp({"x": 1}, tokens_out=25), _resp({"x": 2})))
    await _call(case_id="C-1", max_tokens=5)
    with pytest.raises(llm.BudgetExceeded, match="C-1"):
        await _call(case_id="C-1", max_tokens=10)
    assert await _call(case_id="C-2", max_tokens=10) == {"x": 2}


async def test_usage_accumulates_across_calls():
    llm.set_client_for_tests(FakeClient(_resp({"x": 1}, 10, 5), _resp({"x": 2}, 7, 3)))
    await _call(case_id="C-1")
    await _call(case_id=None)
    assert llm.usage_snapshot() == {"input_tokens": 17, "output_tokens": 8, "calls": 2}
    assert llm.usage_snapshot("C-1") == {"input_tokens": 10, "output_tokens": 5, "calls": 1}
    assert llm.usage_snapshot("C-unknown")["calls"] == 0


async def test_retries_once_on_529_then_succeeds():
    fake = FakeClient(_status_error(anthropic.OverloadedError, 529), _resp({"x": 9}))
    llm.set_client_for_tests(fake)
    assert await _call() == {"x": 9}
    assert len(fake.requests) == 2


async def test_second_failure_propagates():
    fake = FakeClient(_status_error(anthropic.RateLimitError, 429), _status_error(anthropic.RateLimitError, 429))
    llm.set_client_for_tests(fake)
    with pytest.raises(anthropic.RateLimitError):
        await _call()
    assert len(fake.requests) == 2


async def test_400_is_not_retried():
    fake = FakeClient(_status_error(anthropic.BadRequestError, 400), _resp({"x": 1}))
    llm.set_client_for_tests(fake)
    with pytest.raises(anthropic.BadRequestError):
        await _call()
    assert len(fake.requests) == 1


async def test_vision_downscales_and_puts_images_before_text(tmp_path):
    img = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "white").save(img)
    fake = FakeClient(_resp({"x": 1}))
    llm.set_client_for_tests(fake)
    await llm.call_vision_json(model=LEGACY, system="s", user="look", image_paths=[img],
                               schema_name="report_x", schema=SCHEMA, case_id=None)
    content = fake.requests[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    decoded = Image.open(io.BytesIO(base64.b64decode(content[0]["source"]["data"])))
    assert max(decoded.size) <= llm.MAX_IMAGE_SIDE


def test_estimate_input_tokens_matches_what_the_budget_check_uses():
    assert llm.estimate_input_tokens("a" * 350, "b" * 350) == 200
    assert llm.estimate_input_tokens("a" * 350, "b" * 350, images=2) == 200 + 2 * llm.TOKENS_PER_IMAGE


def test_write_json_atomic_replaces_the_file_and_leaves_no_temp(tmp_path):
    from deadlang import fileio
    target = tmp_path / "sub" / "out.json"
    fileio.write_json_atomic(target, {"a": 1})
    fileio.write_json_atomic(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in target.parent.iterdir()] == ["out.json"]


# ---------------- robustness: tool nudge, budget reservation, schema estimate, image cache ----------------

import asyncio
import os
import threading


def _text_only(text="I think it is bone."):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=7))


async def test_missing_tool_output_gets_one_nudge_then_succeeds():
    fake = FakeClient(_text_only(), _resp({"x": 5}, 11, 4))
    llm.set_client_for_tests(fake)

    assert await _call(model="claude-sonnet-5-5") == {"x": 5}

    assert len(fake.requests) == 2
    first, second = fake.requests
    assert len(first["messages"]) == 1
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"][0].text == "I think it is bone."      # the assistant's reply is echoed
    assert second["messages"][2]["content"] == "Call the report_x tool now with your answer."
    assert {k: v for k, v in second.items() if k != "messages"} == {k: v for k, v in first.items() if k != "messages"}
    assert llm.usage_snapshot("C-1") == {"input_tokens": 21, "output_tokens": 11, "calls": 2}   # both calls recorded


async def test_still_no_tool_output_after_the_nudge_raises_value_error():
    fake = FakeClient(_text_only(), _text_only("still words"))
    llm.set_client_for_tests(fake)
    with pytest.raises(ValueError, match="no tool output"):
        await _call(model="claude-sonnet-5-5")
    assert len(fake.requests) == 2                                   # one nudge, never more
    assert llm.usage_snapshot("C-1")["calls"] == 2


async def test_empty_first_reply_is_nudged_without_an_empty_assistant_turn():
    fake = FakeClient(_resp(None), _resp({"x": 1}))
    llm.set_client_for_tests(fake)
    assert await _call(model="claude-sonnet-5-5") == {"x": 1}
    assert [m["role"] for m in fake.requests[1]["messages"]] == ["user", "user"]


async def test_the_nudge_is_budget_checked_first(monkeypatch):
    monkeypatch.setattr(config, "CASE_MAX_OUTPUT_TOKENS", 105)
    fake = FakeClient(_text_only(), _resp({"x": 1}))
    llm.set_client_for_tests(fake)
    with pytest.raises(llm.BudgetExceeded):
        await _call(max_tokens=100)          # first call: 100 fits; then 7 used, so the nudge needs 7 + 100 > 105
    assert len(fake.requests) == 1


class SlowClient(FakeClient):
    async def create(self, **req):
        await asyncio.sleep(0.05)            # let the other calls start while this one is in flight
        return await super().create(**req)


async def test_concurrent_calls_cannot_exceed_a_tiny_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 250)
    fake = SlowClient(*[_resp({"x": i}, 10, 5) for i in range(5)])
    llm.set_client_for_tests(fake)

    results = await asyncio.gather(*[_call(case_id=None, max_tokens=100) for _ in range(5)], return_exceptions=True)

    ok = [r for r in results if isinstance(r, dict)]
    blocked = [r for r in results if isinstance(r, llm.BudgetExceeded)]
    assert len(ok) == 2 and len(blocked) == 3        # 2 x 100 reserved fits in 250; a third does not
    assert len(fake.requests) == 2
    assert llm._pending["in"] == 0 and llm._pending["out"] == 0 and llm._pending["cases"] == {}


async def test_per_case_cap_also_counts_calls_in_flight(monkeypatch):
    monkeypatch.setattr(config, "CASE_MAX_INPUT_TOKENS", 2_300)
    fake = SlowClient(*[_resp({"x": i}) for i in range(3)])
    llm.set_client_for_tests(fake)
    big = "u" * 3_500                                # about 1,025 estimated input tokens per call (with schema)

    results = await asyncio.gather(*[
        llm.call_json(model=LEGACY, system="", user=big, schema_name="report_x", schema=SCHEMA, case_id="C-9")
        for _ in range(3)], return_exceptions=True)

    assert sum(isinstance(r, dict) for r in results) == 2
    assert sum(isinstance(r, llm.BudgetExceeded) for r in results) == 1


async def test_reservation_is_released_when_the_call_fails(monkeypatch):
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 150)
    fake = FakeClient(_status_error(anthropic.BadRequestError, 400), _resp({"x": 1}))
    llm.set_client_for_tests(fake)
    with pytest.raises(anthropic.BadRequestError):
        await _call(max_tokens=100)
    assert llm._pending["out"] == 0
    assert await _call(max_tokens=100) == {"x": 1}   # would be refused if the failed call still held 100


async def test_reservation_is_released_when_the_call_is_cancelled(monkeypatch):
    monkeypatch.setattr(config, "MAX_OUTPUT_TOKENS", 150)
    llm.set_client_for_tests(SlowClient(_resp({"x": 1})))
    task = asyncio.ensure_future(_call(max_tokens=100))
    await asyncio.sleep(0.01)
    assert llm._pending["out"] == 100
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert llm._pending["out"] == 0


def test_schema_size_raises_the_estimate():
    base = llm.estimate_input_tokens("a" * 350, "b" * 350)
    with_schema = llm.estimate_input_tokens("a" * 350, "b" * 350, schema=SCHEMA)
    assert with_schema - base == int(len(json.dumps(SCHEMA)) / llm.CHARS_PER_TOKEN)
    big = {"type": "object", "properties": {f"field_{i}": {"type": "string"} for i in range(100)}}
    assert llm.estimate_input_tokens("", "", schema=big) > with_schema - base
    assert llm.estimate_input_tokens("a" * 350, "b" * 350, images=1) == base + llm.TOKENS_PER_IMAGE   # unchanged


async def test_the_budget_check_uses_the_schema_in_its_estimate(monkeypatch):
    big = {"type": "object", "properties": {f"field_{i}": {"type": "string"} for i in range(200)}}
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 500)           # prompt alone is tiny; the schema is ~1,000 tokens
    fake = FakeClient(_resp({"x": 1}))
    llm.set_client_for_tests(fake)
    with pytest.raises(llm.BudgetExceeded):
        await llm.call_json(model=LEGACY, system="s", user="u", schema_name="report_x", schema=big, case_id=None)
    assert fake.requests == []


@pytest.fixture
def encoder(monkeypatch):
    """Counts real encodes and the thread they ran on."""
    llm._image_cache.clear()
    seen = {"paths": [], "threads": set()}
    real = llm._encode_image

    def counting(path):
        seen["paths"].append(Path(path).name)
        seen["threads"].add(threading.current_thread())
        return real(path)

    monkeypatch.setattr(llm, "_encode_image", counting)
    yield seen
    llm._image_cache.clear()


def _png(path, size=(40, 20)):
    Image.new("RGB", size, "white").save(path)
    return path


async def _vision(path_list):
    return await llm.call_vision_json(model=LEGACY, system="s", user="look", image_paths=path_list,
                                      schema_name="report_x", schema=SCHEMA, case_id=None)


async def test_the_same_image_is_encoded_once_even_for_two_simultaneous_calls(tmp_path, encoder):
    img = _png(tmp_path / "a.png")
    llm.set_client_for_tests(FakeClient(_resp({"x": 1}), _resp({"x": 2}), _resp({"x": 3})))

    await asyncio.gather(_vision([img]), _vision([img]))      # what the thorough examiner does
    await _vision([img])                                       # later: served from the cache

    assert encoder["paths"] == ["a.png"]
    assert threading.main_thread() not in encoder["threads"]   # encoding ran off the event loop


async def test_a_changed_file_is_encoded_again(tmp_path, encoder):
    img = _png(tmp_path / "a.png")
    llm.set_client_for_tests(FakeClient(_resp({"x": 1}), _resp({"x": 2})))
    await _vision([img])
    _png(img, size=(80, 40))
    st = img.stat()
    os.utime(img, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # a clearly newer modification time
    await _vision([img])
    assert encoder["paths"] == ["a.png", "a.png"]


async def test_the_image_cache_is_a_small_lru(tmp_path, encoder, monkeypatch):
    monkeypatch.setattr(llm, "_IMAGE_CACHE_SIZE", 2)
    a, b, c = (_png(tmp_path / f"{n}.png") for n in "abc")
    llm.set_client_for_tests(FakeClient(*[_resp({"x": i}) for i in range(6)]))
    for img in (a, b, a, c):         # a is touched again, so b is the least recently used when c arrives
        await _vision([img])
    assert encoder["paths"] == ["a.png", "b.png", "c.png"]
    await _vision([a])               # still cached
    assert encoder["paths"] == ["a.png", "b.png", "c.png"]
    await _vision([b])               # was evicted
    assert encoder["paths"] == ["a.png", "b.png", "c.png", "b.png"]
    assert len(llm._image_cache) == 2


async def test_a_missing_image_file_is_an_error_and_holds_no_budget(tmp_path, encoder):
    llm.set_client_for_tests(FakeClient())
    with pytest.raises(FileNotFoundError):
        await _vision([tmp_path / "nope.png"])
    assert llm._pending["in"] == 0
