"""Evidence board: the shared, append-only list of numbered facts for one case."""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

from deadlang.schemas import Evidence, EvidenceDraft, Requester

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_from_text(text: str) -> list[float]:
    out: list[float] = []
    for raw in NUMBER_RE.findall(text):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            pass
    return out


def _walk(obj: Any) -> Iterator[Any]:
    """Yield every scalar (str / int / float) inside a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(k)
            yield from _walk(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _walk(v)
    elif isinstance(obj, bool) or obj is None:
        return
    else:
        yield obj


class EvidenceBoard:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self._items: list[Evidence] = []

    def add(self, draft: EvidenceDraft, requested_by: Requester) -> Evidence:
        ev = Evidence(**draft.model_dump(), id=f"E{len(self._items)}", case_id=self.case_id,
                      requested_by=requested_by)
        self._items.append(ev)
        return ev

    def get(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self._items if e.id == evidence_id), None)

    def all(self) -> list[Evidence]:
        return list(self._items)

    def ids(self) -> set[str]:
        return {e.id for e in self._items}

    def count(self) -> int:
        return len(self._items)

    def added_since(self, n: int) -> list[Evidence]:
        """Items added after the board held `n` items."""
        return self._items[n:]

    def _select(self, evidence_ids: list[str]) -> list[Evidence]:
        return [e for i in evidence_ids if (e := self.get(i))]

    def numbers_in(self, evidence_ids: list[str]) -> list[float]:
        out: list[float] = []
        for e in self._select(evidence_ids):
            out += numbers_from_text(e.summary)
            for v in _walk(e.data):
                if isinstance(v, str):
                    out += numbers_from_text(v)
                elif isinstance(v, (int, float)):
                    out.append(float(v))
        return out

    def text_in(self, evidence_ids: list[str]) -> str:
        parts: list[str] = []
        for e in self._select(evidence_ids):
            parts.append(e.summary)
            parts += [v for v in _walk(e.data) if isinstance(v, str)]
        return " ".join(parts).lower()

    def render_for_prompt(self) -> str:
        return render_evidence(self._items)


def render_evidence(items: list[Evidence]) -> str:
    """Prompt block per item. Takes plain Evidence so agents can render a DeliberationTurn's list."""
    blocks = []
    for e in items:
        data = json.dumps(e.data, separators=(",", ":"), default=str)
        if len(data) > 1200:
            data = data[:1200] + "…"
        lines = [f"{e.id} · {e.capability} · by {e.specialist_name} ({e.produced_by}) · requested by {e.requested_by}",
                 f"  Summary: {e.summary}",
                 f"  Data: {data}"]
        if e.confidence is not None:
            lines.append(f"  Model confidence: {e.confidence}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
