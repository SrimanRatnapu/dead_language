"""Build the fixed dataset from raw pulls + hand-written seeds. Idempotent: rebuilds every output.

Run from the repo root:  uv run --project backend python scripts/build_dataset.py

Inputs : data/raw/{ebay,manual}/*.json (real listings; see pull_ebay.py / ingest_manual_csv.py),
         data/raw/met/ and data/museum/ (CC0 photos; see pull_met.py),
         data/seed/reconstructed.yaml, data/seed/networks.yaml, optional data/seed/label_overrides.csv
         and data/seed/exclude_real.csv
Outputs: data/listings.jsonl, data/sellers.jsonl, data/labels.csv, data/images/*, data/eval_set.txt,
         data/demo_cases.json, data/phash_cache.json, data/raw/seller_map.json (real handle -> pseudonym)

Ids are assigned in a stable order that reveals nothing: sorted by a hash of "<source>:<source id>".
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from deadlang.schemas import Label, Listing, Seller  # noqa: E402
from deadlang.textparse import item_type, stated_material  # noqa: E402

DATA = ROOT / "data"
RAW, SEED, IMAGES = DATA / "raw", DATA / "seed", DATA / "images"
SALT = "deadlang"
MIN_REAL = 60                      # refuse to build a dataset with too few real listings to compare against
REAL_TRUTH = {"tagua": "tagua", "resin": "legal_resin", "ivory_color": "legal_resin", "bone": "legal_bone",
              "wood": "other_legal", "unknown": "other_legal", "ivory_mentioned": "other_legal"}
EVAL_NEGATIVES = [("tagua", 15), ("legal_bone", 15), ("legal_resin+other_legal", 10)]
EVAL_SEED = 7


def stable_order(keys) -> list[str]:
    return sorted(keys, key=lambda k: hashlib.sha1(k.encode()).hexdigest())


def pseudonym(handle: str) -> str:
    return "seller_" + hashlib.sha1((handle + SALT).encode()).hexdigest()[:6]


def save_image(src: Path, dest: Path, max_side: int = 800) -> None:
    """Copy as JPEG: longest side <= 800 px, quality 85 (lower only if needed to stay <= 300 KB)."""
    img = Image.open(src).convert("RGB")
    img.thumbnail((max_side, max_side))
    for quality in (85, 75, 65, 55, 45):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= 300_000:
            break
    dest.write_bytes(buf.getvalue())


def photo_source(ref: str) -> Path:
    """"met:60310_0" -> data/raw/met/60310_0.jpg ; "museum:59199" -> data/museum/59199.jpg"""
    kind, name = ref.split(":")
    path = (RAW / "met" if kind == "met" else DATA / "museum") / f"{name}.jpg"
    if not path.exists():
        raise SystemExit(f"seed photo {ref} not found at {path} (run scripts/pull_met.py)")
    return path


def redact(text: str, handle: str) -> str:
    """Sellers often name their own shop in the text; replace that with the pseudonym."""
    if len(handle) < 7 and handle.isalpha():
        return text                                    # too word-like to replace safely (e.g. "grade")
    return re.sub(rf"(?<![A-Za-z0-9]){re.escape(handle)}(?![A-Za-z0-9])", pseudonym(handle), text, flags=re.I)


def load_real() -> list[dict]:
    excluded = set()                                   # real listings removed by eye, with the reason
    if (SEED / "exclude_real.csv").exists():
        with (SEED / "exclude_real.csv").open(newline="") as f:
            excluded = {(row["source"], row["source_id"]) for row in csv.DictReader(f)}
    records = []
    for source in ("ebay", "manual"):
        for path in sorted((RAW / source).glob("*.json")):
            r = json.loads(path.read_text())
            if (r["source"], r["source_id"]) in excluded or (r.get("category") or "").startswith("Pottery & Glass"):
                continue                               # "vegetable ivory" also finds ivory-coloured dinnerware
            if r.get("title") and r.get("seller_handle") and float(r.get("price_usd") or 0) > 0:
                r["title"] = redact(r["title"], r["seller_handle"])
                r["description"] = redact(r["description"], r["seller_handle"])
                records.append(r)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-few-real", action="store_true",
                        help=f"build even with fewer than {MIN_REAL} real listings (for dry runs only)")
    args = parser.parse_args()

    real = load_real()
    print(f"real listings: {len(real)}  {dict(Counter(r['source'] for r in real))}")
    if len(real) < MIN_REAL and not args.allow_few_real:
        raise SystemExit(f"Only {len(real)} real listings in data/raw. The dataset needs at least {MIN_REAL} "
                         "(prices are judged against them). Run scripts/pull_ebay.py with production keys or "
                         "scripts/ingest_manual_csv.py, or pass --allow-few-real for a dry run.")
    recon = yaml.safe_load((SEED / "reconstructed.yaml").read_text())
    net = yaml.safe_load((SEED / "networks.yaml").read_text())
    relist = net["relist"]
    by_key = {e["key"]: e for e in recon}
    assert len(by_key) == len(recon), "duplicate keys in reconstructed.yaml"
    assert relist["of"] in by_key and relist["key"] not in by_key

    # ---- ids: stable, and unrelated to where a listing came from
    listing_keys = ([f"{r['source']}:{r['source_id']}" for r in real] + [f"seed:{e['key']}" for e in recon]
                    + [f"seed:{relist['key']}"])
    assert len(set(listing_keys)) == len(listing_keys), "duplicate listing source ids"
    listing_id = {k: f"L{n:04d}" for n, k in enumerate(stable_order(listing_keys), start=1)}
    seller_keys = {f"real:{r['seller_handle']}" for r in real} | {f"seed:{k}" for k in net["sellers"]}
    seller_id = {k: f"S{n:04d}" for n, k in enumerate(stable_order(seller_keys), start=1)}

    for old in IMAGES.glob("*.jpg"):
        old.unlink()
    IMAGES.mkdir(parents=True, exist_ok=True)
    listings: list[Listing] = []
    labels: dict[str, Label] = {}

    # ---- Step A: real listings
    for r in real:
        lid = listing_id[f"{r['source']}:{r['source_id']}"]
        paths = []
        for src in r.get("images", [])[:3]:
            if (RAW / src).exists():
                rel = f"images/{lid}_{len(paths)}.jpg"
                save_image(RAW / src, DATA / rel)
                paths.append(rel)
        material = stated_material(r["title"], r["description"])
        listings.append(Listing(
            id=lid, marketplace=r["source"], seller_id=seller_id[f"real:{r['seller_handle']}"], title=r["title"],
            description=r["description"], price_usd=round(float(r["price_usd"]), 2), category=r.get("category") or "",
            stated_material=material, item_type=item_type(r["title"], r["description"]),
            ship_from=r.get("ship_from") or "US", image_paths=paths,
            posted_at=r.get("posted_at") or "2026-10-01T00:00:00+00:00", source_url=r.get("source_url")))
        note = "parser saw the word ivory; check by eye" if material == "ivory_mentioned" else ""
        labels[lid] = Label(listing_id=lid, truth=REAL_TRUTH[material], should_flag=False, notes=note)
    real_listings = list(listings)

    def normal_price(material: str, kind: str) -> float:
        """Median real price for this material + type (the same comparison the Price Checker makes)."""
        same = [l.price_usd for l in real_listings if l.stated_material == material]
        both = [l.price_usd for l in real_listings if l.stated_material == material and l.item_type == kind]
        pool = both if len(both) >= 5 else same if len(same) >= 5 else [l.price_usd for l in real_listings]
        return statistics.median(pool) if pool else 95.0

    # ---- Steps B + C: reconstructed listings, networks, the hidden relist
    def add_seed(entry: dict, base: dict | None = None) -> Listing:
        e = {**(base or {}), **entry}
        lid = listing_id[f"seed:{entry['key']}"]
        material, kind = stated_material(e["title"], e["description"]), item_type(e["title"], e["description"])
        assert (material, kind) == (e["material"], e["type"]), \
            f"{e['key']}: text parses as {material}/{kind}, seed says {e['material']}/{e['type']}"
        paths = []
        for ref in e["photos"]:
            rel = f"images/{lid}_{len(paths)}.jpg"
            save_image(photo_source(ref), DATA / rel, e.get("photo_max_side", 800))
            paths.append(rel)
        price = max(5.0, round(e["price_ratio"] * normal_price(material, kind) / 5) * 5.0)
        listing = Listing(
            id=lid, marketplace="reconstructed", seller_id=seller_id[f"seed:{e['seller']}"], title=e["title"].strip(),
            description=" ".join(e["description"].split()), price_usd=price, category=e["category"],
            stated_material=material, item_type=kind, size_cm=e.get("size_cm"), weight_g=e.get("weight_g"),
            ship_from=e["ship_from"], language=e.get("language", "en"), image_paths=paths, posted_at=e["posted_at"],
            is_reconstructed=True, reconstruction_source=e["source"])
        listings.append(listing)
        note = "ambiguous by design" if e.get("ambiguous") else ""
        labels[lid] = Label(listing_id=lid, truth=e["truth"], should_flag=e["truth"] == "ivory", notes=note)
        return listing

    for entry in recon:
        assert entry["seller"] in net["sellers"], f"{entry['key']}: unknown seller {entry['seller']}"
        add_seed(entry)
    original = by_key[relist["of"]]
    hidden = add_seed({**relist, "photos": original["photos"][:1]}, base=original)
    hidden.status, hidden.relist_of = "hidden", listing_id[f"seed:{relist['of']}"]

    # ---- label fixes found by eye (fix the label, never the listing)
    overrides = SEED / "label_overrides.csv"
    if overrides.exists():
        with overrides.open(newline="") as f:
            for row in csv.DictReader(f):
                lid = listing_id.get(f"{row['source']}:{row['source_id']}")
                if lid:
                    labels[lid] = Label(listing_id=lid, truth=row["truth"],
                                        should_flag=row["should_flag"].strip().lower() == "true",
                                        notes=row.get("notes", ""))

    # ---- sellers (real names never leave data/raw)
    first_seen: dict[str, str] = {}
    for l in listings:
        first_seen[l.seller_id] = min(first_seen.get(l.seller_id, l.posted_at), l.posted_at)
    sellers, seller_map = [], {}
    for handle in sorted({r["seller_handle"] for r in real}):
        rows = [r for r in real if r["seller_handle"] == handle]
        sid = seller_id[f"real:{handle}"]
        seller_map[handle] = pseudonym(handle)
        sellers.append(Seller(id=sid, name=pseudonym(handle), joined=first_seen[sid],   # eBay gives no join date
                              location=rows[0].get("seller_location") or rows[0].get("ship_from") or "US",
                              feedback_score=rows[0].get("seller_feedback")))
    for key, s in net["sellers"].items():
        sellers.append(Seller(id=seller_id[f"seed:{key}"], name=pseudonym(s["handle"]), location=s["location"],
                              joined=s["joined"], feedback_score=s.get("feedback_score")))
    assert len({s.name for s in sellers}) == len(sellers), "pseudonym collision; change a seed handle"
    assert not {s.name for s in sellers} & set(seller_map), "a pseudonym equals a real username"

    # ---- eval set: every reconstructed ivory case + 40 real negatives, stratified, seed 7
    rng = random.Random(EVAL_SEED)
    real_ids = {l.id for l in real_listings}
    eval_ids = sorted(lid for lid, lab in labels.items() if lab.should_flag and lid != hidden.id)
    for truths, n in EVAL_NEGATIVES:
        pool = sorted(lid for lid in real_ids if labels[lid].truth in truths.split("+"))
        if len(pool) < n:
            print(f"WARNING: only {len(pool)} real {truths} listings for the eval set (wanted {n})")
        eval_ids += rng.sample(pool, min(n, len(pool)))

    # ---- demo cases
    demo = dict(net["demo"])
    for name in ("d1_network", "d3_removed", "d4_ambiguous"):
        demo[name] = listing_id[f"seed:{demo[name]}"]
    if demo.get("d2_tagua") in (None, "auto"):
        tagua = [l for l in real_listings if l.stated_material == "tagua" and l.item_type == "figurine"
                 and l.image_paths]
        median = statistics.median([l.price_usd for l in tagua]) if tagua else 0
        fits = sorted((l for l in tagua if 0.5 * median <= l.price_usd <= 1.5 * median),
                      key=lambda l: (-len(l.image_paths), l.id))
        demo["d2_tagua"] = fits[0].id if fits else None
        print("d2_tagua candidates (check the photos by eye):", [l.id for l in fits[:8]])
    else:
        demo["d2_tagua"] = listing_id[demo["d2_tagua"]]

    # ---- write
    listings.sort(key=lambda l: l.id)
    sellers.sort(key=lambda s: s.id)
    (DATA / "listings.jsonl").write_text("".join(l.model_dump_json() + "\n" for l in listings))
    (DATA / "sellers.jsonl").write_text("".join(s.model_dump_json() + "\n" for s in sellers))
    with (DATA / "labels.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["listing_id", "truth", "should_flag", "notes"])
        for lid in sorted(labels):
            lab = labels[lid]
            writer.writerow([lab.listing_id, lab.truth, str(lab.should_flag).lower(), lab.notes])
    (DATA / "eval_set.txt").write_text("".join(f"{lid}\n" for lid in eval_ids))
    (DATA / "demo_cases.json").write_text(json.dumps(demo, indent=2) + "\n")
    RAW.mkdir(exist_ok=True)
    (RAW / "seller_map.json").write_text(json.dumps(seller_map, indent=1, sort_keys=True))

    # ---- photo-hash cache, built by the specialist that uses it
    from deadlang.marketplace.client import LocalMarketplaceClient
    from deadlang.marketplace.store import MarketplaceStore
    from deadlang.schemas import SpecialistCall
    from deadlang.specialists.network import LinkedSellers
    (DATA / "phash_cache.json").unlink(missing_ok=True)
    market = LocalMarketplaceClient(MarketplaceStore.from_dir(DATA), DATA)
    asyncio.run(LinkedSellers(market).run(
        SpecialistCall(case_id="build", listing_id=hidden.id, capability="linked_sellers")))

    # ---- report
    print(f"listings: {len(listings)} ({len(real_listings)} real, {len(listings) - len(real_listings)} reconstructed, "
          f"1 hidden relist)   sellers: {len(sellers)}   eval set: {len(eval_ids)}")
    print("truth labels:", dict(Counter(lab.truth for lab in labels.values())))
    print("stated material (real):", dict(Counter(l.stated_material for l in real_listings)))
    print("demo cases:", demo)
    per_seller = defaultdict(list)
    for l in real_listings:
        per_seller[l.seller_id].append(l)
    honest = sorted(((sum(l.stated_material in ("bone", "tagua") for l in ls), sid) for sid, ls in per_seller.items()
                     if len(ls) >= 4 and sum(l.stated_material in ("bone", "tagua") for l in ls) >= 0.7 * len(ls)),
                    reverse=True)
    print("N3 honest-dealer candidates (bone/tagua count, seller):", honest[:5])


if __name__ == "__main__":
    main()
