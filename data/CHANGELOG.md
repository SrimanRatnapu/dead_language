# Data changelog

## dataset v1 — 2026-10-10
- 287 real eBay listings (Browse API, production) + 19 reconstructed listings + 1 hidden relist; 213 sellers.
- Labels: 18 ivory (17 active positives, 3 of them ambiguous by design, + the relist), 78 legal_bone,
  64 legal_resin, 37 tagua, 110 other_legal. Eval set: 17 positives + 40 real negatives (seed 7).
- Demo cases: see `demo_cases.json`. N3 "honest dealer" is seller S0160 (16 real listings, 9 bone, $68–$610).
- Removed by eye (`seed/exclude_real.csv`): 8 listings whose photos carry a seller-username watermark,
  3 unsuitable for a public demo. Dinnerware found by the "vegetable ivory" search is dropped by category.
- Labels fixed by eye (`seed/label_overrides.csv`): 4 bone items the parser read as ivory_color / resin.
- Sellers' own shop names inside listing text are replaced by their pseudonym.
- Only US/JP listings' photos were NOT checked one by one for watermarks; overseas ones were.

Rebuild: `uv run --project backend python scripts/build_dataset.py` (needs `data/raw/`, which is gitignored).

## dataset v2 — 2026-10-10 (more real listings)
- Pulled 209 more real eBay listings (`pull_ebay.py --max 500`): now 479 real listings, 327 sellers. The 20
  reconstructed listings and the eval set size (17 positives + 40 negatives) are unchanged.
- Ids are pinned (`seed/id_map.json`), so every existing listing and all four demo cases kept their ids.
- More comparables moved the "normal price" medians, so the reconstructed listings' prices (a fixed multiple of
  the median) changed. The scripted walkthroughs and the offline UI bundle were regenerated to match.
- Removed by eye from the new batch: 10 with photo watermarks or shop marks, 3 unsuitable, 3 off-topic hits.
  I looked at the first two photos of each new listing only.
- Price at 8x or more: 17 of 17 reconstructed, 19 of 473 real. Linked to another seller: 8 of 479 real.
