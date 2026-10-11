"""Evaluation runner: A = listing only, B = one agent + full evidence, C = three-agent deliberation.

    uv run python -m deadlang.eval.run_eval --modes A,B,C --limit 4

Only this module reads data/labels.csv. Resumable via results/eval_rows.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

from deadlang import llm
from deadlang.deliberation.facilitator import Facilitator
from deadlang.eval import baselines

ROOT = Path(__file__).resolve().parents[3]
DATA, RESULTS = ROOT / "data", ROOT / "results"
ROWS = RESULTS / "eval_rows.jsonl"


class CollectBus:
    """Event sink that keeps events in memory instead of writing replay logs."""
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, case_id, type_, payload):
        self.events.append((type_, payload))


def stance_changes_after_new_evidence(events: list[tuple[str, dict]]) -> int:
    """Posts whose changed_because_evidence cites an item added after that agent's previous post."""
    added_at: dict[str, int] = {}
    last_post: dict[str, int] = {}
    n = 0
    for i, (t, p) in enumerate(events):
        if t == "evidence.added":
            added_at[p["evidence"]["id"]] = i
        elif t == "stance.posted":
            post = p["post"]
            prev = last_post.get(post["agent"], -1)
            if any(added_at.get(e, -1) > prev for e in post.get("changed_because_evidence", [])):
                n += 1
            last_post[post["agent"]] = i
    return n


def _usage(case_id: str) -> dict:
    return llm.usage_snapshot(case_id)


async def run_listing(fac: Facilitator, lid: str, modes: set[str]) -> dict:
    row: dict = {"listing_id": lid}
    listing = await fac.market.get_listing_snapshot(lid)
    intake = None
    if modes & {"B", "C"}:
        intake = await fac.run_intake(f"eval-intake-{lid}", lid)
    if "A" in modes:
        cid = f"eval-A-{lid}"
        out = await baselines.listing_only(listing, cid)
        row["A"] = {"decision": out["decision"].upper(), "confidence": out["confidence"], **_usage(cid)}
    if "B" in modes:
        cid = f"eval-B-{lid}"
        out, rejected = await baselines.single_agent_with_evidence(
            intake.board, f"{listing.title}\n{listing.description}", cid)
        row["B"] = {"decision": out["decision"].upper(), "confidence": out["confidence"],
                    "claims_rejected": rejected, **_usage(cid)}
    if "C" in modes:
        cid = f"eval-C-{lid}"
        bus = CollectBus()
        fac.bus = bus
        cf = await fac.run_case(cid, lid, intake=intake)
        row["C"] = {"decision": cf.outcome, "rounds": cf.rounds_used, "stop_reason": cf.stop_reason,
                    "claims_rejected": sum(t == "claim.rejected" for t, _ in bus.events),
                    "stance_changes_after_new_evidence": stance_changes_after_new_evidence(bus.events),
                    **_usage(cid)}
    return row


def compute_metrics(rows: list[dict], labels: dict[str, bool]) -> dict:
    out: dict = {}
    pos = [r for r in rows if labels[r["listing_id"]]]
    neg = [r for r in rows if not labels[r["listing_id"]]]
    for m in "ABC":
        rs = [r for r in rows if m in r]
        if not rs:
            continue
        dec = lambda r: r[m]["decision"]
        d = {"n_pos": len([r for r in pos if m in r]), "n_neg": len([r for r in neg if m in r]),
             "caught": sum(dec(r) == "FILE" for r in pos if m in r),
             "false_accusations": sum(dec(r) == "FILE" for r in neg if m in r),
             "avg_input_tokens": round(sum(r[m]["input_tokens"] for r in rs) / len(rs)),
             "avg_output_tokens": round(sum(r[m]["output_tokens"] for r in rs) / len(rs))}
        d["false_accusation_rate"] = round(d["false_accusations"] / d["n_neg"], 3) if d["n_neg"] else None
        if m in "BC":
            d["claims_rejected_total"] = sum(r[m]["claims_rejected"] for r in rs)
            d["claims_rejected_per_case"] = round(d["claims_rejected_total"] / len(rs), 2)
        if m == "C":
            d["caught_or_escalated"] = sum(dec(r) in ("FILE", "CONTESTED") for r in pos if m in r)
            d["escalated_rate"] = round(sum(dec(r) == "CONTESTED" for r in rs) / len(rs), 3)
            d["stance_changes_after_new_evidence"] = sum(r[m]["stance_changes_after_new_evidence"] for r in rs)
        out[m] = d
    if "B" in out and "C" in out:
        both = [r for r in rows if "B" in r and "C" in r]
        out["examples"] = {
            "c_caught_b_missed": [r["listing_id"] for r in both if labels[r["listing_id"]]
                                  and r["C"]["decision"] == "FILE" and r["B"]["decision"] != "FILE"][:3],
            "b_false_accusation_c_avoided": [r["listing_id"] for r in both if not labels[r["listing_id"]]
                                             and r["B"]["decision"] == "FILE" and r["C"]["decision"] != "FILE"][:3]}
    return out


def read_labels(path: Path = DATA / "labels.csv") -> dict[str, bool]:
    with path.open() as f:
        return {r["listing_id"]: r["should_flag"].strip().lower() == "true" for r in csv.DictReader(f)}


def merge_rows(rows: list[dict]) -> dict[str, dict]:
    """One row per listing; rows from separate runs (different modes) are combined, newest wins per mode."""
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["listing_id"], {}).update(r)
    return out


def read_rows() -> list[dict]:
    return [json.loads(x) for x in ROWS.read_text().splitlines()] if ROWS.exists() else []


async def main(modes: set[str], limit: int | None) -> None:
    from deadlang.agntcy.discovery import get_discovery
    from deadlang.agntcy.transport import get_transport
    from deadlang.marketplace.client import get_marketplace_client

    ids = (DATA / "eval_set.txt").read_text().split()[:limit]
    discovery = get_discovery()
    await discovery.register_all()
    fac = Facilitator(get_marketplace_client(), get_transport(), discovery, CollectBus())
    RESULTS.mkdir(exist_ok=True)
    done = merge_rows(read_rows())
    for lid in ids:
        missing = modes - set(done.get(lid, {}))
        if not missing:
            continue
        fac.bus = CollectBus()
        row = await run_listing(fac, lid, missing)
        with ROWS.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(lid, {m: row[m]["decision"] for m in "ABC" if m in row}, flush=True)
    merged = merge_rows(read_rows())
    rows = [merged[i] for i in ids if i in merged]
    (RESULTS / "eval.json").write_text(json.dumps(compute_metrics(rows, read_labels()), indent=2))
    print("wrote results/eval.json")


FULL_FLAGS = ("full", "dry_run", "stratified", "max_usd", "run_id", "yes", "score_only", "concurrency", "threshold")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Without the full-set flags this is the old A/B/C run on data/eval_set.txt. "
                                             "Any flag in the second group runs the full-set end-to-end eval instead.")
    ap.add_argument("--modes", default="A,B,C")
    ap.add_argument("--limit", type=int, help="old run: first N of eval_set.txt; full-set run: first N of the balanced order")
    full = ap.add_argument_group("full-set eval (every labeled stored listing: Haiku triage + the three agents)")
    full.add_argument("--full", action="store_true", help="run the full-set eval (implied by any flag below)")
    full.add_argument("--stratified", type=int, metavar="N", help="all true positives plus a proportional share of each negative category, N listings in all")
    full.add_argument("--max-usd", type=float, metavar="N", help="stop cleanly before the next listing would pass N dollars of actual spend")
    full.add_argument("--run-id", help="rows go to results/eval_rows/<run-id>.jsonl; the same id resumes")
    full.add_argument("--dry-run", action="store_true", help="show the selection, models, estimate and commands; make no calls")
    full.add_argument("--yes", action="store_true", help="do not ask y/N before spending")
    full.add_argument("--score-only", action="store_true", help="rescore saved rows for --run-id; no calls")
    full.add_argument("--threshold", type=float, metavar="T", help="with --score-only: score the tiered config at this triage threshold (0..1) instead of DL_TRIAGE_THRESHOLD")
    full.add_argument("--concurrency", type=int, default=None, help="listings at once (default 2)")
    return ap


def is_full_mode(args: argparse.Namespace) -> bool:
    return any(bool(getattr(args, k, None)) for k in FULL_FLAGS)


if __name__ == "__main__":
    import sys

    args = build_parser().parse_args()
    if is_full_mode(args):
        from deadlang.eval import full_eval
        args.concurrency = args.concurrency or full_eval.DEFAULT_CONCURRENCY
        sys.exit(asyncio.run(full_eval.main(args)))
    asyncio.run(main(set(args.modes.split(",")), args.limit))
