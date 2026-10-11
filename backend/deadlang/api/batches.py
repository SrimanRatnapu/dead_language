"""Batch queue: submit many listings, watch each go queued -> triaging -> (screened_out | deliberating) -> done | error.

Contract: docs/plans/v2/00-overview-and-contracts.md section 4.2.
ponytail: in-process asyncio queue; swap Batches for Redis/SQS behind submit()/events() if we outgrow one API process.

Follow-up (optional): when an item finishes, `should_follow(batch, item)` may ask for related listings. They are
fetched by `follow_up(batch, item, room)` and appended to the same batch as new queued items, each carrying
`found_via`, `term` and `parent`. The batch (and its event stream) stays open until every follow-up has finished.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from deadlang.schemas import now_iso

log = logging.getLogger("deadlang.batches")
TERMINAL = {"screened_out", "done", "error"}
# worker(item, set_status): drives one item; set_status(status=..., triage=..., outcome=..., case_id=..., error=...)
Worker = Callable[[dict[str, Any], Callable[..., None]], Awaitable[None]]
# should_follow(batch, item) -> bool: does this finished item call for a follow-up fetch?
ShouldFollow = Callable[[dict[str, Any], dict[str, Any]], bool]
# follow_up(batch, item, room) -> [{"listing_id", "found_via", "term"}, ...]: at most `room` related listings
FollowUp = Callable[[dict[str, Any], dict[str, Any], int], Awaitable[list[dict[str, Any]]]]


class Batches:
    def __init__(self, worker: Worker, limit: int = 4, on_event: Callable[[str, dict], None] | None = None, first_id: int = 1,
                 should_follow: ShouldFollow | None = None, follow_up: FollowUp | None = None,
                 max_added: int = 20, max_items: int = 50):
        self.worker = worker
        self._first = first_id
        self.on_event = on_event
        self.should_follow, self.follow_up = should_follow, follow_up
        self.max_added = max_added     # listings a batch may gain from follow-ups, in total
        self.max_items = max_items     # ceiling on the whole batch, follow-ups included
        self._sem = asyncio.Semaphore(limit)
        self._batches: dict[str, dict[str, Any]] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._tasks: set[asyncio.Task] = set()   # strong refs so running items are not garbage collected

    def submit(self, source: str, listing_ids: list[str], source_mode: str) -> dict[str, Any]:
        bid = f"B-{self._first + len(self._batches):04d}"
        batch = {"batch_id": bid, "source": source, "source_mode": source_mode, "created_at": now_iso(), "items": [],
                 "_events": [], "_finished": False, "_running": 0, "_added": 0, "_follow_lock": asyncio.Lock()}
        self._batches[bid] = batch
        self._enqueue(batch, [{"listing_id": i} for i in dict.fromkeys(listing_ids)])
        self._maybe_finish(batch)                 # an empty batch is finished at once
        return self.view(bid)

    def _enqueue(self, batch: dict, specs: list[dict[str, Any]]) -> int:
        """Append items (skipping listings already in the batch) and start them. Returns how many were added."""
        present = {i["listing_id"] for i in batch["items"]}
        added = 0
        for spec in specs:
            if spec["listing_id"] in present:
                continue
            present.add(spec["listing_id"])
            item = {"listing_id": spec["listing_id"], "case_id": None, "status": "queued", "triage": None,
                    "outcome": None, "error": None,
                    # Follow-up fields. found_via/term/parent: why a follow-up listing is in the batch.
                    # follow_up: on the item that triggered one, {"state": "searching" | "done", "added": n}.
                    "found_via": spec.get("found_via"), "term": spec.get("term"), "parent": spec.get("parent"),
                    "follow_up": None}
            batch["items"].append(item)
            batch["_running"] += 1                # counted before the task starts, so the batch cannot finish early
            added += 1
            self._event(batch, item)
            task = asyncio.create_task(self._run(batch, item))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return added

    def get(self, bid: str) -> dict[str, Any] | None:
        return self._batches.get(bid)

    def view(self, bid: str) -> dict[str, Any]:
        return {k: v for k, v in self._batches[bid].items() if not k.startswith("_")}

    def _event(self, batch: dict, item: dict) -> None:
        e = {"type": "batch.item", "listing_id": item["listing_id"], "case_id": item["case_id"],
             "status": item["status"], "at": now_iso()}
        if item["outcome"]:
            e["outcome"] = item["outcome"]
        if item["found_via"]:                     # a follow-up listing: the UI has no row for it yet, so say why it is here
            e.update(found_via=item["found_via"], term=item["term"], parent=item["parent"])
        if item["follow_up"]:
            e["follow_up"] = item["follow_up"]
        batch["_events"].append(e)
        if self.on_event:
            self.on_event(batch["batch_id"], item)
        for q in self._subs.get(batch["batch_id"], []):
            q.put_nowait(e)

    def _update(self, batch: dict, item: dict, **fields: Any) -> None:
        item.update(fields)
        self._event(batch, item)

    def _maybe_finish(self, batch: dict) -> None:
        """A batch is finished when nothing in it is running: every item is terminal and no follow-up is pending."""
        if not batch["_finished"] and batch["_running"] == 0:
            batch["_finished"] = True
            for q in self._subs.get(batch["batch_id"], []):
                q.put_nowait(None)

    async def _run(self, batch: dict, item: dict) -> None:
        try:
            async with self._sem:
                try:
                    await self.worker(item, lambda **f: self._update(batch, item, **f))
                except Exception as exc:   # one bad item never fails the batch
                    self._update(batch, item, status="error", error=f"{type(exc).__name__}: {exc}")
                if item["status"] not in TERMINAL:   # a worker that returns without finishing must not hang the batch
                    self._update(batch, item, status="error", error="worker returned without a final status")
            await self._follow(batch, item)          # outside the semaphore: a fetch must not hold a review slot
        finally:
            batch["_running"] -= 1
            self._maybe_finish(batch)

    async def _follow(self, batch: dict, item: dict) -> None:
        """Fetch listings related to a finished item and append them to the batch. Never raises."""
        if not (self.should_follow and self.follow_up) or item["found_via"]:   # one hop: a follow-up never follows up
            return
        try:
            if not self.should_follow(self.view(batch["batch_id"]), item):
                return
            async with batch["_follow_lock"]:        # one at a time per batch, so the limits below cannot be overspent
                room = min(self.max_added - batch["_added"], self.max_items - len(batch["items"]))
                if room <= 0:
                    return
                self._update(batch, item, follow_up={"state": "searching", "added": 0})
                added = 0
                try:
                    specs = await self.follow_up(self.view(batch["batch_id"]), item, room)
                    added = self._enqueue(batch, [{**s, "parent": item["listing_id"]} for s in specs[:room]])
                    batch["_added"] += added
                finally:
                    self._update(batch, item, follow_up={"state": "done", "added": added})
        except Exception:
            log.exception("follow-up for %s in %s failed", item["listing_id"], batch["batch_id"])

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

