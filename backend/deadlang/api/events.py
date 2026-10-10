"""EventBus: per-case ordered event log, live fan-out to SSE subscribers, and a replay file on disk."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from deadlang.schemas import Event, EventType

DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "replays" / "runs"


class EventBus:
    def __init__(self, runs_dir: Path | None = DEFAULT_RUNS_DIR):
        """runs_dir=None disables the replay log (used by the eval runner)."""
        self.runs_dir = runs_dir
        self._history: dict[str, list[Event]] = {}
        self._subs: dict[str, list[asyncio.Queue[Event]]] = {}

    def emit(self, case_id: str, type: EventType, payload: dict[str, Any]) -> Event:
        history = self._history.setdefault(case_id, [])
        event = Event(seq=len(history), case_id=case_id, type=type, payload=payload)
        history.append(event)
        if self.runs_dir is not None:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            with (self.runs_dir / f"{case_id}.jsonl").open("a") as f:
                f.write(event.model_dump_json() + "\n")
        for q in self._subs.get(case_id, []):
            q.put_nowait(event)
        return event

    def history(self, case_id: str) -> list[Event]:
        return list(self._history.get(case_id, []))

    def has_case(self, case_id: str) -> bool:
        return case_id in self._history

    async def subscribe(self, case_id: str) -> AsyncIterator[Event]:
        """Yield every event from seq 0, then live ones; stops after case.ended."""
        q: asyncio.Queue[Event] = asyncio.Queue()
        backlog = self.history(case_id)           # snapshot + register with no await in between
        self._subs.setdefault(case_id, []).append(q)
        try:
            for e in backlog:
                yield e
                if e.type == "case.ended":
                    return
            while True:
                e = await q.get()
                yield e
                if e.type == "case.ended":
                    return
        finally:
            self._subs[case_id].remove(q)
