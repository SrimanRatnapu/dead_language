"""The only path to the Anthropic API (contract: plan 01 §4.5): JSON via a tool call, and a hard spend cap.

Request shape depends on the model. Older models (Haiku 4.5, the 4.x family) get the plan's forced
tool_choice and `temperature`. Newer ones (Sonnet 5.5, Opus 5.5, Fable 5.1, Haiku 5.5) return a 400
for forced tool_choice and for non-default temperature, so they get tool_choice "auto" plus a system
line naming the tool, and no temperature. Sonnet 5.5 also gets thinking "between_tools" (its lowest
setting) so thinking does not eat the small max_tokens. Others get effort "low".
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
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

_LEGACY_PREFIXES = ("claude-haiku-4-5", "claude-sonnet-4", "claude-opus-4", "claude-3")

_client: Any = None
_lock = asyncio.Lock()


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


async def _record(case_id: str | None, tokens_in: int, tokens_out: int) -> None:
    async with _lock:   # re-read under the lock so other processes' usage is kept
        data = _load_usage()
        rows = [data["global"]] + ([data["cases"].setdefault(case_id, _empty())] if case_id else [])
        for row in rows:
            row["input_tokens"] += tokens_in
            row["output_tokens"] += tokens_out
            row["calls"] += 1
        _write_usage(data)


def _check_budget(case_id: str | None, est_in: int, max_out: int) -> None:
    data = _load_usage()
    g = data["global"]
    if g["input_tokens"] + est_in > config.MAX_INPUT_TOKENS:
        raise BudgetExceeded(f"global input cap {config.MAX_INPUT_TOKENS} reached")
    if g["output_tokens"] + max_out > config.MAX_OUTPUT_TOKENS:
        raise BudgetExceeded(f"global output cap {config.MAX_OUTPUT_TOKENS} reached")
    if case_id is None:
        return
    c = data["cases"].get(case_id, _empty())
    if c["input_tokens"] + est_in > config.CASE_MAX_INPUT_TOKENS:
        raise BudgetExceeded(f"case {case_id} input cap {config.CASE_MAX_INPUT_TOKENS} reached")
    if c["output_tokens"] + max_out > config.CASE_MAX_OUTPUT_TOKENS:
        raise BudgetExceeded(f"case {case_id} output cap {config.CASE_MAX_OUTPUT_TOKENS} reached")


# ---------------- request building ----------------

def estimate_input_tokens(system: str, user: str, images: int = 0) -> int:
    """The estimate the budget check uses before every call (also used by the cost reports)."""
    return int(len(system + user) / CHARS_PER_TOKEN) + TOKENS_PER_IMAGE * images


def _is_legacy(model: str) -> bool:
    return model.startswith(_LEGACY_PREFIXES)


def _request(model: str, system: str, content: Any, schema_name: str, schema: dict,
             max_tokens: int, temperature: float) -> dict:
    tool = {"name": schema_name, "description": "Return your answer by calling this tool.",
            "input_schema": schema}
    req: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "tools": [tool],
                           "messages": [{"role": "user", "content": content}]}
    if _is_legacy(model):
        req.update(system=system, temperature=temperature,
                   tool_choice={"type": "tool", "name": schema_name})
        return req
    req["system"] = f"{system}\n\nReturn your answer by calling the `{schema_name}` tool exactly once."
    req["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
    if model.startswith("claude-sonnet-5-5"):
        req["thinking"] = {"type": "between_tools"}
    else:
        req["output_config"] = {"effort": "low"}
    return req


def _encode_image(path: Path) -> dict:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):   # includes APITimeoutError
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in RETRY_STATUSES


async def _call(req: dict, schema_name: str, case_id: str | None, est_in: int) -> dict:
    _check_budget(case_id, est_in, req["max_tokens"])
    client = _get_client()
    start = time.perf_counter()
    try:
        resp = await client.messages.create(**req)
    except Exception as exc:
        if not _retryable(exc):
            raise
        log.warning("llm retry after %s (%s, %s)", type(exc).__name__, req["model"], schema_name)
        await asyncio.sleep(RETRY_SLEEP)
        resp = await client.messages.create(**req)
    ms = (time.perf_counter() - start) * 1000
    tokens_in, tokens_out = resp.usage.input_tokens, resp.usage.output_tokens
    await _record(case_id, tokens_in, tokens_out)
    log.info("llm model=%s schema=%s case=%s in=%d out=%d ms=%.0f",
             req["model"], schema_name, case_id, tokens_in, tokens_out, ms)
    for block in resp.content:
        if block.type == "tool_use" and block.name == schema_name:
            return dict(block.input)
    raise ValueError("no tool output")


async def call_json(*, model: str, system: str, user: str, schema_name: str,
                    schema: dict, case_id: str | None, max_tokens: int = 2000,
                    temperature: float = 0.0) -> dict:
    req = _request(model, system, user, schema_name, schema, max_tokens, temperature)
    est_in = estimate_input_tokens(system, user)
    return await _call(req, schema_name, case_id, est_in)


async def call_vision_json(*, model: str, system: str, user: str, image_paths: list[Path],
                           schema_name: str, schema: dict, case_id: str | None,
                           max_tokens: int = 1500, temperature: float = 0.0) -> dict:
    content = [_encode_image(Path(p)) for p in image_paths] + [{"type": "text", "text": user}]
    req = _request(model, system, content, schema_name, schema, max_tokens, temperature)
    est_in = estimate_input_tokens(system, user, images=len(image_paths))
    return await _call(req, schema_name, case_id, est_in)
