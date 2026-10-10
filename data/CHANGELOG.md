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
