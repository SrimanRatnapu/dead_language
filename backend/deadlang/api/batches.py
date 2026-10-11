"""Batch queue: submit many listings, watch each go queued -> triaging -> (screened_out | deliberating) -> done | error.

Contract: docs/plans/v2/00-overview-and-contracts.md section 4.2.
ponytail: in-process asyncio queue; swap Batches for Redis/SQS behind submit()/events() if we outgrow one API process.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from deadlang.schemas import now_iso

TERMINAL = {"screened_out", "done", "error"}
# worker(item, set_status): drives one item; set_status(status=..., triage=..., outcome=..., case_id=..., error=...)
Worker = Callable[[dict[str, Any], Callable[..., None]], Awaitable[None]]


class Batches:
    def __init__(self, worker: Worker, limit: int = 4, on_event: Callable[[str, dict], None] | None = None, first_id: int = 1):
        self.worker = worker
        self._first = first_id
        self.on_event = on_event
        self._sem = asyncio.Semaphore(limit)
        self._batches: dict[str, dict[str, Any]] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._tasks: set[asyncio.Task] = set()   # strong refs so running items are not garbage collected

    def submit(self, source: str, listing_ids: list[str], source_mode: str) -> dict[str, Any]:
        bid = f"B-{self._first + len(self._batches):04d}"
        items = [{"listing_id": i, "case_id": None, "status": "queued", "triage": None, "outcome": None, "error": None}
                 for i in dict.fromkeys(listing_ids)]
        batch = {"batch_id": bid, "source": source, "source_mode": source_mode, "created_at": now_iso(), "items": items,
                 "_events": [], "_finished": not items}
        self._batches[bid] = batch
        for it in items:
            self._event(batch, it)
            task = asyncio.create_task(self._run(batch, it))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return self.view(bid)

    def get(self, bid: str) -> dict[str, Any] | None:
        return self._batches.get(bid)

    def view(self, bid: str) -> dict[str, Any]:
        return {k: v for k, v in self._batches[bid].items() if not k.startswith("_")}

    def _event(self, batch: dict, item: dict) -> None:
        e = {"type": "batch.item", "listing_id": item["listing_id"], "case_id": item["case_id"],
             "status": item["status"], "at": now_iso()}
        if item["outcome"]:
            e["outcome"] = item["outcome"]
        batch["_events"].append(e)
        if self.on_event:
            self.on_event(batch["batch_id"], item)
        for q in self._subs.get(batch["batch_id"], []):
            q.put_nowait(e)

    def _update(self, batch: dict, item: dict, **fields: Any) -> None:
        item.update(fields)
        self._event(batch, item)
        if not batch["_finished"] and all(i["status"] in TERMINAL for i in batch["items"]):
            batch["_finished"] = True
            for q in self._subs.get(batch["batch_id"], []):
                q.put_nowait(None)

    async def _run(self, batch: dict, item: dict) -> None:
        async with self._sem:
            try:
                await self.worker(item, lambda **f: self._update(batch, item, **f))
            except Exception as exc:   # one bad item never fails the batch
                self._update(batch, item, status="error", error=f"{type(exc).__name__}: {exc}")

    async def events(self, bid: str) -> AsyncIterator[dict[str, Any]]:
        """Every event from the start, then live ones; ends once every item is terminal."""
        batch = self._batches[bid]
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(batch["_events"])          # snapshot + register with no await in between
        self._subs.setdefault(bid, []).append(q)
        try:
            for e in backlog:
                yield e
            if batch["_finished"]:
                return
            while (e := await q.get()) is not None:
                yield e
        finally:
            self._subs[bid].remove(q)

