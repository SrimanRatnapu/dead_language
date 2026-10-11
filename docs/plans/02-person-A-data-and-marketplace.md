# Person A — Data & Marketplace Build Plan

> Read `00-watchdog-design-spec.md` and `01-shared-contracts-and-kickoff.md` first. This plan assumes both.
> Steps use `- [ ]` checkboxes. Each task ends with tests passing and a commit prefixed `data:`.

**Goal:** Produce the fixed dataset (real look-alikes + reconstructed trafficking cases + seller networks + labels), serve it as a marketplace over MCP, and build the four code-only specialists (price check, seller inventory, linked sellers, legal lookup).
**Architecture:** Scripts turn raw eBay/Met/manual data into `data/listings.jsonl` and `data/sellers.jsonl`. `MarketplaceStore` loads them into memory; a FastMCP server exposes them as marketplace tools; `MarketplaceClient` lets everyone else read them over MCP or in-process. Code specialists implement the `Specialist` protocol and return `EvidenceDraft`s.
**Tech Stack:** Python 3.12, uv, httpx, pydantic v2, MCP Python SDK (FastMCP), Pillow, imagehash, pytest.

## Global Constraints (in addition to file 01)

- No model calls anywhere in your code. Everything you produce is deterministic.
- **Pseudonymize real sellers.** Real eBay usernames never appear in `sellers.jsonl`, the UI, or slides. Seller display names are generated like `seller_7f3a2c` (first 6 hex chars of sha1 of the real username + a fixed salt `deadlang`). Keep the mapping only in `data/raw/` (gitignored).
- Images: max 3 per listing, longest side ≤ 800 px, JPEG quality 85, each ≤ 300 KB. Path pattern `images/<listing_id>_<n>.jpg`.
- IDs: listings `L0001`…, sellers `S0001`…, zero-padded to 4 digits, assigned in a stable order (sorted by source + source id) so re-running the build doesn't reshuffle IDs.
- Every number that appears in an `EvidenceDraft.summary` must also appear in its `data` (the validator in Person C's code depends on this).
- `labels.csv` is the only place ground truth lives. Never put truth hints in titles, descriptions, ids, file names or seller names.

## Files you own

`scripts/pull_ebay.py`, `scripts/pull_met.py`, `scripts/ingest_manual_csv.py`, `scripts/build_dataset.py`, `backend/deadlang/textparse.py`, `backend/deadlang/marketplace/{store.py,server.py,client.py}`, `backend/deadlang/specialists/{price.py,network.py,legal.py}`, everything under `data/`, tests `backend/tests/test_textparse.py`, `test_store.py`, `test_marketplace_client.py`, `test_price.py`, `test_network.py`, `test_legal.py`.

---

### Task 1: Text parsing (stated material and item type)

**Files:** Create `backend/deadlang/textparse.py` · Test `backend/tests/test_textparse.py`

**Interfaces — Produces:**
- `stated_material(title: str, description: str) -> StatedMaterial`
- `item_type(title: str, description: str) -> ItemType`

**Behavior:** lowercase title+description, apply regex rules in order, first match wins.

| Order | Pattern (word-boundary regex) | stated_material |
|---|---|---|
| 1 | `tagua`, `vegetable ivory`, `corozo` | `tagua` |
| 2 | `faux`, `imitation`, `resin`, `polyresin`, `plastic`, `celluloid` | `resin` |
| 3 | `ivory` followed by `color`/`colour`/`colored`/`tone`/`white`/`finish` (space or hyphen) | `ivory_color` |
| 4 | `bone`, `bovine`, `ox bone`, `cow bone`, `camel bone` | `bone` |
| 5 | `boxwood`, `wood`, `wooden` | `wood` |
| 6 | `ivory` | `ivory_mentioned` |
| – | none | `unknown` |

| Order | Pattern | item_type |
|---|---|---|
| 1 | `netsuke` | `netsuke` |
| 2 | `bangle`, `bracelet`, `bead(s)`, `necklace`, `pendant`, `mala`, `ring`, `earring(s)` | `jewelry` |
| 3 | `okimono`, `figurine`, `figure`, `statue`, `carving`, `sculpture` | `figurine` |
| – | none | `other` |

- [ ] Step 1: Write failing tests (one assert each):
  - `("Vegetable ivory netsuke", "")` → `tagua`, `netsuke`
  - `("Carved figure", "hand carved from ox bone")` → `bone`, `figurine`
  - `("Ivory-colored resin bangle", "")` → `resin` (rule 2 beats rule 3), `jewelry`
  - `("Ivory tone bead necklace", "")` → `ivory_color`, `jewelry`
  - `("Old netsuke", "boxwood")` → `wood`, `netsuke`
  - `("Antique carving", "")` → `unknown`, `figurine`
  - `("Mammoth ivory?", "")` → `ivory_mentioned`
- [ ] Step 2: Run `cd backend && uv run pytest tests/test_textparse.py -v` → FAIL (not defined).
- [ ] Step 3: Implement the two functions with the tables above.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `data: textparse rules`.

---

### Task 2: Pull real look-alike listings from eBay (with manual fallback)

**Files:** Create `scripts/pull_ebay.py`, `scripts/ingest_manual_csv.py`, `data/raw/` (gitignored), `data/manual_listings_template.csv`

**Time box: 90 minutes.** If eBay production keys are not working within 30 minutes, switch to the manual path and do not come back to eBay.

**eBay path (Browse API):**
- Env: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` (production keyset from developer.ebay.com). Note: eBay may require you to handle or opt out of "marketplace account deletion notifications" before production keys activate; if that blocks you, go manual.
- Token: `POST https://api.ebay.com/identity/v1/oauth2/token`, HTTP Basic auth with `client_id:client_secret`, form body `grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope`. Cache the token for its lifetime.
- Search: `GET https://api.ebay.com/buy/browse/v1/item_summary/search?q=<query>&limit=100`, header `X-EBAY-C-MARKETPLACE-ID: EBAY_US`. Queries (run each, dedupe by itemId): `netsuke bone`, `bone carving figurine`, `carved bone netsuke antique`, `tagua carving`, `vegetable ivory`, `resin netsuke`, `faux ivory bangle`, `ivory color resin figurine`, `bone bead necklace carved`, `antique bone carving chinese`, `okimono carving`, `boxwood netsuke`.
- Details: for each item, `GET https://api.ebay.com/buy/browse/v1/item/{itemId}`. Keep: `title`, `shortDescription` or `description` (strip HTML to text, collapse whitespace, cut to 1,500 chars), `price.value`/`price.currency` (skip non-USD), `image.imageUrl` + first 2 `additionalImages`, `seller.username`, `seller.feedbackScore`, `itemLocation.stateOrProvince`/`country`, `categoryPath`, `itemWebUrl`, `itemCreationDate` if present.
- Seller inventories: pick the 15 sellers with the most hits and, for each, run search with `filter=sellers:{<username>}` and `q=carving` (the Browse API needs a q); add those items too. One of these sellers with mostly real bone/tagua at normal prices becomes network **N3 "honest dealer"**.
- Save raw JSON per item to `data/raw/ebay/<itemId>.json`. Download images to `data/raw/ebay_images/`.
- Target: 200–300 items. Stop at 300.

**Manual path:** `data/manual_listings_template.csv` columns: `source_url,title,description,price_usd,seller_handle,seller_location,ship_from,category,image_url_1,image_url_2,image_url_3,posted_at`. Two people can fill ~60 rows in ~1 hour from public marketplace pages (any site). `scripts/ingest_manual_csv.py` downloads images and writes the same raw format as the eBay path (`data/raw/manual/<row_n>.json`).

- [ ] Step 1: Write `pull_ebay.py` with `--max 300` and `--dry-run` (prints counts only).
- [ ] Step 2: Run `uv run python scripts/pull_ebay.py --dry-run --max 20` → prints items found per query.
- [ ] Step 3: Run full pull. Verify: `ls data/raw/ebay | wc -l` ≥ 150.
- [ ] Step 4: (Only if eBay failed) write `ingest_manual_csv.py`, fill CSV, run it.
- [ ] Step 5: Commit scripts and template (not raw data) `data: ebay + manual ingestion`.

---

### Task 3: Pull museum images (Met Open Access, CC0)

**Files:** Create `scripts/pull_met.py`, `data/museum/<objectID>.jpg`, `data/museum/museum_labels.csv`

**Purpose:** (a) photos of genuine ivory for reconstructed listings, (b) a labeled photo set for measuring the Material Examiner (Person B uses it).

- API: `GET https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q=<q>` returns `objectIDs`; `GET https://collectionapi.metmuseum.org/public/collection/v1/objects/<id>` returns `isPublicDomain`, `primaryImageSmall`, `primaryImage`, `medium`, `title`, `objectDate`, `objectURL`.
- Queries: `netsuke ivory`, `okimono ivory`, `netsuke bone`, `netsuke wood`, `netsuke stag antler`, `carved bone`.
- Keep only `isPublicDomain == true` with a non-empty `primaryImageSmall`.
- Label from `medium` (lowercase): contains `ivory` and not `vegetable` → `elephant_ivory`; contains `bone` → `bone`; contains `wood` → `wood`; contains `antler` → `other`; else skip. Skip objects whose medium mentions more than one of these.
- Target: 20 ivory, 10 bone, 10 wood (+ any antler). Rate-limit to 5 requests/second.
- `museum_labels.csv` columns: `object_id,label,medium,title,object_url,image_path`.

- [ ] Step 1: Write script with `--per-label` caps.
- [ ] Step 2: Run; verify counts per label printed.
- [ ] Step 3: Open 5 images by eye to confirm they are the right objects.
- [ ] Step 4: Commit `data: met museum set`.

---

### Task 4: Build the dataset (listings, sellers, reconstructed cases, networks, relist, labels)

**Files:** Create `scripts/build_dataset.py`, `data/seed/reconstructed.yaml`, `data/seed/networks.yaml` · Output `data/listings.jsonl`, `data/sellers.jsonl`, `data/labels.csv`, `data/images/*`, `data/eval_set.txt`, `data/demo_cases.json`

**Step A — real listings → `Listing`:** for each raw item: assign ids (Global Constraints), parse `stated_material` and `item_type` with `textparse`, `ship_from` = `US-<state code>` for US items else country code, `language="en"`, resize/copy images to `data/images/`, `is_reconstructed=false`. Sellers from real usernames → pseudonymized `Seller` rows.

**Step B — reconstructed trafficking cases (`data/seed/reconstructed.yaml`).** Write these by hand with Person D (they own the story). 15–20 entries. Rules:
- Base them on the patterns documented in published research (Kent 2021 eBay netsuke study; Oryx EU code-word study): the item is described as a legal material (most often bone, sometimes "old material" or an ambiguous word), the price is at ivory level (8–20× the median price of comparable bone items in our real data — compute that median first from Step A), and one photo is a close-up of a base or cut surface.
- Write them at the pattern level in ordinary seller language. Do not build a glossary of trafficking euphemisms; you only need enough realistic variety for 15–20 listings.
- Photos: use Met images labeled `elephant_ivory` (copy them into `data/images/` under the new listing id). Use a museum close-up image as the "base" photo where possible.
- Each entry sets `is_reconstructed: true` and `reconstruction_source` to a citation string, e.g. `"Pattern from Kent 2021 (Tropical Conservation Science): ivory netsuke described as bone"`.
- Include variety: 10 netsuke, 4 figurines, 3 jewelry; 2 entries written in Vietnamese (`language: "vi"`; write in English then translate with any translator) to exercise the translation specialist; 3 entries deliberately **ambiguous** (ivory-level price but photos show nothing clear) so the system can produce WATCHLIST/CONTESTED.

**Step C — networks (`data/seed/networks.yaml`).**
- **N1 linked network:** 3 new sellers (S9xxx ids are fine, still pseudonymous names). Spread 6 reconstructed listings across them. Two of the listings (different sellers) reuse the **same photo file** (copy it, same pixels). All three sellers share at least two rare 5-word phrases in descriptions (write them yourself, ordinary wording, e.g. a shipping or "please message before buying" sentence).
- **N2 shop:** 1 seller with 6 reconstructed "bone" netsuke at ivory-level prices and 2 ordinary real-looking items.
- **N3 honest dealer:** the real eBay seller chosen in Task 2 with genuine bone/tagua at normal prices. No reconstructed listings.
- **Relist:** pick one N1 listing as the demo "removed" listing. Create a hidden copy (`status: "hidden"`, `relist_of: <original id>`) under a 4th new seller with the same main photo and the description lightly reworded (same rare phrases kept).

**Step D — labels (`data/labels.csv`):** columns `listing_id,truth,should_flag,notes`. Reconstructed (non-ambiguous) → `ivory,true`. Ambiguous reconstructed → `ivory,true,"ambiguous by design"`. Real items: `tagua`, `legal_resin` (resin/faux/ivory_color), `legal_bone` (bone), `other_legal` (wood/unknown) — all `should_flag=false`. Spot-check 30 real items by eye; if an item is clearly mislabeled by the parser, fix the label (not the listing).

**Step E — eval set (`data/eval_set.txt`):** one listing id per line: all non-ambiguous reconstructed + ambiguous ones + 40 negatives stratified (15 tagua, 15 bone, 10 resin/other) with random seed 7. This is what Person C's eval runs over.

**Step F — demo cases (`data/demo_cases.json`):** `{"d1_network": "<N1 listing id>", "d2_tagua": "<real tagua id>", "d3_removed": "<N1 listing with hidden relist>", "d4_ambiguous": "<ambiguous id>"}` — pick D2 as a tagua item whose price is normal and whose photos clearly look like tagua.

- [ ] Step 1: Write a test `tests/test_dataset_integrity.py` that loads the output files and asserts: every listing's `seller_id` exists; every `image_paths` file exists and is ≤ 300 KB; ids unique; every listing in `labels.csv`; exactly one hidden listing with `relist_of` set; `eval_set.txt` ids all exist; no seller name equals any raw eBay username (load mapping from `data/raw/seller_map.json` if present).
- [ ] Step 2: Run → FAIL (files missing).
- [ ] Step 3: Write `build_dataset.py` (idempotent: deletes and rebuilds `data/images/` and output files) and the two seed YAML files.
- [ ] Step 4: Run `uv run python scripts/build_dataset.py` then the integrity test → PASS.
- [ ] Step 5: Commit `data: dataset v1`. Post in team chat: counts per truth label and the demo case ids.

---

### Task 5: MarketplaceStore

**Files:** Create `backend/deadlang/marketplace/store.py` · Test `backend/tests/test_store.py`

**Produces:**
- `class ListingRemoved(Exception)` with attribute `listing_id: str`
- `class MarketplaceStore` with: `from_dir(data_dir: Path) -> MarketplaceStore`; `get_listing(id) -> Listing` (raises `ListingRemoved` if removed, `KeyError` if unknown or hidden); `get_listing_any_status(id) -> Listing`; `get_seller(id) -> Seller`; `active_listings() -> list[Listing]`; `seller_listings(seller_id, include_removed=True) -> list[Listing]`; `search(query, limit=50) -> list[Listing]` (all whitespace-separated words must appear in title+description, case-insensitive, active only); `remove_listing(id) -> str | None` (marks removed; if a hidden listing has `relist_of == id`, mark it active and return its id); `statuses() -> dict[str,str]`; `reset_demo_state(original: dict[str,str])`.

- [ ] Step 1: Failing tests with an in-memory store of 4 listings (one hidden relist of L1): get_listing on removed raises `ListingRemoved`; on hidden raises `KeyError`; `remove_listing("L1")` returns the relist id and that relist becomes visible in `active_listings()`; `seller_listings` includes removed when asked; `search("bone netsuke")` matches only listings containing both words; `reset_demo_state` restores.
- [ ] Step 2: Run → FAIL. Step 3: implement. Step 4: Run → PASS.
- [ ] Step 5: Commit `data: marketplace store`.

---

### Task 6: Marketplace MCP server and client

**Files:** Create `backend/deadlang/marketplace/server.py`, `backend/deadlang/marketplace/client.py` · Test `backend/tests/test_marketplace_client.py`

**Server:** FastMCP app named `deadlang-marketplace`, streamable HTTP on port 8100, path `/mcp`. Loads `MarketplaceStore.from_dir(DL_DATA_DIR)` once, remembers the original statuses. Tools (all return JSON strings of the models; errors as `{"error": "...", ...}`):
- `get_listing(listing_id)`, `get_listing_snapshot(listing_id)` (any status), `get_seller(seller_id)`, `get_seller_inventory(seller_id)`, `search_listings(query, limit=50)`, `list_active()`, `admin_remove_listing(listing_id)` → `{"removed": id, "relisted_as": id|null}`, `admin_reset_demo()`.
- Run with `uv run python -m deadlang.marketplace.server`.

**Client (`client.py`):** implements the `MarketplaceClient` protocol from file 01 §4.1 twice:
- `LocalMarketplaceClient(store)` — calls the store directly (used by tests and `MARKETPLACE_MODE=local`). Because the API process and the specialists' processes must see the same removed/relist state, **in local mode everything runs in one process**; in `mcp` mode every process talks to the one MCP server.
- `McpMarketplaceClient(url)` — uses the MCP Python SDK streamable-HTTP client; opens one session lazily and reuses it; converts `{"error":"listing_removed"}` into `ListingRemoved`.
- `get_marketplace_client()` reads `MARKETPLACE_MODE` and returns a process-wide singleton.
- `image_path(rel)` returns `Path(DL_DATA_DIR) / rel` (images are read from disk in both modes; the MCP server doesn't stream images).

- [ ] Step 1: Failing tests against `LocalMarketplaceClient` covering every method (reuse the Task 5 fixture), plus one test that starts the MCP server in a subprocess on a random port and calls `get_listing` and `admin_remove_listing` through `McpMarketplaceClient` (mark with `@pytest.mark.integration`).
- [ ] Step 2–4: implement, run `uv run pytest tests/test_marketplace_client.py -v` → PASS (integration test included).
- [ ] Step 5: Commit `data: marketplace mcp server + client`. Tell Person B and C it's ready.

---

### Task 7: Price Checker specialist (`price_check`)

**Files:** Create `backend/deadlang/specialists/price.py` · Test `backend/tests/test_price.py`

**Consumes:** `Specialist` protocol (file 01 §4.2), `MarketplaceClient`.
**Produces:** `class PriceChecker` with `name="deadlang-price-checker"`, `capability="price_check"`, `tier="preferred"`, `async run(call: SpecialistCall) -> SpecialistReply`.

**Algorithm:**
1. Load the target with `get_listing_snapshot` (price checks still work after removal).
2. Comparables = all active listings except the target, excluding any listing with `is_reconstructed=True` (so our planted cases don't inflate prices), with the same `item_type` AND same `stated_material`.
3. If fewer than 5 comparables, widen to same `stated_material` any item type; set `weak_comparison=True`. If still fewer than 5, return one draft saying there aren't enough comparables (`ratio=null`).
4. Compute `median`, `p25`, `p75` (nearest-rank), `n`, `ratio = price / median` rounded to 1 decimal.
5. `summary` template: `"Comparable {stated_material} {item_type} listings (n={n}) have a median price of ${median:.0f} (middle range ${p25:.0f}–${p75:.0f}); this listing is ${price:.0f}, {ratio}x the median."` Append `" Weak comparison: matched on material only."` when widened.
6. `data`: `{"listing_id", "price_usd", "stated_material", "item_type", "n", "median_usd", "p25_usd", "p75_usd", "ratio", "weak_comparison", "comparable_ids": first 10 ids}`. All numbers in the summary must be the same rounded values stored in data (store `median_usd` rounded to 0 decimals, `ratio` to 1).

- [ ] Step 1: Failing tests with a fixture of 8 bone netsuke at $40–$120 and a target bone netsuke at $1,000: ratio ≈ 12.x, n=8, summary contains the median and ratio and both values are in data; widen test with only 3 same-type comps; not-enough test.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Commit `data: price checker`.

---

### Task 8: Seller Inventory specialist (`seller_inventory`)

**Files:** Create in `backend/deadlang/specialists/network.py` · Test `backend/tests/test_network.py`

**Produces:** `class SellerInventory` (`name="deadlang-seller-inventory"`, `capability="seller_inventory"`). `params.seller_id` optional (defaults to the listing's seller).

**Output:** one draft. `data`: `{"seller_id", "seller_name", "listing_count", "removed_count", "same_material_count", "same_type_count", "total_value_usd" (rounded 0), "items": [{"id","title","price_usd","stated_material","item_type","status"} up to 12]}`. Price ratios per item are not computed here (that's price_check's job). Summary template: `"Seller {seller_name} has {listing_count} listings ({removed_count} removed); {same_material_count} are described as {stated_material} and {same_type_count} are {item_type} items, worth ${total_value_usd:,} in total."` — make sure the formatted number (with comma) still matches: store `total_value_usd` as an int and let Person C's number check strip commas (it does).

- [ ] Steps 1–5: failing tests (seller with 3 active + 1 removed listings), implement, pass, commit `data: seller inventory`.

---

### Task 9: Linked Sellers specialist (`linked_sellers`)

**Files:** Add to `backend/deadlang/specialists/network.py` · Test `backend/tests/test_network.py`

**Produces:** `class LinkedSellers` (`name="deadlang-linked-sellers"`, `capability="linked_sellers"`).

**Algorithm (precompute once per process, cache on the instance; recompute when `all_active()` count changes, which handles the relist reveal):**
1. **Phrases:** normalize text (lowercase, strip punctuation, collapse spaces) of title + description; build word 5-grams. Drop any 5-gram whose words are all in a small stopword list. A 5-gram is **rare** if it appears in listings of ≤ 3 distinct sellers across the whole dataset.
2. **Photos:** compute `imagehash.phash` for every image (cache to `data/phash_cache.json` keyed by image path). Two images match when Hamming distance ≤ 6.
3. For the target listing: collect rare 5-grams; find other sellers' listings sharing ≥ 2 rare 5-grams, or sharing a matching photo. Include removed listings of the target's own seller for the "relist" case (the relist is by a different seller, so it shows up naturally once revealed).
4. Output one draft. `data`: `{"listing_id", "linked": [{"seller_id","seller_name","listing_ids":[...],"shared_phrases":[up to 3 strings],"shared_photo_pairs":[["images/..","images/.."]]}], "linked_seller_count"}`. Summary: zero → `"No other sellers share rare phrasing or photos with this listing."`; else `"{linked_seller_count} other sellers share rare phrasing or reused photos with this listing: {name1} ({k1} shared phrases, {p1} shared photos), …"`. Shared phrases go in `data` verbatim so quoted text in agent claims can be verified.

- [ ] Step 1: Failing tests: three-seller fixture where S1/S2 share two rare phrases and S1/S3 share an identical image file → both linked; a common phrase used by 5 sellers is not rare; relist case: after `remove_listing`, the revealed relist's seller appears as linked to the original.
- [ ] Steps 2–4: implement → PASS (tests create tiny real JPEGs with Pillow so phash works).
- [ ] Step 5: Commit `data: linked sellers`.

---

### Task 10: Legal Table specialist (`legal_lookup`)

**Files:** Create `data/reference/legal.json`, `backend/deadlang/specialists/legal.py` · Test `backend/tests/test_legal.py`

**`legal.json` content.** The US-federal and US-CA rows were checked against the cited sources on 2026-10-09. The CITES row is from general knowledge: open the CITES appendices page and confirm the wording before the demo. Keep the `source` field on every row.

```json
{
  "species": {
    "elephant_ivory": {
      "common_name": "African or Asian elephant ivory",
      "cites": "Asian elephant: Appendix I. African elephant: Appendix I, except the populations of Botswana, Namibia, South Africa and Zimbabwe, which are in Appendix II with an annotation that restricts trade in their ivory.",
      "source": "https://cites.org/eng/app/appendices.php"
    }
  },
  "jurisdictions": {
    "US-federal": {
      "rule": "Interstate sale of African elephant ivory is prohibited except ESA antiques (at least 100 years old, not repaired with ivory since Dec 27, 1973, imported through an antique port where applicable) and de minimis items (ivory under 200 grams, not more than 50% of the item by volume or value, made before July 6, 2016, with import-date conditions). Intrastate sale is allowed federally only with proof of lawful import before Jan 18, 1990; states may be stricter.",
      "source": "https://www.fws.gov/frequently-asked-questions-about-elephant-ivory"
    },
    "US-CA": {
      "rule": "California Fish and Game Code section 2022 makes it unlawful to purchase, sell, offer for sale, or possess with intent to sell ivory. Narrow exceptions: antiques at least 100 years old with ivory under 5% by volume and documented provenance; musical instruments made no later than 1975 with ivory under 20% by volume and documentation; certain educational or scientific institutions; federal permits and law enforcement. First offense is a misdemeanor with fines of $1,000 to $40,000 depending on value.",
      "source": "https://codes.findlaw.com/ca/fish-and-game-code/fgc-sect-2022/"
    },
    "default": {
      "rule": "No state-specific rule in our table; federal rules apply for US sellers. For non-US sellers, CITES Appendix I bars commercial international trade.",
      "source": "https://cites.org/eng/app/appendices.php"
    }
  }
}
```

**Produces:** `class LegalTable` (`name="deadlang-legal-table"`, `capability="legal_lookup"`). `params.material_hypothesis` defaults to `"elephant_ivory"`; jurisdiction = listing `ship_from` if it's a key in `jurisdictions`, else `US-federal` for any `US-*`, else `default`. Returns **two** drafts: one species draft (summary = first sentence of `cites`) and one jurisdiction draft (summary = first sentence of the rule + `" (applies because the item ships from {ship_from})."`). `data` carries the full text, `source`, `jurisdiction`, `ship_from`, and for CA the numbers `100`, `5`, `20`, `1975` as fields so agents can cite them.

- [ ] Steps 1–5: failing tests (US-CA listing → CA rule; US-NY → federal; HK → default), implement, pass, commit `data: legal table`.

---

### Task 11: Demo data tuning (with Persons C and D, after the first live runs)

- [ ] Run D1–D4 through the live system with Person C. For each, check: does the intake board contain the facts the story needs (price ratio on D1 ≥ 8x, linked sellers found for D1 after request, tagua look in D2's photos, relist revealed in D3)?
- [ ] Adjust **data only** (prices, which photo is the close-up, phrasing overlap) — never prompts or code — until each case tells its story in at least 2 out of 3 runs. Record changes in `data/CHANGELOG.md`.
- [ ] Re-run `test_dataset_integrity.py` after every change.
- [ ] Commit `data: demo tuning`.

## Self-check before you call it done

- Every specialist test passes; `uv run pytest -m "not integration"` is green and the integration test passes with the MCP server.
- `data/listings.jsonl` loads; counts posted in chat; demo case ids in `data/demo_cases.json`.
- No real eBay usernames anywhere outside `data/raw/`.
