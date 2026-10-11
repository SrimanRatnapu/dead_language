"""Examiner accuracy test (plan 03 Task 12): how often do the two Material Examiners get museum photos right?

Run from backend/:
    uv run python -m deadlang.eval.examiner_eval --dry-run              # print the cost estimate only
    uv run python -m deadlang.eval.examiner_eval --modes quick --limit 10
    uv run python -m deadlang.eval.examiner_eval                        # quick, then thorough, on every photo

Each photo in data/museum/museum_labels.csv (a Met Museum object whose medium text gives the true material) is
examined on its own; only the photo is sent, never the label, title or medium. Writes results/examiner_eval.json
(per mode: n, accuracy_on_decisive, cannot_tell_rate, ivory_precision, ivory_recall, confusion matrix) and
results/examiner_eval_rows.jsonl (one row per photo and mode, so a rerun skips photos already done).

It prints an estimated cost and asks before making any real call (--yes skips the question). Calls use case ids
examiner_eval-<mode>-<run>-0, -1, ... (10 photos each). The run id is new every time, so one run's usage never
counts against the next run's per-case caps, and no case holds more than one run's share; the global cap still
applies. If a run stops on a budget, the message says which cap and the sum that did not fit.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from deadlang import config, costs, fileio, llm
from deadlang.llm import BudgetExceeded
from deadlang.schemas import now_iso
from deadlang.specialists import material
from deadlang.specialists.material import QuickExaminer, ThoroughExaminer

MODES = ("quick", "thorough")                # cheap mode first
CALLS_PER_PHOTO = {"quick": 1, "thorough": 2}
SHARD = 10                                    # photos per case id (the per-case caps are 300k in / 30k out)
GIVE_UP_AFTER = 5                             # failures with no success: something systematic (key, model name)
DEFAULT_CONCURRENCY = 3
EXPECTED_OUTPUT_TOKENS = 150                  # one photo's answer
MAX_TOKENS = 1500                             # call_vision_json's default


@dataclass(frozen=True)
class Item:
    object_id: str
    truth: str
    path: Path


# ---------------- reading the set ----------------

def _resolve(image_path: str) -> Path | None:
    for candidate in (config.DATA_DIR / image_path, config.REPO_ROOT / image_path,
                      config.DATA_DIR / "museum" / Path(image_path).name):
        if candidate.is_file():
            return candidate
    return None


def load_items(csv_path: Path) -> tuple[list[Item], list[str]]:
    """(items whose photo exists, object ids whose photo is missing)."""
    items: list[Item] = []
    missing: list[str] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = _resolve(row["image_path"])
            if path is None:
                missing.append(row["object_id"])
            else:
                items.append(Item(row["object_id"], row["label"].strip(), path))
    return items, missing


def select_items(items: list[Item], limit: int | None) -> list[Item]:
    """With a limit, take photos round-robin across labels so a small test run still sees every material."""
    if limit is None or limit >= len(items):
        return items
    by_label: dict[str, list[Item]] = {}
    for item in items:
        by_label.setdefault(item.truth, []).append(item)
    picked: list[Item] = []
    while len(picked) < limit:
        for queue in by_label.values():
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return picked


# ---------------- metrics ----------------

def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def compute_metrics(rows: list[dict]) -> dict:
    decisive = [r for r in rows if r["predicted"] != "cannot_tell"]
    correct = sum(r["predicted"] == r["truth"] for r in decisive)
    called_ivory = [r for r in rows if r["predicted"] == "elephant_ivory"]
    truly_ivory = [r for r in rows if r["truth"] == "elephant_ivory"]
    hits = sum(r["truth"] == "elephant_ivory" for r in called_ivory)
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        confusion[r["truth"]][r["predicted"]] += 1
    return {"n": len(rows), "decisive": len(decisive), "correct": correct,
            "accuracy_on_decisive": _ratio(correct, len(decisive)),
            "cannot_tell_rate": _ratio(len(rows) - len(decisive), len(rows)),
            "ivory_precision": _ratio(hits, len(called_ivory)),
            "ivory_recall": _ratio(hits, len(truly_ivory)),
            "confusion": {truth: dict(counts) for truth, counts in confusion.items()}}


# ---------------- running a mode ----------------

def make_examiner(mode: str):
    return ThoroughExaminer(None) if mode == "thorough" else QuickExaminer(None)   # no marketplace needed here


@dataclass
class EvalResult:
    rows: list[dict] = field(default_factory=list)
    failed: int = 0
    stopped: str | None = None        # "budget" | "errors"
    last_error: str = ""


async def evaluate(mode: str, examiner, items: list[Item], done: set[str], concurrency: int = DEFAULT_CONCURRENCY,
                   on_row=None, run_id: str | None = None) -> EvalResult:
    todo = [i for i in items if i.object_id not in done]
    run_id = run_id or costs.new_run_id()
    result = EvalResult()
    gate = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async def one(position: int, item: Item) -> None:
        async with gate:
            if stop.is_set():
                return
            try:
                (photo,) = await examiner.examine([item.path], case_id=f"examiner_eval-{mode}-{run_id}-{position // SHARD}",
                                                   detail=True)
            except BudgetExceeded as exc:
                result.stopped = result.stopped or "budget"
                result.last_error = result.last_error or str(exc)      # which cap, and the sum that did not fit
                stop.set()
                return
            except Exception as exc:                       # one bad photo should not end the run
                result.failed += 1
                result.last_error = f"{type(exc).__name__}: {exc}"
                if result.failed >= GIVE_UP_AFTER and not result.rows:
                    result.stopped = result.stopped or "errors"
                    stop.set()
                return
            row = {"mode": mode, "object_id": item.object_id, "truth": item.truth,
                   "predicted": photo["material"], "confidence": photo["confidence"],
                   # what the model said it saw, and (thorough) what each of the two looks answered
                   "visible_features": photo["visible_features"], "best_region": photo["best_region"],
                   "looks": photo["looks"] if len(photo["looks"]) > 1 else None}
            result.rows.append(row)
            if on_row:
                on_row(row)

    await asyncio.gather(*(one(p, i) for p, i in enumerate(todo)))
    return result


def plan(mode: str, examiner, items: list[Item], concurrency: int = DEFAULT_CONCURRENCY) -> costs.Batch:
    """Cost of examining `items`. Counts what the model really does: photos at their measured size, output that
    includes thinking for models that think, and the per-case load (calls sharing a case id, and the calls in
    flight that each reserve max_tokens)."""
    photo_tokens = round(sum(llm.estimate_image_tokens(i.path) for i in items) / len(items))
    per_call_in = (llm.estimate_input_tokens(examiner.system, material.USER_MESSAGE, images=1, schema=material.SCHEMA,
                                             image_tokens=photo_tokens) + costs.TOOL_USE_OVERHEAD_TOKENS)
    looks = CALLS_PER_PHOTO[mode]
    return costs.Batch(f"examiner {mode} ({len(items)} photos)", examiner.model, len(items) * looks, per_call_in,
                       costs.expected_output_tokens(examiner.model, EXPECTED_OUTPUT_TOKENS), MAX_TOKENS,
                       calls_per_case=SHARD * looks, concurrency=concurrency * looks)


# ---------------- files ----------------

def read_rows(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass                                       # a half-written last line from an interrupted run
    return rows


def write_results(path: Path, rows: list[dict], items: list[Item], missing: list[str], limit: int | None,
                  label_counts: Counter) -> dict:
    ids = {i.object_id for i in items}
    out: dict = {}
    for mode in MODES:
        mode_rows = [r for r in rows if r["mode"] == mode and r["object_id"] in ids]
        if mode_rows:
            out[mode] = compute_metrics(mode_rows)
    out["meta"] = {"generated_at": now_iso(), "images_in_set": sum(label_counts.values()) + len(missing),
                   "labels": dict(label_counts), "missing_images": missing, "limit": limit,
                   "models": {"quick": config.MODEL_FAST, "thorough": config.MODEL_STRONG}}
    fileio.write_json_atomic(path, out)
    return out


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Measure both Material Examiners on the labeled museum photos.")
    p.add_argument("--modes", default=",".join(MODES), help="comma-separated: quick,thorough (default both)")
    p.add_argument("--limit", type=int, help="use at most this many photos (spread across materials)")
    p.add_argument("--csv", help="label file (default data/museum/museum_labels.csv)")
    p.add_argument("--dry-run", action="store_true", help="print the cost estimate and stop; no calls")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    return p.parse_args(argv)


async def main(argv: list[str] | None = None, *, ask=input) -> int:
    args = parse(argv)
    asked = [m.strip() for m in args.modes.split(",") if m.strip()]
    bad = [m for m in asked if m not in MODES]
    if bad or not asked:
        print(f"Unknown mode(s): {', '.join(bad) or '(none given)'}. Choose from: {', '.join(MODES)}.")
        return 2
    modes = [m for m in MODES if m in asked]

    csv_path = Path(args.csv) if args.csv else config.DATA_DIR / "museum" / "museum_labels.csv"
    if not csv_path.exists():
        print(f"Cannot find {csv_path}. museum_labels.csv is made by scripts/pull_met.py.")
        return 2
    all_items, missing = load_items(csv_path)
    if not all_items:
        print(f"None of the photos listed in {csv_path} could be found on disk.")
        return 2
    label_counts = Counter(i.truth for i in all_items)
    items = select_items(all_items, args.limit)

    results_dir = config.REPO_ROOT / "results"
    rows_path, out_path = results_dir / "examiner_eval_rows.jsonl", results_dir / "examiner_eval.json"
    saved = read_rows(rows_path)
    done = {m: {r["object_id"] for r in saved if r["mode"] == m} for m in modes}
    examiners = {m: make_examiner(m) for m in modes}
    batches = []
    for m in modes:
        left = [i for i in items if i.object_id not in done[m]]
        if left:
            batches.append(plan(m, examiners[m], left, args.concurrency))
    if missing:
        print(f"Note: {len(missing)} listed photo(s) are not on disk and are skipped: {', '.join(missing[:5])}"
              + (" ..." if len(missing) > 5 else ""))

    if not batches:
        write_results(out_path, saved, items, missing, args.limit, label_counts)
        print("Nothing to run: every photo already has a result for these modes "
              f"(delete {rows_path.name} to redo). Results rewritten to {out_path}.")
        return 0
    if args.dry_run:
        print(costs.report(batches))
        print("Dry run: no calls were made.")
        return 0
    if not costs.confirm(batches, assume_yes=args.yes, ask=ask):
        print("No calls were made.")
        return 1

    results_dir.mkdir(parents=True, exist_ok=True)

    def save_row(row: dict) -> None:
        with rows_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    stopped, stop_detail, failed = None, "", 0
    run_id = costs.new_run_id()
    for m in modes:
        result = await evaluate(m, examiners[m], items, done[m], args.concurrency, on_row=save_row, run_id=run_id)
        failed += result.failed
        print(f"{m}: {len(result.rows)} photos done" + (f", {result.failed} failed" if result.failed else ""))
        if result.failed:
            print(f"  last error: {result.last_error}")
        if result.stopped:
            stopped, stop_detail = result.stopped, result.last_error
            break

    out = write_results(out_path, read_rows(rows_path), items, missing, args.limit, label_counts)
    for m in MODES:
        if m in out:
            s = out[m]
            print(f"{m}: n={s['n']}, accuracy on decisive {_pct(s['accuracy_on_decisive'])}, "
                  f"cannot tell {_pct(s['cannot_tell_rate'])}, ivory precision {_pct(s['ivory_precision'])}, "
                  f"ivory recall {_pct(s['ivory_recall'])}")
    print(f"Results written to {out_path}.")
    if stopped == "budget":
        print(f"Stopped early: the token budget was reached ({stop_detail}). What finished is saved; raise the cap "
              "or rerun later to continue (finished photos are skipped).")
    elif stopped == "errors":
        print(f"Stopped early: the first {GIVE_UP_AFTER} calls all failed, so something is wrong "
              "(API key? model name?).")
    return 2 if stopped else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
