"""The only path to the Anthropic API (contract: plan 01 §4.5): JSON via a tool call, and a hard spend cap.

Request shape depends on the model. Older models (Haiku 4.5, the 4.x family) get the plan's forced
tool_choice and `temperature`. Newer ones (Sonnet 5.5, Opus 5.5, Fable 5.1, Haiku 5.5) return a 400
for forced tool_choice and for non-default temperature, so they get tool_choice "auto" plus a system
line naming the tool, and no temperature. Sonnet 5.5 also gets thinking "between_tools" (its lowest
setting) so thinking does not eat the small max_tokens. Others get effort "low".

Because "auto" does not guarantee a tool call, a reply without one gets exactly one follow-up asking for it.

Spend caps are enforced with reservations: before a call, its estimated input and its max_tokens are added
to an in-memory pending total (checked together with the usage file), so calls running at the same time
cannot together overshoot a cap. The reservation is replaced by actual usage when the call ends, however it ends.
The pending total is per process; the usage file is what processes share.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from PIL import Image

from deadlang import config, fileio

log = logging.getLogger("deadlang.llm")

MAX_IMAGE_SIDE = 1568
TOKENS_PER_IMAGE = 1600
CHARS_PER_TOKEN = 3.5
RETRY_STATUSES = {429, 500, 529}
RETRY_SLEEP = 3.0
_IMAGE_CACHE_SIZE = 16

_LEGACY_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-4", "claude-opus-4", "claude-3")

_client: Any = None
_lock_for: tuple[Any, asyncio.Lock] | None = None     # (event loop, its lock); a lock belongs to one loop
_pending: dict[str, Any] = {"in": 0, "out": 0, "cases": {}}    # tokens reserved by calls in flight


# Set by the API to persist every call (model, schema_name, case_id, tokens_in, tokens_out, ms).
usage_hook: Any = None


class BudgetExceeded(Exception):
    """A global or per-case token cap would be exceeded by this call."""


def set_client_for_tests(fake: Any) -> None:
    global _client
    _client = fake


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(max_retries=0)   # retries are ours: at most 1
    return _client


def _get_lock() -> asyncio.Lock:
    global _lock_for
    loop = asyncio.get_running_loop()
    if _lock_for is None or _lock_for[0] is not loop:
        _lock_for = (loop, asyncio.Lock())
    return _lock_for[1]


# ---------------- usage file ----------------

def _empty() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "calls": 0}


def _load_usage() -> dict:
    try:
        data = json.loads(Path(config.USAGE_FILE).read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("global", _empty())
    data.setdefault("cases", {})
    return data


def _write_usage(data: dict) -> None:
    fileio.write_json_atomic(config.USAGE_FILE, data)


def usage_snapshot(case_id: str | None = None) -> dict:
    data = _load_usage()
    if case_id is None:
        return dict(data["global"])
    return dict(data["cases"].get(case_id, _empty()))


# ---------------- budget: check, reserve, record ----------------

@dataclass
class _Reservation:
    case_id: str | None
    tokens_in: int
    tokens_out: int
    active: bool = True


def _check_budget(case_id: str | None, est_in: int, max_out: int) -> None:
    """Raise BudgetExceeded if this call, on top of usage so far and calls in flight, would pass a cap."""
    data = _load_usage()
    g = data["global"]
    if g["input_tokens"] + _pending["in"] + est_in > config.MAX_INPUT_TOKENS:
        raise BudgetExceeded(f"global input cap {config.MAX_INPUT_TOKENS} reached")
    if g["output_tokens"] + _pending["out"] + max_out > config.MAX_OUTPUT_TOKENS:
        raise BudgetExceeded(f"global output cap {config.MAX_OUTPUT_TOKENS} reached")
    if case_id is None:
        return
    c = data["cases"].get(case_id, _empty())
    p_in, p_out = _pending["cases"].get(case_id, (0, 0))
    if c["input_tokens"] + p_in + est_in > config.CASE_MAX_INPUT_TOKENS:
        raise BudgetExceeded(f"case {case_id} input cap {config.CASE_MAX_INPUT_TOKENS} reached")
    if c["output_tokens"] + p_out + max_out > config.CASE_MAX_OUTPUT_TOKENS:
        raise BudgetExceeded(f"case {case_id} output cap {config.CASE_MAX_OUTPUT_TOKENS} reached")


async def _reserve(case_id: str | None, est_in: int, max_out: int) -> _Reservation:
    async with _get_lock():
        _check_budget(case_id, est_in, max_out)
        res = _Reservation(case_id, est_in, max_out)
        _pending["in"] += est_in
        _pending["out"] += max_out
        if case_id:
            p_in, p_out = _pending["cases"].get(case_id, (0, 0))
            _pending["cases"][case_id] = (p_in + est_in, p_out + max_out)
    return res


def _release(res: _Reservation) -> None:
    """Give a reservation back. Synchronous and idempotent, so it is safe in a finally, even when cancelled."""
    if not res.active:
        return
    res.active = False
    _pending["in"] -= res.tokens_in
    _pending["out"] -= res.tokens_out
    if res.case_id:
        p_in, p_out = _pending["cases"].get(res.case_id, (0, 0))
        left = (p_in - res.tokens_in, p_out - res.tokens_out)
        if left == (0, 0):
            _pending["cases"].pop(res.case_id, None)
        else:
            _pending["cases"][res.case_id] = left


def _record_now(res: _Reservation, tokens_in: int, tokens_out: int) -> None:
    """Add usage to the file and release the reservation. Never awaits, so nothing can interleave with it."""
    data = _load_usage()   # re-read every time so other processes' usage is kept
    rows = [data["global"]] + ([data["cases"].setdefault(res.case_id, _empty())] if res.case_id else [])
    for row in rows:
        row["input_tokens"] += tokens_in
        row["output_tokens"] += tokens_out
        row["calls"] += 1
    _write_usage(data)
    _release(res)


async def _record(res: _Reservation, tokens_in: int, tokens_out: int) -> None:
    async with _get_lock():
        _record_now(res, tokens_in, tokens_out)


# ---------------- request building ----------------

def estimate_input_tokens(system: str, user: str, images: int = 0, schema: dict | None = None) -> int:
    """The estimate the budget check uses before every call (also used by the cost reports)."""
    total = int(len(system + user) / CHARS_PER_TOKEN) + TOKENS_PER_IMAGE * images
    if schema is not None:
        total += int(len(json.dumps(schema)) / CHARS_PER_TOKEN)      # the tool definition is sent as input too
    return total


def _is_legacy(model: str) -> bool:
    return model.startswith(_LEGACY_PREFIXES)


def _request(model: str, system: str, content: Any, schema_name: str, schema: dict,
             max_tokens: int, temperature: float) -> dict:
    tool = {"name": schema_name, "description": "Return your answer by calling this tool.",
            "input_schema": schema}
    req: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "tools": [tool],
                           "messages": [{"role": "user", "content": content}]}
    if _is_legacy(model):
        req.update(system=system,   # anthropic SDK 1.x has no temperature argument
                   tool_choice={"type": "tool", "name": schema_name})
        return req
    req["system"] = f"{system}\n\nReturn your answer by calling the `{schema_name}` tool exactly once."
    req["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
    if model.startswith("claude-sonnet-5-5"):
        req["thinking"] = {"type": "between_tools"}
    else:
        req["output_config"] = {"effort": "low"}
    return req


# ---------------- images: encode off the event loop, once per file version ----------------

_image_cache: OrderedDict[tuple[str, int], dict] = OrderedDict()       # (path, mtime_ns) -> image block, LRU
_image_inflight: dict[tuple[str, int], asyncio.Future] = {}            # encodes already running, shared


def _encode_image(path: Path) -> dict:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


async def _encoded(path: Path) -> dict:
    key = (str(path), path.stat().st_mtime_ns)      # a changed file is a new key; a missing one raises here
    hit = _image_cache.get(key)
    if hit is not None:
        _image_cache.move_to_end(key)
        return hit
    task = _image_inflight.get(key)
    if task is None:                                # two calls for the same photo at once share one encode
        task = asyncio.ensure_future(asyncio.to_thread(_encode_image, path))
        _image_inflight[key] = task
        task.add_done_callback(lambda _t: _image_inflight.pop(key, None))
    block = await asyncio.shield(task)              # one caller being cancelled must not cancel the others
    _image_cache[key] = block
    _image_cache.move_to_end(key)
    while len(_image_cache) > _IMAGE_CACHE_SIZE:
        _image_cache.popitem(last=False)
    return block


# ---------------- the call ----------------

def _retryable(exc: Exception) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):   # includes APITimeoutError
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in RETRY_STATUSES


async def _create(req: dict, schema_name: str) -> Any:
    client = _get_client()
    try:
        return await client.messages.create(**req)
    except Exception as exc:
        if not _retryable(exc):
            raise
        log.warning("llm retry after %s (%s, %s)", type(exc).__name__, req["model"], schema_name)
        await asyncio.sleep(RETRY_SLEEP)
        return await client.messages.create(**req)


async def _attempt(req: dict, schema_name: str, case_id: str | None, est_in: int) -> tuple[dict | None, Any]:
    """One request, budget-reserved and recorded. Returns (tool input or None, the response)."""
    res = await _reserve(case_id, est_in, req["max_tokens"])
    resp = None
    try:
        start = time.perf_counter()
        resp = await _create(req, schema_name)
        ms = (time.perf_counter() - start) * 1000
        tokens_in, tokens_out = resp.usage.input_tokens, resp.usage.output_tokens
        await _record(res, tokens_in, tokens_out)
    except (asyncio.CancelledError, anthropic.APITimeoutError):
        # The request was (or may have been) sent and then cut off, e.g. by the transport's timeout. It may
        # still be billed, so count it as spent rather than letting it vanish: the real usage if the response
        # had already arrived, otherwise the reserved estimate (conservative).
        if res.active:
            spent = (resp.usage.input_tokens, resp.usage.output_tokens) if resp is not None                 else (res.tokens_in, res.tokens_out)
            try:
                _record_now(res, *spent)
            except OSError:
                log.exception("llm: could not record usage for a cut-off call")
        raise
    finally:
        _release(res)                                   # no-op once recorded; covers every other error
    log.info("llm model=%s schema=%s case=%s in=%d out=%d ms=%.0f",
             req["model"], schema_name, case_id, tokens_in, tokens_out, ms)
    if usage_hook:
        usage_hook(req["model"], schema_name, case_id, tokens_in, tokens_out, ms)
    for block in resp.content:
        if block.type == "tool_use" and block.name == schema_name:
            return _unstringify(dict(block.input)), resp
    return None, resp


def _unstringify(out: dict) -> dict:
    """The model sometimes returns a nested object/array as a JSON string; decode those."""
    for k, v in out.items():
        if isinstance(v, str) and v.lstrip()[:1] in ("{", "["):
            try:
                out[k] = json.loads(v)
            except ValueError:
                pass
    return out


async def _call(req: dict, schema_name: str, case_id: str | None, est_in: int) -> dict:
    out, resp = await _attempt(req, schema_name, case_id, est_in)
    if out is not None:
        return out
    if getattr(resp, "stop_reason", None) == "refusal":
        raise ValueError("no tool output (the model declined to answer)")    # asking again would just be refused again
    # The model answered in words instead of calling the tool (possible when tool_choice is "auto").
    # Ask once more, with its reply in the conversation; this call is budget-checked and recorded too.
    nudge = f"Call the {schema_name} tool now with your answer."
    log.warning("llm: no %s tool call from %s; asking once more", schema_name, req["model"])
    echoed = [b for b in resp.content if b.type != "tool_use"]
    messages = list(req["messages"]) + ([{"role": "assistant", "content": echoed}] if echoed else [])
    messages.append({"role": "user", "content": nudge})
    est_again = est_in + resp.usage.output_tokens + int(len(nudge) / CHARS_PER_TOKEN)
    out, _ = await _attempt({**req, "messages": messages}, schema_name, case_id, est_again)
    if out is None:
        raise ValueError("no tool output")
    return out


async def call_json(*, model: str, system: str, user: str, schema_name: str,
                    schema: dict, case_id: str | None, max_tokens: int = 2000,
                    temperature: float = 0.0) -> dict:
    req = _request(model, system, user, schema_name, schema, max_tokens, temperature)
    est_in = estimate_input_tokens(system, user, schema=schema)
    return await _call(req, schema_name, case_id, est_in)


async def call_vision_json(*, model: str, system: str, user: str, image_paths: list[Path],
                           schema_name: str, schema: dict, case_id: str | None,
                           max_tokens: int = 1500, temperature: float = 0.0) -> dict:
    blocks = await asyncio.gather(*(_encoded(Path(p)) for p in image_paths))
    content = [*blocks, {"type": "text", "text": user}]
    req = _request(model, system, content, schema_name, schema, max_tokens, temperature)
    est_in = estimate_input_tokens(system, user, images=len(image_paths), schema=schema)
    return await _call(req, schema_name, case_id, est_in)
