"""Persistence, audit, strikes and metrics in one SQLite file (data/runs.db).

ponytail: stdlib sqlite3, one connection, move to Postgres when more than one writer process is needed.
events/strikes/usage/changes are append-only; a finished case row is never updated after `end_case`.
The per-case event log stays in runs/<case>.jsonl (EventBus), which is what replays read.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deadlang import config, costs
from deadlang.schemas import now_iso

_ROOT = Path(__file__).resolve().parents[1]
STRIKE_FLOW = ("pending_review", "approved", "submitted_simulated", "observed_removed")

SCHEMA = """
create table if not exists cases(case_id text primary key, listing_id, origin, outcome, started_at, ended_at,
  model_versions, prompt_hash, rules_version, snapshot_sha256);
create table if not exists items(batch_id, listing_id, status, outcome, at);
create table if not exists usage(id integer primary key, at, case_id, model, stage, tokens_in, tokens_out, usd, duration_ms);
create table if not exists strikes(id integer primary key, case_id, status, at, by);
create table if not exists changes(id integer primary key, listing_id, kind, at, old, new);
create table if not exists refreshes(at, checked, changed, removed);
"""


def _hash_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()[:16]


def prompt_hash() -> str:
    return _hash_files(list((_ROOT / "deliberation" / "prompts").glob("*.md")))


def rules_version() -> str:
    return _hash_files([_ROOT / "deliberation" / "rules.py"])


def usd(model: str, tin: int, tout: int) -> float:
    p = costs.price_for(model)
    return (tin * p[0] + tout * p[1]) / 1e6 if p else 0.0


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


class Runs:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _x(self, sql: str, *a: Any) -> sqlite3.Cursor:
        cur = self.db.execute(sql, a)
        self.db.commit()
        return cur

    # ---------------------------------------------------------------- audit
    def start_case(self, case_id: str, listing: Any) -> None:
        snap = hashlib.sha256(listing.model_dump_json().encode()).hexdigest()
        self._x("insert or ignore into cases values(?,?,?,?,?,?,?,?,?,?)", case_id, listing.id, listing.origin, None,
                now_iso(), None, json.dumps({"strong": config.MODEL_STRONG, "fast": config.MODEL_FAST}),
                prompt_hash(), rules_version(), snap)

    def end_case(self, case_id: str, outcome: str | None) -> None:
        self._x("update cases set outcome=?, ended_at=? where case_id=? and ended_at is null", outcome, now_iso(), case_id)
        if outcome in ("FILE", "CONTESTED") and not self._strike_rows(case_id):
            self._x("insert into strikes(case_id,status,at,by) values(?,?,?,?)", case_id, "pending_review", now_iso(), "system")

    def case(self, case_id: str) -> dict[str, Any] | None:
        r = self.db.execute("select * from cases where case_id=?", (case_id,)).fetchone()
        return dict(r) if r else None

    def record_usage(self, model: str, stage: str, case_id: str | None, tin: int, tout: int, ms: float) -> None:
        self._x("insert into usage(at,case_id,model,stage,tokens_in,tokens_out,usd,duration_ms) values(?,?,?,?,?,?,?,?)",
                now_iso(), case_id, model, stage, tin, tout, usd(model, tin, tout), ms)

    def record_item(self, batch_id: str, listing_id: str, status: str, outcome: str | None) -> None:
        self._x("insert into items values(?,?,?,?,?)", batch_id, listing_id, status, outcome, now_iso())

    def record_changes(self, changes: list[Any], checked: int) -> None:
        for c in changes:
            self._x("insert into changes(listing_id,kind,at,old,new) values(?,?,?,?,?)", c.listing_id, c.kind, c.at,
                    json.dumps(c.old), json.dumps(c.new))
        self._x("insert into refreshes values(?,?,?,?)", now_iso(), checked, len(changes),
                sum(c.kind == "removed" for c in changes))

    def batch_count(self) -> int:
        return self.db.execute("select count(distinct batch_id) from items").fetchone()[0]

    def spend_today(self) -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.db.execute("select coalesce(sum(usd),0) from usage where at >= ?", (day,)).fetchone()[0]

    # ---------------------------------------------------------------- strikes
    def _strike_rows(self, case_id: str) -> list[sqlite3.Row]:
        return self.db.execute("select status,at,by from strikes where case_id=? order by id", (case_id,)).fetchall()

    def strike(self, case_id: str, notice: str | None) -> dict[str, Any]:
        rows = self._strike_rows(case_id)
        status = rows[-1]["status"] if rows else "none"
        approved = next((r["by"] for r in rows if r["status"] == "approved"), None)
        return {"status": status, "approved_by": approved,
                "notice_draft": notice if status in ("submitted_simulated", "observed_removed") else None,
                "history": [dict(r) for r in rows]}

    def advance_strike(self, case_id: str, action: str, by: str) -> None:
        """approve: pending_review -> approved; submit: approved -> submitted_simulated. ValueError otherwise."""
        by = (by or "").strip()
        if not by:
            raise ValueError("a named human (`by`) is required")
        want, need = {"approve": ("approved", "pending_review"), "submit": ("submitted_simulated", "approved")}[action]
        rows = self._strike_rows(case_id)
        cur = rows[-1]["status"] if rows else "none"
        if cur != need:
            raise ValueError(f"cannot {action} from status {cur!r}; needs {need!r}")
        self._x("insert into strikes(case_id,status,at,by) values(?,?,?,?)", case_id, want, now_iso(), by)

    def observe_removed(self, listing_id: str) -> None:
        """Refresh saw this listing gone: advance only cases already submitted (an earlier removal is just a change)."""
        for r in self.db.execute("select case_id from cases where listing_id=?", (listing_id,)).fetchall():
            rows = self._strike_rows(r["case_id"])
            if rows and rows[-1]["status"] == "submitted_simulated":
                self._x("insert into strikes(case_id,status,at,by) values(?,?,?,?)", r["case_id"], "observed_removed",
                        now_iso(), "refresh")

    # ---------------------------------------------------------------- metrics
    def metrics(self, window_min: int = 10) -> dict[str, Any]:
        q = lambda sql, *a: self.db.execute(sql, a).fetchall()   # noqa: E731
        last = {}   # latest status per (batch, listing)
        for r in q("select * from items order by rowid"):
            last[(r["batch_id"], r["listing_id"])] = r
        outs = [r["outcome"] for r in last.values() if r["status"] == "done"]
        funnel = {"ingested": len(last), "screened_out": sum(r["status"] == "screened_out" for r in last.values()),
                  "deliberated": len(outs), "errors": sum(r["status"] == "error" for r in last.values()), **{o: outs.count(o) for o in ("FILE", "DISMISS", "CONTESTED", "WATCHLIST")}}
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_min)).isoformat()
        recent = sum(1 for r in last.values() if r["status"] in ("done", "screened_out") and r["at"] >= cutoff)
        tri = [r["duration_ms"] for r in q("select duration_ms from usage where stage like 'triage%'")]
        case_ms = [(datetime.fromisoformat(r["ended_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds() * 1000
                   for r in q("select started_at,ended_at from cases where ended_at is not null")]
        t = q("select coalesce(sum(usd),0) u, coalesce(sum(tokens_in),0) i, coalesce(sum(tokens_out),0) o from usage")[0]
        by_model = {r["model"]: {"calls": r["c"], "tokens_in": r["i"], "tokens_out": r["o"], "usd": round(r["u"], 4)}
                    for r in q("select model,count(*) c,sum(tokens_in) i,sum(tokens_out) o,sum(usd) u from usage group by model")}
        rf = q("select * from refreshes order by rowid desc limit 1")
        st = {s: 0 for s in STRIKE_FLOW}
        for r in q("select case_id from strikes group by case_id"):
            st[self._strike_rows(r["case_id"])[-1]["status"]] += 1
        return {"funnel": funnel,
                "latency_ms": {"triage": {"p50": _pct(tri, .5), "p95": _pct(tri, .95)},
                               "case": {"p50": _pct(case_ms, .5), "p95": _pct(case_ms, .95)}},
                "throughput_per_min": round(recent / window_min, 2),
                "cost": {"usd_total": round(t["u"], 4), "usd_per_case": round(t["u"] / len(case_ms), 4) if case_ms else 0.0,
                         "tokens_in": t["i"], "tokens_out": t["o"]},
                "by_model": by_model,
                "refresh": {"last_run_at": rf[0]["at"] if rf else None, "checked": rf[0]["checked"] if rf else 0,
                            "changed": rf[0]["changed"] if rf else 0, "removed": rf[0]["removed"] if rf else 0},
                "strikes": st}
