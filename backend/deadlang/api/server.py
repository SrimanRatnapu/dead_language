"""FastAPI app: REST + SSE for the UI. Endpoints are frozen in docs/plans/01 section 4.6."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from deadlang import config, llm
from deadlang.api.batches import Batches
from deadlang.api.events import EventBus
from deadlang.api.runs import Runs
from deadlang.deliberation.facilitator import Facilitator
from deadlang.schemas import CaseFile, Event, now_iso

log = logging.getLogger("deadlang.api")
ROOT = Path(__file__).resolve().parents[3]
CASE_RE = re.compile(r"C-(\d+)\.jsonl$")


MAX_LIVE_CAP = 50   # hard ceiling for a live fetch; the UI shows the same number


class CaseRequest(BaseModel):
    listing_id: str


class NameRequest(BaseModel):
    name: str


class StrikeRequest(BaseModel):
    action: Literal["approve", "submit"]
    by: str


class BatchRequest(BaseModel):
    source: Literal["demo", "live"]
    listing_ids: list[str] | None = None
    query: str | None = None
    cap: int = Field(25, ge=1, le=MAX_LIVE_CAP)


def demo_listing_ids(data_dir: Path) -> list[str]:
    """data/demo_set.json (Person A, list of {listing_id}) if present, else the four recorded demo cases."""
    path = data_dir / "demo_set.json"
    if path.is_file():
        return [r["listing_id"] for r in json.loads(path.read_text())]
    return list(json.loads((data_dir / "demo_cases.json").read_text()).values())


def create_app(market: Any = None, transport: Any = None, discovery: Any = None, bus: EventBus | None = None,
               data_dir: Path | None = None, replays_dir: Path | None = None, results_dir: Path | None = None) -> FastAPI:
    """Dependencies default to the real ones (built at startup); tests inject fakes."""
    data_dir = Path(data_dir or os.getenv("DL_DATA_DIR") or ROOT / "data")
    replays_dir = Path(replays_dir or ROOT / "fixtures" / "replays")
    results_dir = Path(results_dir or ROOT / "results")
    state: dict[str, Any] = {}
    cases: dict[str, dict[str, Any]] = {}
    batches: Batches

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        m, t, d = market, transport, discovery
        if m is None:
            from deadlang.marketplace.client import get_marketplace_client
            m = get_marketplace_client()
        if d is None:
            from deadlang.agntcy.discovery import get_discovery
            d = get_discovery()
            await d.register_all()
        if t is None:
            from deadlang.agntcy.transport import get_transport
            t = get_transport()
        b = bus or EventBus()
        existing = [int(m_.group(1)) for p in (b.runs_dir.glob("C-*.jsonl") if b.runs_dir else []) if (m_ := CASE_RE.search(p.name))]
        state.update(market=m, transport=t, discovery=d, bus=b, counter=max(existing, default=0),
                     facilitator=Facilitator(m, t, d, b))
        runs = state["runs"] = Runs(data_dir / "runs.db")
        llm.usage_hook = runs.record_usage
        nonlocal batches
        batches = Batches(real_worker, int(os.getenv("DL_MAX_CONCURRENT_CASES", "4")),
                          lambda bid, it: runs.record_item(bid, it["listing_id"], it["status"], it["outcome"]))
        yield
        llm.usage_hook = None

    app = FastAPI(title="Dead Language API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # any local dev port (3000 can be taken)
                       allow_origins=[],
                       allow_methods=["*"], allow_headers=["*"])

    # ------------------------------------------------------------------ listings
    @app.get("/api/listings")
    async def listings(sort: str | None = None, origin: Literal["demo", "live"] | None = None):
        market_ = state["market"]
        triage_file = data_dir / "triage.json"
        triage = json.loads(triage_file.read_text()) if triage_file.exists() else {}
        sellers: dict[str, Any] = {}
        rows = []
        for listing in await market_.all_active():
            if origin and listing.origin != origin:
                continue
            if listing.seller_id not in sellers:
                sellers[listing.seller_id] = await market_.get_seller(listing.seller_id)
            t = triage.get(listing.id)
            rows.append({"listing": listing.model_dump(mode="json"),
                         "seller": sellers[listing.seller_id].model_dump(mode="json"),
                         "triage": {"score": t["score"], "reason": t["reason"]} if t else None})
        if sort == "triage":
            rows.sort(key=lambda r: -(r["triage"]["score"] if r["triage"] else -1))
        return rows

    @app.get("/api/listings/{listing_id}")
    async def listing(listing_id: str):
        try:
            l = await state["market"].get_listing_snapshot(listing_id)
            s = await state["market"].get_seller(l.seller_id)
        except KeyError:
            raise HTTPException(404, "unknown listing")
        return {"listing": l.model_dump(mode="json"), "seller": s.model_dump(mode="json")}

    # ------------------------------------------------------------------ cases
    def start_case(listing_id: str) -> str:
        state["counter"] += 1
        case_id = f"C-{state['counter']:04d}"
        info = {"listing_id": listing_id, "started_at": now_iso(), "case_file": None}
        cases[case_id] = info

        async def run():
            try:
                state["runs"].start_case(case_id, await state["market"].get_listing_snapshot(listing_id))
                info["case_file"] = await state["facilitator"].run_case(case_id, listing_id)
                state["runs"].end_case(case_id, info["case_file"].outcome)
            except Exception as exc:
                state["runs"].end_case(case_id, None)
                log.exception("case %s failed", case_id)
                # Always terminate the stream. Extends the case.ended payload with `error` (case_file is null).
                state["bus"].emit(case_id, "case.ended", {"case_file": None, "error": f"{type(exc).__name__}: {exc}"})

        info["task"] = asyncio.create_task(run())
        return case_id

    @app.post("/api/cases")
    async def create_case(req: CaseRequest):
        try:
            await state["market"].get_listing_snapshot(req.listing_id)
        except KeyError:
            raise HTTPException(404, "unknown listing")
        return {"case_id": start_case(req.listing_id)}

    async def real_worker(item: dict[str, Any], set_status: Any) -> None:
        if state["runs"].spend_today() >= config.MAX_SPEND_USD:
            raise RuntimeError(f"daily spend cap reached (${config.MAX_SPEND_USD:g}); not starting a new case")
        # No triage step until Person B's screen() lands: every item is deliberated.
        set_status(status="deliberating", case_id=(case_id := start_case(item["listing_id"])))
        await cases[case_id]["task"]
        cf = cases[case_id]["case_file"]
        if cf is None:
            raise RuntimeError("case failed before a case file was produced")
        set_status(status="done", outcome=cf.outcome)

    # ------------------------------------------------------------------ batches
    @app.post("/api/batches", status_code=202)
    async def create_batch(req: BatchRequest):
        if req.source == "live":
            raise HTTPException(501, "live source needs Person A's fetch_live, which is not merged yet")
        ids = req.listing_ids or demo_listing_ids(data_dir)
        for lid in ids:
            try:
                await state["market"].get_listing_snapshot(lid)
            except KeyError:
                raise HTTPException(404, f"unknown listing {lid}")
        b = batches.submit(req.source, ids, "demo")   # live: "live" | "recorded", reported by fetch_live
        return {"batch_id": b["batch_id"], "source_mode": b["source_mode"], "items": b["items"]}

    @app.get("/api/batches/{batch_id}")
    async def get_batch(batch_id: str):
        if batches.get(batch_id) is None:
            raise HTTPException(404, "unknown batch")
        return batches.view(batch_id)

    @app.get("/api/batches/{batch_id}/events")
    async def batch_events(batch_id: str):
        if batches.get(batch_id) is None:
            raise HTTPException(404, "unknown batch")

        async def gen():
            async for e in batches.events(batch_id):
                yield {"event": e["type"], "data": json.dumps(e)}

        return EventSourceResponse(gen())

    # ------------------------------------------------------------------ strikes, metrics, refresh
    @app.get("/api/cases/{case_id}/strike")
    async def get_strike(case_id: str):
        if case_id not in cases:
            raise HTTPException(404, "unknown case")
        cf = cases[case_id]["case_file"]
        return state["runs"].strike(case_id, cf.tip_draft if cf else None)

    @app.post("/api/cases/{case_id}/strike")
    async def post_strike(case_id: str, req: StrikeRequest):
        if case_id not in cases:
            raise HTTPException(404, "unknown case")
        try:
            state["runs"].advance_strike(case_id, req.action, req.by)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return await get_strike(case_id)

    @app.get("/api/metrics")
    async def metrics():
        return state["runs"].metrics()

    @app.post("/api/refresh")
    async def refresh():
        try:
            from deadlang.marketplace.refresh import refresh_listings
        except ImportError:
            raise HTTPException(501, "refresh needs Person A's refresh_listings, which is not merged yet")
        ids = [l.id for l in await state["market"].all_active()]
        changes = await refresh_listings(ids)
        state["runs"].record_changes(changes, len(ids))
        for c in changes:
            if c.kind == "removed":
                state["runs"].observe_removed(c.listing_id)
        return [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in changes]

    @app.get("/api/cases")
    async def list_cases():
        return [{"case_id": cid, "listing_id": i["listing_id"], "started_at": i["started_at"],
                 "outcome": i["case_file"].outcome if i["case_file"] else None} for cid, i in cases.items()]

    @app.get("/api/cases/{case_id}/events")
    async def case_events(case_id: str):
        if case_id not in cases:
            raise HTTPException(404, "unknown case")

        async def gen():
            async for e in state["bus"].subscribe(case_id):
                yield {"event": e.type, "data": e.model_dump_json()}

        return EventSourceResponse(gen())

    @app.get("/api/cases/{case_id}/casefile", response_model=CaseFile)
    async def casefile(case_id: str):
        cf = cases.get(case_id, {}).get("case_file")
        if cf is None:
            raise HTTPException(404, "case file not ready")
        return cf

    # ------------------------------------------------------------------ demo controls
    @app.post("/api/demo/remove-listing")
    async def remove_listing(req: CaseRequest):
        relisted = await state["market"].remove_listing(req.listing_id)
        await state["facilitator"].notify_listing_removed(req.listing_id, relisted)
        return {"removed": req.listing_id, "relisted_as": relisted}

    @app.post("/api/demo/reset")
    async def reset():
        await state["market"].reset_demo()
        return {"ok": True}

    @app.post("/api/demo/kill-specialist")
    async def kill_specialist(req: NameRequest):
        await state["discovery"].mark_unhealthy(req.name)
        disabled = getattr(state["transport"], "disabled", None)
        if disabled is not None:
            disabled.add(req.name)
        return {"ok": True}

    # ------------------------------------------------------------------ replays, eval, images
    @app.get("/api/replays")
    async def replays():
        return sorted(p.stem for p in replays_dir.glob("*.jsonl")) if replays_dir.exists() else []

    @app.get("/api/replays/{name}")
    async def replay(name: str):
        path = replays_dir / f"{name}.jsonl"
        if "/" in name or "\\" in name or ".." in name or not path.is_file():
            raise HTTPException(404, "unknown replay")
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    @app.get("/api/eval")
    async def eval_results():
        path = results_dir / "eval.json"
        if not path.is_file():
            raise HTTPException(404, "no eval results yet")
        return json.loads(path.read_text())

    @app.get("/api/images/{rel_path:path}")
    async def image(rel_path: str):
        base = data_dir.resolve()
        path = (base / rel_path).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    return app


app = create_app()
