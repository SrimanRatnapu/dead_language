"""Full-set end-to-end evaluation (v2 B2): every labelled stored listing goes through Haiku triage AND the full
three-agent review, so "agents alone" and "triage then agents" can both be scored offline from the same rows.

    uv run python -m deadlang.eval.run_eval --stratified 100 --max-usd 25      (asks y/N before any call)
    uv run python -m deadlang.eval.run_eval --run-id <id> --score-only         (free: rescore saved rows)

Only the evaluation modules read data/labels.csv. The label is never given to a model: it is not in any prompt, and
this module only uses it to score. One row per listing goes to results/eval_rows/<run_id>.jsonl (append-only;
rerunning with the same --run-id skips finished listings and retries the ones that errored).
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
import re
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from deadlang import config, costs, llm, triage
from deadlang.deliberation.facilitator import AGENTS, Facilitator
from deadlang.eval.run_eval import CollectBus
from deadlang.llm import BudgetExceeded

OFFICER = "case_officer"
RAW_FLAG = 1.01                 # threshold above any score: triage returns the model's own flag, any threshold replays offline
DEFAULT_SEED = 0
DEFAULT_CONCURRENCY = 2
GIVE_UP_AFTER = 5               # consecutive error rows (a dead key, no credit): stop instead of burning through the set
GIVE_UP_CONNECTION_AFTER = 20   # consecutive rows lost to the network alone: a long outage; stop and let the user resume
CONNECTION_RETRY_SECONDS = 120.0  # how long one model call keeps retrying a dropped connection before the listing errors
PROGRESS_EVERY = 10
SWEEP = [round(0.05 * i, 2) for i in range(1, 11)]
SMALL_GROUP = 10                # a rate over fewer listings than this is not a headline
TOKEN_KEYS = ("input_tokens", "output_tokens", "calls", "cache_read_tokens", "cache_write_tokens")

# What the first-pass estimate assumes per listing (measured on the earlier real runs; the report says so).
AGENT_CALLS_PER_LISTING = 8
AGENT_INPUT_TOKENS = 3_500
AGENT_OUTPUT_TOKENS = 330
EXAMINER_LOOKS = 2
EXAMINER_OUTPUT_TOKENS = 250
TRIAGE_OUTPUT_TOKENS = 120
TRANSLATOR_INPUT_TOKENS, TRANSLATOR_OUTPUT_TOKENS = 900, 300
TRIAGE_USER_TOKENS = 300
PHOTOS_PER_LISTING = 3
PHOTO_TOKENS = 850               # an 800 px photo: width x height / 750
EXAMINER_MAX_TOKENS = 1_500


# ---------------------------------------------------------------- files

def rows_path(run_id: str):
    return config.REPO_ROOT / "results" / "eval_rows" / f"{run_id}.jsonl"


def eval_json_path():
    return config.REPO_ROOT / "results" / "eval.json"


def read_rows(run_id: str) -> dict[str, dict]:
    """One row per listing, the newest line winning, so a retried listing replaces its earlier error row."""
    out: dict[str, dict] = {}
    path = rows_path(run_id)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue                                   # a half-written last line from an interrupted run
            out[row["listing_id"]] = row
    return out


def append_row(run_id: str, row: dict) -> None:
    path = rows_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- population and order

@dataclass(frozen=True)
class Item:
    id: str
    label: bool
    category: str
    language: str
    ship_from: str
    country: str
    material: str


def load_population(data_dir=None) -> list[Item]:
    """Stored listings (listings.jsonl only) that have a label. Never the live-lane or new-listing files."""
    from pathlib import Path
    data_dir = Path(data_dir or config.DATA_DIR)
    with (data_dir / "labels.csv").open(encoding="utf-8", newline="") as f:
        labels = {r["listing_id"]: r for r in csv.DictReader(f)}
    items = []
    for line in (data_dir / "listings.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        lab = labels.get(rec["id"])
        if lab is None:
            continue
        ship = rec.get("ship_from") or ""
        items.append(Item(id=rec["id"], label=lab["should_flag"].strip().lower() == "true", category=lab["truth"].strip(),
                          language=rec.get("language", "en"), ship_from=ship, country=ship.split("-")[0] or "unknown",
                          material=str(rec.get("stated_material") or "unknown")))
    return items


def _by_category(negatives: list[Item], seed: int) -> dict[str, list[Item]]:
    rng = random.Random(seed)
    cats: dict[str, list[Item]] = {}
    for it in sorted(negatives, key=lambda i: i.id):
        cats.setdefault(it.category, []).append(it)
    for cat in sorted(cats):
        rng.shuffle(cats[cat])                             # sorted keys, so the seed gives the same order every time
    return cats


def _interleave(cats: dict[str, list[Item]]) -> list[Item]:
    out, queues = [], {c: list(v) for c, v in sorted(cats.items())}
    while any(queues.values()):
        for c in sorted(queues):
            if queues[c]:
                out.append(queues[c].pop(0))
    return out


def order_population(items: list[Item], seed: int = DEFAULT_SEED) -> list[Item]:
    """All true positives first, then the negatives one category at a time in turn (each category seeded-shuffled)."""
    positives = sorted((i for i in items if i.label), key=lambda i: i.id)
    return positives + _interleave(_by_category([i for i in items if not i.label], seed))


def _allocate(sizes: dict[str, int], total: int) -> dict[str, int]:
    """Negatives per category: proportional, at least one each when there is room, never more than the category has."""
    total = min(total, sum(sizes.values()))
    cats = sorted(sizes)
    if total <= 0:
        return {c: 0 for c in cats}
    grand = sum(sizes.values())
    share = {c: sizes[c] * total / grand for c in cats}
    alloc = {c: min(sizes[c], max(1 if total >= len(cats) else 0, int(share[c]))) for c in cats}
    while sum(alloc.values()) > total:
        c = max((c for c in cats if alloc[c] > 1), key=lambda c: alloc[c] - share[c])
        alloc[c] -= 1
    while sum(alloc.values()) < total:
        c = max((c for c in cats if alloc[c] < sizes[c]), key=lambda c: share[c] - alloc[c])
        alloc[c] += 1
    return alloc


def select(items: list[Item], limit: int | None = None, stratified: int | None = None, seed: int = DEFAULT_SEED) -> list[Item]:
    ordered = order_population(items, seed)
    if stratified is not None:
        positives = [i for i in ordered if i.label]
        if stratified <= len(positives):
            ordered = positives[:stratified]
        else:
            cats = _by_category([i for i in items if not i.label], seed)
            alloc = _allocate({c: len(v) for c, v in cats.items()}, stratified - len(positives))
            ordered = positives + _interleave({c: v[:alloc[c]] for c, v in cats.items()})
    return ordered[:limit] if limit is not None else ordered


# ---------------------------------------------------------------- cost collection

class CostCollector:
    """Per-case tokens and dollars, fed by llm.usage_detail_hook, so a row's numbers are exact and include the cache."""

    def __init__(self):
        self.cases: dict[str, dict] = {}

    def __call__(self, model, stage, case_id, tin, tout, cache_read, cache_write, ms):
        row = self.cases.setdefault(case_id, {**{k: 0 for k in TOKEN_KEYS}, "cost_usd": 0.0, "unpriced_calls": 0})
        row["input_tokens"] += tin
        row["output_tokens"] += tout
        row["cache_read_tokens"] += cache_read
        row["cache_write_tokens"] += cache_write
        row["calls"] += 1
        usd = costs.call_cost_usd(model, tin, tout, cache_read, cache_write)
        if usd is None:
            row["unpriced_calls"] += 1
        else:
            row["cost_usd"] += usd

    def take(self, case_id: str) -> dict:
        return self.cases.pop(case_id, {**{k: 0 for k in TOKEN_KEYS}, "cost_usd": 0.0, "unpriced_calls": 0})


@contextmanager
def collecting_costs(collector: CostCollector):
    previous = llm.usage_detail_hook
    llm.usage_detail_hook = collector
    try:
        yield collector
    finally:
        llm.usage_detail_hook = previous


# ---------------------------------------------------------------- one listing

_API_ERROR = re.compile(r"error code|credit|billing|rate.?limit|overloaded|api.?key|authenticat|unauthori|forbidden|"
                        r"insufficient|quota|\b(401|402|403|429|500|502|503|529)\b|api_error|permission", re.I)


def classify_specialist_error(text: str) -> str:
    """'budget' stops the run, 'error' marks the row (the model or key failed), 'warning' is a normal outcome
    (no photos, listing removed, a specialist that is not running) that the agents already read as evidence."""
    t = (text or "").strip().lower()
    if t == "budget" or "budgetexceeded" in t:
        return "budget"
    return "error" if _API_ERROR.search(t) else "warning"


_CONNECTION = re.compile(r"connection error|apiconnectionerror|apitimeouterror|timed? ?out|timeout|connecterror|"
                         r"connection (reset|refused|aborted)|remote(ly)? ?protocol|network is unreachable|getaddrinfo", re.I)


def is_connection_error(text: str) -> bool:
    """A dropped connection or a timeout: nothing was wrong with the listing, so it does not count toward the
    'N errors in a row' stop."""
    return bool(_CONNECTION.search(text or ""))


class RecordingTransport:
    """Wraps a transport and remembers failures. The Facilitator swallows an agent that errors (it carries the old
    stance over), which would make a failed API call look like a real opinion; this is how the eval notices."""

    def __init__(self, inner: Any):
        self._inner = inner
        self.agent_errors: list[str] = []
        self.specialist_errors: list[tuple[str, str]] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def call_specialist(self, specialist_name, call, *args, **kw):
        reply = await self._inner.call_specialist(specialist_name, call, *args, **kw)
        if not reply.ok:
            self.specialist_errors.append((specialist_name, reply.error or ""))
        return reply

    async def call_agent(self, agent, turn, *args, **kw):
        result = await self._inner.call_agent(agent, turn, *args, **kw)
        if isinstance(result, str):
            self.agent_errors.append(f"agent {agent}: {result}")
        return result

    async def broadcast_turns(self, turns, *args, **kw):
        results = await self._inner.broadcast_turns(turns, *args, **kw)
        for a, r in results.items():
            if isinstance(r, str):
                self.agent_errors.append(f"agent {a}: {r}")
        return results


def _claims(stats: dict[str, dict[str, int]] | None) -> dict[str, dict]:
    """Per agent: claims the model posted, how many the validator rejected in that first attempt, how many were still
    rejected after the repair call, and how many repair calls it took."""
    stats = stats or {}
    out = {}
    for a in AGENTS:
        st = stats.get(a, {})
        out[a] = {"made": st.get("claims", 0), "rejected": st.get("rejected_first", 0),
                  "rejected_after_repair": st.get("rejected_final", 0), "repairs": st.get("repairs", 0)}
    return out


class Evaluator:
    def __init__(self, run_id: str, market: Any, transport: Any, discovery: Any, screen: Callable | None = None,
                 max_rounds: int = 4):
        self.run_id, self.market, self.transport, self.discovery = run_id, market, transport, discovery
        self.screen = screen or triage.screen
        self.max_rounds = max_rounds
        self.costs = CostCollector()

    def case_id(self, listing_id: str) -> str:
        """Fresh for every run, so one run's usage never counts against the next run's per-case caps."""
        return f"ev-{self.run_id}-{listing_id}"

    async def run_triage(self, item: Item) -> dict:
        """Haiku triage alone (no agents, no specialists): the model's raw score and flag for one listing."""
        t0 = time.perf_counter()
        case = self.case_id(item.id) + "-tonly"
        row: dict = {"run_id": self.run_id, "listing_id": item.id, "label": item.label, "category": item.category,
                     "language": item.language, "ship_from": item.ship_from, "country": item.country,
                     "material": item.material, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "budget_stop": False}
        errors: list[str] = []
        result = None
        listing = await self.market.get_listing_snapshot(item.id)
        seller = await self.market.get_seller(listing.seller_id)
        try:
            count = len(await self.market.get_seller_inventory(seller.id))
        except Exception:
            count = None
        try:
            result = await self.screen(listing, seller, seller_listing_count=count, case_id=case, threshold=RAW_FLAG)
            if result.reason.startswith(triage.COULD_NOT_RUN):
                errors.append(f"triage: {result.reason}")
        except BudgetExceeded as exc:
            row["budget_stop"] = True
            errors.append(f"triage: budget: {exc}")
        except Exception as exc:
            errors.append(f"triage: {type(exc).__name__}: {exc}")
        used = self.costs.take(case)
        row["triage"] = ({"score": result.score, "flagged": bool(result.suspicious), "reason": result.reason}
                         if result else None)
        row["tokens"] = {"triage": {k: used[k] for k in TOKEN_KEYS}}
        row["cost_usd"] = {"triage": used["cost_usd"], "total": used["cost_usd"]}
        row["duration_s"] = {"total": round(time.perf_counter() - t0, 2)}
        row["errors"], row["warnings"] = errors, []
        row["connection_error"] = bool(errors) and all(is_connection_error(e) for e in errors)
        return row

    async def run_listing(self, item: Item) -> dict:
        t0 = time.perf_counter()
        case = self.case_id(item.id)
        errors: list[str] = []
        warnings: list[str] = []
        row: dict = {"run_id": self.run_id, "listing_id": item.id, "label": item.label, "category": item.category,
                     "language": item.language, "ship_from": item.ship_from, "country": item.country,
                     "material": item.material, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "budget_stop": False}
        listing = await self.market.get_listing_snapshot(item.id)
        seller = await self.market.get_seller(listing.seller_id)
        try:
            count = len(await self.market.get_seller_inventory(seller.id))
        except Exception:                                  # a hint for triage, never a reason to fail the listing
            count = None

        result, t_triage = None, time.perf_counter()
        try:
            result = await self.screen(listing, seller, seller_listing_count=count, case_id=case + "-t", threshold=RAW_FLAG)
            if result.reason.startswith(triage.COULD_NOT_RUN):
                errors.append(f"triage: {result.reason}")
        except BudgetExceeded as exc:
            row["budget_stop"] = True
            errors.append(f"triage: budget: {exc}")
        except Exception as exc:
            errors.append(f"triage: {type(exc).__name__}: {exc}")
        t_triage = time.perf_counter() - t_triage
        row["triage"] = ({"score": result.score, "flagged": bool(result.suspicious), "reason": result.reason}
                         if result else None)

        t_agents, bus, rec, cf, fac = time.perf_counter(), CollectBus(), RecordingTransport(self.transport), None, None
        if not errors:                                     # no point paying for the agents on a row that will be retried
            fac = Facilitator(self.market, rec, self.discovery, bus, max_rounds=self.max_rounds)
            fac.claim_stats = {}
            try:
                cf = await fac.run_case(case, item.id)
            except Exception as exc:
                errors.append(f"agents: {type(exc).__name__}: {exc}")
        t_agents = time.perf_counter() - t_agents

        if cf is not None:
            finals = {p.agent: p for p in cf.final_positions}
            row.update(outcome=cf.outcome, rounds=cf.rounds_used, stop_reason=cf.stop_reason,
                       agents_ran=[a for a in AGENTS if a in finals and not finals[a].abstained],
                       sat_out=[a for a in AGENTS if a in finals and finals[a].abstained])
            if cf.stop_reason == "budget":
                row["budget_stop"] = True
                errors.append("agents: budget: the case ended early at a token cap")
        else:
            row.update(outcome=None, rounds=0, stop_reason=None, agents_ran=[], sat_out=[])
        row["case_officer_abstained"] = OFFICER in row["sat_out"]
        row["claims"] = _claims(((fac.claim_stats or {}).get(case)) if fac is not None else None)
        row["final"] = ({p.agent: {"stance": p.stance, "confidence": p.confidence, "take": " ".join(p.take.split()),
                                   "ready_to_close": p.ready_to_close, "abstained": p.abstained, "claims": len(p.claims)}
                         for p in cf.final_positions} if cf is not None else {})

        errors.extend(rec.agent_errors)
        for name, text in rec.specialist_errors:
            kind = classify_specialist_error(text)
            if kind == "budget":
                row["budget_stop"] = True
            if kind == "warning":
                warnings.append(f"{name}: {text}")
            else:
                errors.append(f"specialist {name}: {text}")

        tri, ag = self.costs.take(case + "-t"), self.costs.take(case)
        if tri["unpriced_calls"] or ag["unpriced_calls"]:
            warnings.append("some calls were on a model with no known price; their cost is not counted")
        row["tokens"] = {"triage": {k: tri[k] for k in TOKEN_KEYS}, "agents": {k: ag[k] for k in TOKEN_KEYS}}
        row["cost_usd"] = {"triage": tri["cost_usd"], "agents": ag["cost_usd"], "total": tri["cost_usd"] + ag["cost_usd"]}
        row["duration_s"] = {"triage": round(t_triage, 2), "agents": round(t_agents, 2),
                             "total": round(time.perf_counter() - t0, 2)}
        row["errors"], row["warnings"] = errors, warnings
        row["connection_error"] = bool(errors) and all(is_connection_error(e) for e in errors)
        return row


def triage_rows_id(run_id: str) -> str:
    """Triage-only rows live beside the full rows, in results/eval_rows/<run_id>.triage.jsonl."""
    return f"{run_id}.triage"


def build_evaluator(run_id: str, market: Any = None) -> Evaluator:
    """The same pieces the server builds: the process-wide marketplace client (local unless MARKETPLACE_MODE=mcp),
    discovery and transport, whose specialists share that client."""
    from deadlang.agntcy.discovery import get_discovery
    from deadlang.agntcy.transport import get_transport
    from deadlang.marketplace.client import get_marketplace_client
    market = market if market is not None else get_marketplace_client()
    return Evaluator(run_id, market, get_transport(), get_discovery())


# ---------------------------------------------------------------- the run

@dataclass
class Summary:
    done: int = 0
    skipped: int = 0
    errors: int = 0
    spent: float = 0.0
    stopped: str | None = None
    ran: list[str] = field(default_factory=list)


async def run_items(ev: Evaluator, items: list[Item], *, run_id: str, out: Callable[[str], None] = print,
                    concurrency: int = DEFAULT_CONCURRENCY, max_usd: float | None = None,
                    per_listing_estimate: float | None = None, run: Callable | None = None) -> Summary:
    existing = read_rows(run_id)
    summary = Summary(spent=sum(r.get("cost_usd", {}).get("total", 0.0) for r in existing.values()))
    todo = [i for i in items if i.id not in existing or existing[i.id].get("errors")]
    summary.skipped = len(items) - len(todo)
    queue = list(todo)
    in_flight = 0
    spent_new = 0.0
    consecutive_errors = 0
    consecutive_connection = 0
    total = len(items)
    run = run or ev.run_listing

    def estimate() -> float:
        if per_listing_estimate is not None:
            return per_listing_estimate
        return spent_new / summary.done if summary.done else 0.0

    async def worker():
        nonlocal in_flight, spent_new, consecutive_errors, consecutive_connection
        while queue and summary.stopped is None:
            if max_usd is not None and summary.spent + (in_flight + 1) * estimate() > max_usd:
                summary.stopped = "max_usd"
                out(f"Stopping before the next listing: spent ${summary.spent:.2f}, one more would pass --max-usd ${max_usd:.2f}.")
                return
            item = queue.pop(0)
            in_flight += 1
            try:
                row = await run(item)
            finally:
                in_flight -= 1
            append_row(run_id, row)
            cost = row["cost_usd"]["total"]
            summary.spent += cost
            spent_new += cost
            summary.done += 1
            summary.ran.append(item.id)
            if row["errors"]:
                summary.errors += 1
                if row.get("connection_error"):             # the network, not the listing: not a sign of a dead key
                    consecutive_connection += 1
                else:
                    consecutive_errors += 1
            else:
                consecutive_errors = consecutive_connection = 0
            if row.get("budget_stop"):
                summary.stopped = summary.stopped or "budget"
                out(f"Stopping: a token cap was reached ({row['errors'][0] if row['errors'] else 'budget'}). Rows so far are saved.")
            elif consecutive_connection >= GIVE_UP_CONNECTION_AFTER:
                summary.stopped = summary.stopped or "connection"
                out(f"Stopping: {GIVE_UP_CONNECTION_AFTER} listings in a row lost to connection errors even after retrying "
                    "(a long network outage). Rows so far are saved; run the same command again to resume.")
            elif consecutive_errors >= GIVE_UP_AFTER:
                summary.stopped = summary.stopped or "errors"
                out(f"Stopping: {GIVE_UP_AFTER} listings in a row failed (check the API key and credit). Rows so far are saved.")
            position = summary.skipped + summary.done
            if summary.done % PROGRESS_EVERY == 0:
                out(f"[{position}/{total}] spend ${summary.spent:.2f} | {summary.errors} errors | {summary.done} run this time")

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    return summary


# ---------------------------------------------------------------- scoring

def rate(count: int, n: int, *, small: bool = False) -> dict:
    out = {"count": count, "n": n, "rate": round(count / n, 4) if n else None, "text": f"{count} of {n}"}
    if small:
        out["too_small_to_headline"] = n < SMALL_GROUP
    return out


def _cleared(r: dict, threshold: float) -> bool:
    t = r.get("triage") or {}
    return t.get("score", 1.0) < threshold and not t.get("flagged", True)


def _outcome(r: dict, config_name: str, threshold: float) -> str:
    return "CLEARED" if config_name == "tiered" and _cleared(r, threshold) else r["outcome"]


def _sum_tokens(rows: list[dict], with_triage: bool, with_agents: Callable[[dict], bool]) -> dict:
    tot = {k: 0 for k in TOKEN_KEYS}
    usd = 0.0
    for r in rows:
        parts = (["triage"] if with_triage else []) + (["agents"] if with_agents(r) else [])
        for p in parts:
            for k in TOKEN_KEYS:
                tot[k] += r["tokens"][p][k]
            usd += r["cost_usd"][p]
    return {**tot, "cost_usd": usd}


def _config_block(rows: list[dict], name: str, threshold: float) -> dict:
    pos = [r for r in rows if r["label"]]
    neg = [r for r in rows if not r["label"]]
    oc = lambda r: _outcome(r, name, threshold)       # noqa: E731
    block = {
        "catch": rate(sum(oc(r) in ("FILE", "WATCHLIST") for r in pos), len(pos)),
        "false_accusation": rate(sum(oc(r) == "FILE" for r in neg), len(neg)),
        "escalation": rate(sum(oc(r) == "CONTESTED" for r in rows), len(rows)),
        "outcomes_on_positives": dict(Counter(oc(r) for r in pos)),
        "outcomes_on_negatives": dict(Counter(oc(r) for r in neg)),
    }
    tiered = name == "tiered"
    if tiered:
        block["cleared_by_triage"] = rate(sum(_cleared(r, threshold) for r in rows), len(rows))
    sums = _sum_tokens(rows, with_triage=tiered, with_agents=(lambda r: not _cleared(r, threshold)) if tiered else (lambda r: True))
    n = len(rows)
    block["total_cost_usd"] = sums["cost_usd"]
    block["per_case"] = {k: (sums[k] / n if n else None) for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                                   "cache_write_tokens", "calls", "cost_usd")}
    return block


def _subgroups(rows: list[dict], threshold: float) -> dict:
    out: dict = {}
    for dim in ("language", "country", "material"):
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(str(r.get(dim) or "unknown"), []).append(r)
        out[dim] = {}
        for value, rs in sorted(groups.items()):
            pos = [r for r in rs if r["label"]]
            neg = [r for r in rs if not r["label"]]
            entry = {"n": len(rs), "n_pos": len(pos), "n_neg": len(neg)}
            for name in ("sonnet_all", "tiered"):
                oc = lambda r, name=name: _outcome(r, name, threshold)   # noqa: E731
                entry[name] = {
                    "miss": rate(sum(oc(r) not in ("FILE", "WATCHLIST") for r in pos), len(pos), small=True),
                    "false_accusation": rate(sum(oc(r) == "FILE" for r in neg), len(neg), small=True)}
            out[dim][value] = entry
    return out


def score_rows(all_rows: list[dict], threshold: float | None = None) -> dict:
    """Everything the report needs, from saved rows only. Rows with errors are left out of every number."""
    threshold = config.TRIAGE_THRESHOLD if threshold is None else threshold
    rows = [r for r in all_rows if not r.get("errors")]
    bad = [r for r in all_rows if r.get("errors")]
    pos, neg = [r for r in rows if r["label"]], [r for r in rows if not r["label"]]
    sweep = []
    for t in SWEEP:
        kept_pos = [r for r in pos if not _cleared(r, t)]
        sweep.append({"threshold": t, "recall": rate(len(kept_pos), len(pos)),
                      "cleared": rate(sum(_cleared(r, t) for r in rows), len(rows)),
                      "is_current_threshold": abs(t - threshold) < 1e-9})
    sat = lambda rs: rate(sum(r["case_officer_abstained"] for r in rs), len(rs))      # noqa: E731
    categories = sorted({r["category"] for r in rows})
    claim_quality = {}
    for a in AGENTS:
        ran = [r for r in rows if a in r["agents_ran"]]
        made = sum(r["claims"][a]["made"] for r in ran)
        rejected = sum(r["claims"][a]["rejected"] for r in ran)
        after = sum(r["claims"][a].get("rejected_after_repair", r["claims"][a]["rejected"]) for r in ran)
        repairs = sum(r["claims"][a].get("repairs", 0) for r in ran)
        claim_quality[a] = {"listings": len(ran), "made": made, "rejected": rejected,
                            "rejection_rate": round(rejected / made, 4) if made else None,
                            "rejected_after_repair": after, "repair_calls": repairs}
    return {
        "threshold": threshold,
        "population": {"n_rows": len(all_rows), "n_scored": len(rows), "n_errors": len(bad),
                       "error_ids": [r["listing_id"] for r in bad], "n_positives": len(pos), "n_negatives": len(neg)},
        "configs": {"sonnet_all": _config_block(rows, "sonnet_all", threshold),
                    "tiered": _config_block(rows, "tiered", threshold)},
        "triage_sweep": sweep,
        "subgroups": _subgroups(rows, threshold),
        "case_officer_sat_out": {"overall": sat(rows), "by_label": {"positive": sat(pos), "negative": sat(neg)},
                                 "by_category": {c: sat([r for r in rows if r["category"] == c]) for c in categories}},
        "claim_quality": claim_quality,
    }


def write_eval(result: dict, run_id: str) -> None:
    """Adds a `full_eval` key to results/eval.json and leaves every existing key (A, B, C, examples) as it was."""
    path = eval_json_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    kept = (data.get("full_eval") or {}).get("triage_full") if isinstance(data.get("full_eval"), dict) else None
    data["full_eval"] = {"run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **result}
    if kept is not None:                                  # a triage-only result from another run stays
        data["full_eval"]["triage_full"] = kept
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def score_triage(all_rows: list[dict], threshold: float | None = None) -> dict:
    """Triage alone over every scored listing: the real clearance rate and the recall on true positives at each threshold."""
    threshold = config.TRIAGE_THRESHOLD if threshold is None else threshold
    rows = [r for r in all_rows if not r.get("errors") and r.get("triage")]
    pos, neg = [r for r in rows if r["label"]], [r for r in rows if not r["label"]]
    sweep = [{"threshold": t, "recall": rate(sum(not _cleared(r, t) for r in pos), len(pos)),
              "cleared": rate(sum(_cleared(r, t) for r in rows), len(rows)),
              "cleared_negatives": rate(sum(_cleared(r, t) for r in neg), len(neg)),
              "missed_positives": [r["listing_id"] for r in pos if _cleared(r, t)],
              "is_current_threshold": abs(t - threshold) < 1e-9} for t in SWEEP]
    cats = sorted({r["category"] for r in rows})
    cost = sum(r["cost_usd"]["total"] for r in all_rows)
    return {"threshold": threshold,
            "population": {"n_rows": len(all_rows), "n_scored": len(rows), "n_errors": sum(bool(r.get("errors")) for r in all_rows),
                           "n_positives": len(pos), "n_negatives": len(neg)},
            "at_current_threshold": {"recall": rate(sum(not _cleared(r, threshold) for r in pos), len(pos)),
                                     "cleared": rate(sum(_cleared(r, threshold) for r in rows), len(rows)),
                                     "cleared_by_category": {c: rate(sum(_cleared(r, threshold) for r in rows if r["category"] == c),
                                                                     sum(r["category"] == c for r in rows)) for c in cats}},
            "sweep": sweep, "total_cost_usd": cost, "cost_per_listing_usd": cost / len(all_rows) if all_rows else None}


def write_triage_full(result: dict, run_id: str) -> None:
    """Puts a triage-only result at full_eval.triage_full in results/eval.json; everything else stays as it was."""
    path = eval_json_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data.get("full_eval"), dict):
        data["full_eval"] = {}
    data["full_eval"]["triage_full"] = {"run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        **result}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def format_triage(result: dict, run_id: str) -> str:
    p = result["population"]
    lines = [f"Triage alone, run {run_id}: {p['n_scored']} listings ({p['n_positives']} true positives, {p['n_negatives']} negatives); "
             f"{p['n_errors']} errored and left out. Cost ${result['total_cost_usd']:.2f}."]
    lines.append("threshold: positives kept (recall) | share of all listings cleared | negatives cleared")
    for s_ in result["sweep"]:
        mark = "  <- current" if s_["is_current_threshold"] else ""
        lines.append(f"  {s_['threshold']:.2f}: {s_['recall']['text']} ({_pct(s_['recall'])}) | {s_['cleared']['text']} "
                     f"({_pct(s_['cleared'])}) | {s_['cleared_negatives']['text']}{mark}")
    return "\n".join(lines)


def _pct(r: dict) -> str:
    return "n/a" if r["rate"] is None else f"{r['rate']:.0%}"


def format_summary(result: dict, run_id: str) -> str:
    p = result["population"]
    lines = [f"Scored run {run_id}: {p['n_scored']} listings ({p['n_positives']} true positives, {p['n_negatives']} negatives); "
             f"{p['n_errors']} errored and left out."]
    for name, c in result["configs"].items():
        lines.append(f"  {name}: catch {c['catch']['text']} ({_pct(c['catch'])}), false accusation "
                     f"{c['false_accusation']['text']} ({_pct(c['false_accusation'])}), escalation {c['escalation']['text']} "
                     f"({_pct(c['escalation'])}); ${c['per_case']['cost_usd'] or 0:.4f} per case, "
                     f"{round(c['per_case']['input_tokens'] or 0):,} in / {round(c['per_case']['output_tokens'] or 0):,} out tokens per case")
    lines.append(f"  triage cleared {result['configs']['tiered']['cleared_by_triage']['text']} at threshold {result['threshold']}")
    lines.append("Triage recall sweep (threshold: positives kept / share cleared):")
    for s in result["triage_sweep"]:
        mark = "  <- current" if s["is_current_threshold"] else ""
        lines.append(f"  {s['threshold']:.2f}: {s['recall']['text']} kept ({_pct(s['recall'])}), {s['cleared']['text']} cleared{mark}")
    lines.append("Subgroups for the agents alone (miss = true positive not filed or watchlisted; n < "
                 f"{SMALL_GROUP} is too small to headline):")
    for dim, groups in result["subgroups"].items():
        for value, g in groups.items():
            m, f = g["sonnet_all"]["miss"], g["sonnet_all"]["false_accusation"]
            note = "  (too small to headline)" if m["too_small_to_headline"] and f["too_small_to_headline"] else ""
            lines.append(f"  {dim}={value}: n={g['n']} | miss {m['text']} | false accusation {f['text']}{note}")
    s = result["case_officer_sat_out"]
    lines.append(f"Case officer sat out: {s['overall']['text']} overall; positives {s['by_label']['positive']['text']}, "
                 f"negatives {s['by_label']['negative']['text']}.")
    lines.append("Claim rejections: " + ", ".join(f"{a} {q['rejected']} of {q['made']}" for a, q in result["claim_quality"].items()))
    return "\n".join(lines)


# ---------------------------------------------------------------- estimate, models, command line

def role_models() -> list[tuple[str, str, str]]:
    from deadlang.deliberation.agents import _model
    return [("triage", config.MODEL_TRIAGE, "DL_MODEL_TRIAGE"), ("translator", config.MODEL_TRIAGE, "DL_MODEL_TRIAGE"),
            ("quick examiner (fallback, not planned)", config.MODEL_FAST, "DL_MODEL_FAST"),
            ("thorough examiner", config.MODEL_STRONG, "DL_MODEL_STRONG"),
            *[(a, _model(), "DL_MODEL_STRONG") for a in AGENTS]]


def is_haiku(model: str) -> bool:
    return "haiku" in model.lower()


def plan_batches(items: list[Item], concurrency: int, triage_only: bool = False) -> list[costs.Batch]:
    from deadlang.deliberation.agents import DeliberatingAgent, post_schema, SCHEMA_NAME as POST
    from deadlang.specialists import material
    n = len(items)
    if triage_only:
        tri_in = llm.estimate_input_tokens(triage.SCREEN_SYSTEM, "x" * int(TRIAGE_USER_TOKENS * llm.CHARS_PER_TOKEN),
                                           schema=triage.SCHEMA) + costs.TOOL_USE_OVERHEAD_TOKENS
        return [costs.Batch("triage only", config.MODEL_TRIAGE, n, tri_in, TRIAGE_OUTPUT_TOKENS, triage.MAX_TOKENS,
                            calls_per_case=1, concurrency=1)]
    foreign = sum(i.language != "en" for i in items)
    strong, tri = config.MODEL_STRONG, config.MODEL_TRIAGE
    tri_in = llm.estimate_input_tokens(triage.SCREEN_SYSTEM, "x" * int(TRIAGE_USER_TOKENS * llm.CHARS_PER_TOKEN),
                                       schema=triage.SCHEMA) + costs.TOOL_USE_OVERHEAD_TOKENS
    exam_system = material.PROMPT_FILE.read_text(encoding="utf-8")
    exam_in = (llm.estimate_input_tokens(exam_system, material.USER_MESSAGE, images=PHOTOS_PER_LISTING,
                                         schema=material.SCHEMA, image_tokens=PHOTO_TOKENS)
               + costs.TOOL_USE_OVERHEAD_TOKENS)
    agent = DeliberatingAgent("undercover")
    batches = [
        costs.Batch("triage", tri, n, tri_in, TRIAGE_OUTPUT_TOKENS, triage.MAX_TOKENS, calls_per_case=1, concurrency=1),
        costs.Batch("thorough examiner", strong, n * EXAMINER_LOOKS, exam_in,
                    costs.expected_output_tokens(strong, EXAMINER_OUTPUT_TOKENS), EXAMINER_MAX_TOKENS,
                    calls_per_case=EXAMINER_LOOKS, concurrency=EXAMINER_LOOKS,
                    cached_prefix_tokens=llm.cached_prefix_tokens(strong, exam_system, material.SCHEMA, material.SCHEMA_NAME)),
        costs.Batch("three agents", strong, n * AGENT_CALLS_PER_LISTING, AGENT_INPUT_TOKENS,
                    costs.expected_output_tokens(strong, AGENT_OUTPUT_TOKENS), 1_500,
                    calls_per_case=AGENT_CALLS_PER_LISTING + EXAMINER_LOOKS, concurrency=1,
                    cached_prefix_tokens=llm.cached_prefix_tokens(strong, agent.system, post_schema(), POST)),
    ]
    if foreign:
        batches.insert(1, costs.Batch("translator", tri, foreign, TRANSLATOR_INPUT_TOKENS, TRANSLATOR_OUTPUT_TOKENS, 800))
    return batches


def _commands(run_id: str, args, est: costs.Estimate | None) -> list[str]:
    flag = ("--triage-only " if args.triage_only else "") + (f"--stratified {args.stratified} " if args.stratified
                                                              else (f"--limit {args.limit} " if args.limit else ""))
    flag += f"--concurrency {args.concurrency} " if args.concurrency != DEFAULT_CONCURRENCY else ""
    budget = max(5, -(-int((est.dollars or 0) * 1.3) // 5) * 5) if est else 25      # ~30% over the estimate, in $5 steps
    base = f"uv run python -m deadlang.eval.run_eval {flag}--run-id {run_id} --max-usd {budget}"
    ps, sh = base, base
    if est:
        in_cap = -(-int(est.input_tokens * 1.3) // 100_000) * 100_000
        out_cap = -(-int(est.output_tokens * 1.3) // 100_000) * 100_000
        left_in = config.MAX_INPUT_TOKENS - llm.effective_input(llm.usage_snapshot())
        left_out = config.MAX_OUTPUT_TOKENS - llm.usage_snapshot()["output_tokens"]
        if est.input_tokens > left_in or est.output_tokens > left_out:       # the global caps would stop it part way
            ps = f"$env:DL_MAX_INPUT_TOKENS={max(in_cap, config.MAX_INPUT_TOKENS)}; $env:DL_MAX_OUTPUT_TOKENS={max(out_cap, config.MAX_OUTPUT_TOKENS)}; {base}"
            sh = f"DL_MAX_INPUT_TOKENS={max(in_cap, config.MAX_INPUT_TOKENS)} DL_MAX_OUTPUT_TOKENS={max(out_cap, config.MAX_OUTPUT_TOKENS)} {base}"
    return [f"  PowerShell (from the backend folder):  {ps}",
            f"  bash (from the backend folder):        {sh}",
            "  It prints the estimate and asks y/N; add --yes to skip the question.",
            "  Resume after a stop: run the same command again (finished listings are skipped).",
            f"  Rescore for free, no calls:            uv run python -m deadlang.eval.run_eval {'--triage-only ' if args.triage_only else ''}--run-id {run_id} --score-only"]


async def main(args, ask: Callable[[str], str] = input, market: Any = None, out: Callable[[str], None] = print) -> int:
    """Returns the exit code: 0 done, 1 declined, 2 stopped before any call (bad setup)."""
    only = bool(getattr(args, "triage_only", False))
    if args.score_only:
        if not args.run_id:
            out("--score-only needs --run-id <id> (the run whose rows in results/eval_rows/ you want to score).")
            return 2
        storage = triage_rows_id(args.run_id) if only else args.run_id
        rows = list(read_rows(storage).values())
        if not rows:
            out(f"No rows found for run {args.run_id} at {rows_path(storage)}; nothing to score.")
            return 2
        threshold = args.threshold
        if threshold is not None and not 0.0 <= threshold <= 1.0:
            out("--threshold must be between 0 and 1.")
            return 2
        if only:
            result = score_triage(rows, threshold)
            write_triage_full(result, args.run_id)
            out(format_triage(result, args.run_id))
            out("Wrote results/eval.json (key full_eval.triage_full).")
        else:
            result = score_rows(rows, threshold)
            write_eval(result, args.run_id)
            out(format_summary(result, args.run_id))
            out("Wrote results/eval.json (key full_eval).")
        return 0

    out("Models by role:")
    for role, model, env in role_models():
        if only and role != "triage":
            continue
        out(f"  {role:<38} {model}   ({env})")
    if not is_haiku(config.MODEL_TRIAGE):
        out(f"STOP: triage is on {config.MODEL_TRIAGE}, not Haiku. The tiered numbers only mean something with a Haiku "
            "triage. Set DL_MODEL_TRIAGE=claude-haiku-4-5-20251001 (in the environment or .env) and run again. "
            "No calls were made.")
        return 2

    args.concurrency = args.concurrency or DEFAULT_CONCURRENCY
    population = load_population(config.DATA_DIR)
    chosen = select(population, limit=args.limit, stratified=args.stratified)
    run_id = args.run_id or costs.new_run_id()
    storage = triage_rows_id(run_id) if only else run_id
    positives = sum(i.label for i in population)
    out(f"Population: {len(population)} labeled listings in listings.jsonl ({positives} true positives, "
        f"{len(population) - positives} negatives).")
    out(f"Selected: {len(chosen)} listings ({sum(i.label for i in chosen)} true positives first, then negatives "
        f"interleaved across categories). Run id: {run_id}{' (triage only)' if only else ''}. Concurrency {args.concurrency}.")
    done = read_rows(storage)
    todo = [i for i in chosen if i.id not in done or done[i.id].get("errors")]
    if len(todo) != len(chosen):
        out(f"Resuming: {len(chosen) - len(todo)} already finished, {len(todo)} to run.")
    if not todo:
        out("Nothing left to run.")
    batches = plan_batches(todo, args.concurrency, triage_only=only) if todo else []
    per_listing = (costs.estimate(batches).dollars or 0.0) / len(todo) if todo else 0.0

    if args.dry_run:
        if batches:
            out(costs.report(batches))
            detail = "." if only else (f"; the figures assume {AGENT_CALLS_PER_LISTING} agent calls and "
                                       f"{PHOTOS_PER_LISTING} photos per listing (measured on earlier runs).")
            out(f"Per listing ~${per_listing:.4f}{detail}")
            out(f"A dropped connection is retried for up to {CONNECTION_RETRY_SECONDS:.0f} s per call before a listing errors; "
                f"{GIVE_UP_CONNECTION_AFTER} such listings in a row stop the run (other errors: {GIVE_UP_AFTER}).")
        out("Dry run: no calls were made. To run it yourself:")
        for line in _commands(run_id, args, costs.estimate(batches) if batches else None):
            out(line)
        return 0

    if batches and not costs.confirm(batches, assume_yes=args.yes, ask=ask, out=out):
        out("No calls were made.")
        return 1

    if todo:
        ev = build_evaluator(run_id, market)
        previous_retry, llm.CONNECTION_RETRY_SECONDS = llm.CONNECTION_RETRY_SECONDS, CONNECTION_RETRY_SECONDS
        try:
            await ev.discovery.register_all()
            with collecting_costs(ev.costs):
                summary = await run_items(ev, chosen, run_id=storage, out=out, concurrency=args.concurrency,
                                          max_usd=args.max_usd, per_listing_estimate=per_listing or None,
                                          run=ev.run_triage if only else None)
        finally:
            llm.CONNECTION_RETRY_SECONDS = previous_retry
            close = getattr(ev.market, "aclose", None)       # the MCP client holds a session; the local one has nothing
            if close:
                await close()
        out(f"Spend this run: ${summary.spent:.2f} | listings done: {summary.done} | errors: {summary.errors}"
            + (f" | stopped: {summary.stopped}" if summary.stopped else ""))
    rows = list(read_rows(storage).values())
    if rows and only:
        result = score_triage(rows)
        write_triage_full(result, run_id)
        out(format_triage(result, run_id))
        out("Wrote results/eval.json (key full_eval.triage_full).")
    elif rows:
        result = score_rows(rows)
        write_eval(result, run_id)
        out(format_summary(result, run_id))
        out("Wrote results/eval.json (key full_eval).")
    return 0
