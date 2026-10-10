"""Export an offline bundle for the UI: a browse list, its photos, and measured code-only signals.

Run from the repo root:  uv run --project backend python scripts/export_demo.py

Writes frontend/public/stub/listings.json (same shape as GET /api/listings), frontend/public/images/* (only the
photos those rows need) and frontend/public/stub/signals.json. Every number in signals.json is computed here from
the dataset by the real code specialists; nothing is estimated and no model is called.
(Reads data/labels.csv, which only evaluation and demo-curation scripts may do.)
"""
from __future__ import annotations

import asyncio
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from deadlang.marketplace.client import LocalMarketplaceClient  # noqa: E402
from deadlang.marketplace.store import MarketplaceStore  # noqa: E402
from deadlang.schemas import SpecialistCall  # noqa: E402
from deadlang.specialists.network import LinkedSellers  # noqa: E402
from deadlang.specialists.price import PriceChecker  # noqa: E402

DATA, PUBLIC = ROOT / "data", ROOT / "frontend" / "public"
FLAG_AT = 8.0                       # "ivory-level" price: 8x the median of the stated material


async def main() -> None:
    store = MarketplaceStore.from_dir(DATA)
    market = LocalMarketplaceClient(store, DATA)
    demo = json.loads((DATA / "demo_cases.json").read_text())
    with (DATA / "labels.csv").open(newline="") as f:
        planted = {r["listing_id"] for r in csv.DictReader(f) if r["should_flag"] == "true"}
    pricer, tracer = PriceChecker(market), LinkedSellers(market)

    async def one(specialist, listing_id):
        reply = await specialist.run(SpecialistCall(case_id="export", listing_id=listing_id,
                                                    capability=specialist.capability))
        return reply.drafts[0].data

    active = store.active_listings()
    facts = {}
    for l in active:
        price, links = await one(pricer, l.id), await one(tracer, l.id)
        facts[l.id] = {"ratio": price["ratio"], "n": price["n"], "weak": price["weak_comparison"],
                       "linked": links["linked_seller_count"]}

    def triage(l) -> dict | None:
        f = facts[l.id]
        if f["ratio"] is None:
            return None
        what = l.stated_material.replace("_", " ") + ("" if f["weak"] else f" {l.item_type}")
        reason = f"Priced {f['ratio']}x the median for {what} listings"
        if f["linked"]:
            reason += f"; {f['linked']} linked seller{'s' if f['linked'] != 1 else ''}"
        return {"score": round(min(f["ratio"] / 10, 1.0), 2), "reason": reason}

    # ---- browse list: the demo cases, every planted case, the priciest real listings, some ordinary ones
    real = [l for l in active if l.id not in planted and facts[l.id]["ratio"] is not None and l.image_paths]
    by_ratio = sorted(real, key=lambda l: -facts[l.id]["ratio"])
    ordinary = [l for l in real if 0.6 <= facts[l.id]["ratio"] <= 1.6 and l.stated_material in ("bone", "tagua", "resin")]
    chosen = {lid: None for lid in demo.values()}
    for l in [l for l in active if l.id in planted] + by_ratio[:6] + ordinary[:8]:
        chosen.setdefault(l.id, None)
    rows = [{"listing": store.get_listing(lid).model_dump(mode="json"),
             "seller": store.get_seller(store.get_listing(lid).seller_id).model_dump(mode="json"),
             "triage": triage(store.get_listing(lid))} for lid in chosen]
    rows.sort(key=lambda r: -(r["triage"] or {"score": 0})["score"])
    (PUBLIC / "stub").mkdir(parents=True, exist_ok=True)
    (PUBLIC / "stub" / "listings.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")

    # ---- photos for those rows, plus the hidden relist the removed-listing case reveals
    shutil.rmtree(PUBLIC / "images", ignore_errors=True)
    (PUBLIC / "images").mkdir(parents=True)
    relist = next(l for l in store._listings.values() if l.relist_of)
    wanted = {p for r in rows for p in r["listing"]["image_paths"]} | set(relist.image_paths)
    for rel in sorted(wanted):
        shutil.copyfile(DATA / rel, PUBLIC / rel)

    # ---- measured signals
    priced_real = [l for l in active if l.id not in planted and facts[l.id]["ratio"] is not None]
    priced_planted = [l for l in active if l.id in planted and facts[l.id]["ratio"] is not None]
    all_real = [l for l in active if l.id not in planted and not l.is_reconstructed]
    network = [l for l in active if l.id in planted and facts[l.id]["linked"]]
    signals = {
        "generated_by": "scripts/export_demo.py",
        "dataset": {"real_listings": len(all_real), "planted_cases": len(planted & {l.id for l in active}),
                    "sellers": len({l.seller_id for l in active}),
                    "eval_set": len((DATA / "eval_set.txt").read_text().split()),
                    "museum_photos": sum(1 for _ in (DATA / "museum").glob("*.jpg"))},
        "price": {
            "flag_at": FLAG_AT,
            "planted_flagged": sum(facts[l.id]["ratio"] >= FLAG_AT for l in priced_planted),
            "planted_total": len(priced_planted),
            "real_flagged": sum(facts[l.id]["ratio"] >= FLAG_AT for l in priced_real),
            "real_total": len(priced_real),
            "planted_ratios": sorted(facts[l.id]["ratio"] for l in priced_planted),
            "real_ratios": sorted(facts[l.id]["ratio"] for l in priced_real)},
        "links": {"real_linked": sum(facts[l.id]["linked"] > 0 for l in all_real), "real_total": len(all_real),
                  "planted_linked": len(network)},
    }
    (PUBLIC / "stub" / "signals.json").write_text(json.dumps(signals, indent=1) + "\n")
    p = signals["price"]
    print(f"rows: {len(rows)}   photos: {len(wanted)}   dataset: {signals['dataset']}")
    print(f"price >= {FLAG_AT}x: planted {p['planted_flagged']}/{p['planted_total']}, "
          f"real {p['real_flagged']}/{p['real_total']}   links: {signals['links']}")


if __name__ == "__main__":
    asyncio.run(main())
