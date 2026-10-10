"""FastAPI app: REST + SSE for the UI. Endpoints are frozen in docs/plans/01 section 4.6."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from deadlang.api.events import EventBus
from deadlang.deliberation.facilitator import Facilitator
from deadlang.schemas import CaseFile, Event, now_iso

log = logging.getLogger("deadlang.api")
ROOT = Path(__file__).resolve().parents[3]
CASE_RE = re.compile(r"C-(\d+)\.jsonl$")


class CaseRequest(BaseModel):
    listing_id: str


class NameRequest(BaseModel):
    name: str


def create_app(market: Any = None, transport: Any = None, discovery: Any = None, bus: EventBus | None = None,
               data_dir: Path | None = None, replays_dir: Path | None = None, results_dir: Path | None = None) -> FastAPI:
    """Dependencies default to the real ones (built at startup); tests inject fakes."""
    data_dir = Path(data_dir or os.getenv("DL_DATA_DIR") or ROOT / "data")
    replays_dir = Path(replays_dir or ROOT / "fixtures" / "replays")
    results_dir = Path(results_dir or ROOT / "results")
    state: dict[str, Any] = {}
    cases: dict[str, dict[str, Any]] = {}

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
        yield

    app = FastAPI(title="Dead Language API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"])

    # ------------------------------------------------------------------ listings
    @app.get("/api/listings")
    async def listings(sort: str | None = None):
        market_ = state["market"]
        triage_file = data_dir / "triage.json"
        triage = json.loads(triage_file.read_text()) if triage_file.exists() else {}
        sellers: dict[str, Any] = {}
        rows = []
        for listing in await market_.all_active():
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
    @app.post("/api/cases")
    async def create_case(req: CaseRequest):
        try:
            await state["market"].get_listing_snapshot(req.listing_id)
        except KeyError:
            raise HTTPException(404, "unknown listing")
        state["counter"] += 1
        case_id = f"C-{state['counter']:04d}"
        info = {"listing_id": req.listing_id, "started_at": now_iso(), "case_file": None}
        cases[case_id] = info

        async def run():
            try:
                info["case_file"] = await state["facilitator"].run_case(case_id, req.listing_id)
            except Exception as exc:
                log.exception("case %s failed", case_id)
                # Always terminate the stream. Extends the case.ended payload with `error` (case_file is null).
                state["bus"].emit(case_id, "case.ended", {"case_file": None, "error": f"{type(exc).__name__}: {exc}"})

        info["task"] = asyncio.create_task(run())
        return {"case_id": case_id}

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
