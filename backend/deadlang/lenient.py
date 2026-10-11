"""Lenient reading of a model's tool input against its JSON schema.

A model sometimes sends an object or a list as a JSON string ('{"target_agent": ...}'), wrapped in a code fence, or
writes "null" for an optional object. `coerce` decodes those, at any depth, before pydantic validates. It only
touches a string where the schema expects an object or an array (and not a string), so real text is never altered.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)
_BAD = object()


def _resolve(schema: dict, root: dict) -> dict:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 10:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = {**root.get("$defs", {}).get(name, {}), **{k: v for k, v in schema.items() if k != "$ref"}}
        seen += 1
    return schema


def _members(schema: dict, root: dict) -> list[dict]:
    s = _resolve(schema, root)
    return [_resolve(m, root) for m in s["anyOf"]] if "anyOf" in s else [s]


def _kinds(schema: dict, root: dict) -> set[str]:
    kinds: set[str] = set()
    for m in _members(schema, root):
        t = m.get("type")
        kinds |= set(t) if isinstance(t, list) else ({t} if t else set())
        if "properties" in m:
            kinds.add("object")
    return kinds


def _shape(schema: dict, root: dict, kind: str) -> dict:
    for m in _members(schema, root):
        t = m.get("type")
        if t == kind or (kind == "object" and "properties" in m):
            return m
    return {}


def _parse(text: str, nullable: bool) -> Any:
    t = text.strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1).strip()
    if nullable and t.lower() in ("null", "none", ""):
        return None
    try:
        return json.loads(t)
    except ValueError:
        return _BAD


def coerce(value: Any, schema: dict, root: dict | None = None) -> Any:
    """A copy of `value` with JSON-in-a-string decoded wherever `schema` expects an object or an array."""
    root = root if root is not None else schema
    return _coerce(copy.deepcopy(value), schema, root)


def _coerce(value: Any, schema: dict, root: dict) -> Any:
    kinds = _kinds(schema, root)
    if isinstance(value, str) and kinds & {"object", "array"} and "string" not in kinds:
        parsed = _parse(value, "null" in kinds)
        if parsed is not _BAD and (parsed is None or isinstance(parsed, (dict, list))):
            value = parsed
    if isinstance(value, dict):
        props = _shape(schema, root, "object").get("properties", {})
        return {k: _coerce(v, props[k], root) if k in props else v for k, v in value.items()}
    if isinstance(value, list):
        items = _shape(schema, root, "array").get("items")
        return [_coerce(v, items, root) for v in value] if items else value
    return value
