"""Triage scores for the browse page (plan 03 Task 11): a cheap first look at every active listing.

Run from the repo root:
    uv run --project backend python scripts/compute_triage.py --dry-run     # print the cost estimate only
    uv run --project backend python scripts/compute_triage.py --limit 10    # try 10 listings first
    uv run --project backend python scripts/compute_triage.py               # all listings

Per listing: a fast-model read of the text only (title, description, price, stated material, item type; no
photos) gives text_suspicion 0-1, and Price Checker gives how many times the median price it is. The score is
half of each. Output: data/triage.json  {listing_id: {"score", "reason", "price_ratio"}}.

It prints an estimated cost and asks before making any real call (--yes skips the question). Listings already
in triage.json are skipped (--force redoes them). Calls are spread over case ids triage-0, triage-1, ... so the
per-case token cap does not cut a long run short; the global cap still applies.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))   # so `python scripts/...` finds deadlang

from deadlang import config, costs, fileio, llm  # noqa: E402
from deadlang.llm import BudgetExceeded  # noqa: E402
from deadlang.schemas import Listing, SpecialistCall  # noqa: E402

SYSTEM = ("You screen marketplace listings for possible disguised elephant ivory. Read it as an experienced "
          "collector would: does anything about the price, wording, or details only make sense if the item "
          "were ivory? Most listings are innocent; give low scores unless something specific stands out.")
SCHEMA_NAME = "report_triage"
SCHEMA = {"type": "object",
          "properties": {"text_suspicion": {"type": "number", "minimum": 0, "maximum": 1},
                         "reason": {"type": "string", "description": "One sentence."}},
          "required": ["text_suspicion", "reason"]}

SHARD = 50                    # listings per case id, so each stays far below the per-case token caps
GIVE_UP_AFTER = 5             # failures in a row with no success means something systematic (key, model name)
DEFAULT_CONCURRENCY = 4
EXPECTED_OUTPUT_TOKENS = 80   # typical: a number and one sentence
MAX_TOKENS = 200
TOOL_OVERHEAD_TOKENS = 150    # the tool definition and tool instruction that llm.py adds to each request


def listing_text(listing: Listing) -> str:
    return (f"Title: {listing.title}\nDescription: {listing.description}\nPrice: ${listing.price_usd:,.0f}\n"
            f"Stated material: {listing.stated_material}\nItem type: {listing.item_type}")


def combine(text_suspicion: float, price_ratio: float) -> float:
    return round(0.5 * text_suspicion + 0.5 * min(price_ratio / 10, 1), 2)


async def price_ratio_for(price_checker, listing: Listing, case_id: str) -> float:
    reply = await price_checker.run(SpecialistCall(case_id=case_id, listing_id=listing.id, capability="price_check"))
    if reply.ok and reply.drafts:
        ratio = reply.drafts[0].data.get("ratio")
        if ratio is not None:
            return float(ratio)
    return 0.0                # no comparables


async def score_listing(listing: Listing, price_checker, case_id: str) -> dict:
    out = await llm.call_json(model=config.MODEL_FAST, system=SYSTEM, user=listing_text(listing),
                              schema_name=SCHEMA_NAME, schema=SCHEMA, case_id=case_id, max_tokens=MAX_TOKENS)
    suspicion = min(max(float(out["text_suspicion"]), 0.0), 1.0)
    ratio = await price_ratio_for(price_checker, listing, case_id)
    return {"score": combine(suspicion, ratio), "reason": str(out.get("reason") or "").strip(),
            "price_ratio": ratio}


@dataclass
class TriageResult:
    scores: dict[str, dict] = field(default_factory=dict)
    failed: int = 0
    stopped: str | None = None        # "budget" | "errors"
    last_error: str = ""


async def compute(listings: list[Listing], price_checker, concurrency: int = DEFAULT_CONCURRENCY) -> TriageResult:
    result = TriageResult()
    gate = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async def one(i: int, listing: Listing) -> None:
        async with gate:
            if stop.is_set():
                return
            try:
                result.scores[listing.id] = await score_listing(listing, price_checker, f"triage-{i // SHARD}")
            except BudgetExceeded:
                result.stopped = result.stopped or "budget"
                stop.set()
            except Exception as exc:                         # one bad listing should not end the run
                result.failed += 1
                result.last_error = f"{type(exc).__name__}: {exc}"
                if result.failed >= GIVE_UP_AFTER and not result.scores:
                    result.stopped = result.stopped or "errors"
                    stop.set()

    await asyncio.gather(*(one(i, l) for i, l in enumerate(listings)))
    return result


def pending(active: list[Listing], existing: dict, limit: int | None, force: bool) -> list[Listing]:
    todo = [l for l in sorted(active, key=lambda l: l.id) if force or l.id not in existing]
    return todo[:limit] if limit else todo


def plan(todo: list[Listing]) -> list[costs.Batch]:
    avg_in = round(sum(llm.estimate_input_tokens(SYSTEM, listing_text(l)) for l in todo) / len(todo))
    return [costs.Batch("triage (text only)", config.MODEL_FAST, len(todo), avg_in + TOOL_OVERHEAD_TOKENS,
                        EXPECTED_OUTPUT_TOKENS, MAX_TOKENS)]


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute triage scores for every active listing.")
    p.add_argument("--limit", type=int, help="score at most this many listings")
    p.add_argument("--force", action="store_true", help="re-score listings that already have a score")
    p.add_argument("--dry-run", action="store_true", help="print the cost estimate and stop; no calls")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    return p.parse_args(argv)


async def main(argv: list[str] | None = None, *, market=None, price_checker=None, ask=input) -> int:
    args = parse(argv)
    out_path = config.DATA_DIR / "triage.json"
    existing = json.loads(out_path.read_text()) if out_path.exists() else {}
    try:
        if market is None:
            from deadlang.marketplace.client import get_marketplace_client
            market = get_marketplace_client()
        active = await market.all_active()
    except FileNotFoundError as exc:
        print(f"Cannot read the marketplace data ({exc.filename or exc}). Build the dataset first "
              "(scripts/build_dataset.py).")
        return 2
    if price_checker is None:
        from deadlang.specialists.price import PriceChecker
        price_checker = PriceChecker(market)

    todo = pending(active, existing, args.limit, args.force)
    if not todo:
        print(f"Nothing to score: {len(active)} active listings, {len(existing)} already have a score "
              "(use --force to redo them).")
        return 0
    batches = plan(todo)
    if args.dry_run:
        print(costs.report(batches))
        print("Dry run: no calls were made.")
        return 0
    if not costs.confirm(batches, assume_yes=args.yes, ask=ask):
        print("No calls were made.")
        return 1

    result = await compute(todo, price_checker, args.concurrency)
    if result.scores:
        fileio.write_json_atomic(out_path, dict(sorted({**existing, **result.scores}.items())))
    print(f"Scored {len(result.scores)} of {len(todo)} listings ({result.failed} failed)"
          + (f"; saved to {out_path}." if result.scores else "; nothing saved."))
    if result.failed:
        print(f"Last error: {result.last_error}")
    if result.stopped == "budget":
        print("Stopped early: the token budget was reached. What was scored is saved; raise the cap or rerun "
              "later to continue (finished listings are skipped).")
    elif result.stopped == "errors":
        print(f"Stopped early: the first {GIVE_UP_AFTER} calls all failed, so something is wrong (API key? "
              "model name?).")
    return 2 if result.stopped else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
