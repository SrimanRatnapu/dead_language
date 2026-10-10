import base64
import io
import json
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


async def test_no_tool_output_raises_without_retry():
    fake = FakeClient(_resp(None))
    llm.set_client_for_tests(fake)
    with pytest.raises(ValueError, match="no tool output"):
        await _call()
    assert len(fake.requests) == 1


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
