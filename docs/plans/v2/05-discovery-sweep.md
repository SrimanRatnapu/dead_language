# v2 Add-on: Discovery Sweep (finding listings that avoid the keywords)

> Proposal by Person A. Read `00-overview-and-contracts.md` first. This changes one shared contract (§4.2, the
> live batch body), so it needs a yes from C and D before anyone builds step 2 onward.
> Status: **step 3 (follow-up fetch) is built and tested; steps 1 and 2 are proposals.** The API checks in "What we measured" were run on 2026-10-10.

## The gap

The live lane asks eBay one keyword question (`fetch_live(query, cap)`, default "bone netsuke") and takes the
first 25-50 results in eBay's relevance order. Two things go wrong:

1. **Someone has to guess the words.** A listing titled "old carved toggle, estate piece" never matches
   "bone netsuke", so it is never fetched and no agent ever sees it. This is the keyword search our pitch says fails.
2. **The cap is spent on whatever eBay ranks first**, which has nothing to do with suspicion. Most of it is $20 resin.

Our own insight already says what to do: a seller can change the words, but the buyer must still be able to
**find** the item and **see the price**. So search by where the item has to be listed and what it costs, not by words.

## What we measured (eBay Browse API, production keys)

| Search | Results |
|---|---|
| Category "Netsuke" (id 37938), no keyword at all | 11,221 |
| Same category, price at least $400 | 857 |
| Same category, price at least $400, keyword "bone" | 0 |
| Category "Statues" under Japanese antiques (id 162973), price at least $500 | 1,273 |
| Vintage bracelets (id 262003), keyword "bone", price at least $120 | 106 |

What this tells us:
- A category sweep needs no keyword, and a price floor cuts it by more than 90% on the server, before we download anything.
- Nobody on eBay is currently selling a netsuke that says "bone" for $400 or more. Our planted cases sit at
  $985-$1,865. So "expensive and described as bone" is rare enough to be worth a human's attention on its own.
- A price floor alone is not enough: the 857 expensive netsuke are mostly genuine antique wood, lacquer and stag
  horn. The floor decides what we **fetch**; price relative to the **stated material** still decides what is suspicious.

Category ids found with eBay's category-suggestion API: 37938 and 29453 (Netsuke), 162973 (Statues, Japanese
antiques), 73466 (Other Japanese antiques), 29445 (Figures & statues, Chinese), 262003 (Vintage bracelets).
Confirm each id before hard-coding it.

## The change, in three steps

### Step 1. Sweeps in `fetch_live` (Person A, about 1.5 hours, no contract change)

Add named sweeps beside the existing keyword query. A sweep is a small fixed list of (category id, price floor):

```python
# deadlang/marketplace/live.py
SWEEPS = {
    "netsuke":   [("37938", 300), ("29453", 300)],
    "figures":   [("162973", 400), ("29445", 400), ("73466", 400)],
    "bracelets": [("262003", 100)],
}
async def fetch_live(query: str | None = None, cap: int = 25, sweep: str | None = None) -> tuple[list[...], str]
```

- `sweep` given: for each (category, floor) call `item_summary/search` with `category_ids`, `filter=price:[floor..],priceCurrency:USD`
  and `sort=newlyListed`, no keyword. Split the cap evenly across the entries.
- `query` given: behaves exactly as today. Neither given: use the `netsuke` sweep.
- Everything after the search is unchanged: dedupe against the dataset and earlier fetches, pseudonymize, store
  photos and the snapshot hash, `origin="live"`, recorded fallback when the API is unavailable.
- Price floors start from our stored medians (bone netsuke $104, bone figurine $132, bone jewelry about $28), at
  roughly 3x. They are constants in one place and get tuned after the first real sweep.

Acceptance:
- A faked-eBay test shows a sweep sends `category_ids` and a price filter and no `q`.
- A real `netsuke` sweep with cap 25 returns 25 listings, all at or above the floor, in under 60 seconds.
- Existing live tests still pass; `fetch_live("bone netsuke", 25)` returns what it returns today.

### Step 2. Rank by price ratio before spending the cap on agents (Person A + Person B, about 1 hour)

A sweep returns expensive items of every material. Before any model runs, order them with facts we already compute for free:

- `PriceChecker` ratio against the stated material (code, no model).
- Stated material is one of `bone`, `unknown`, `ivory_color`, `ivory_mentioned` (the materials a disguised item would claim).

Expose `rank_for_review(listing_ids) -> list[{listing_id, ratio, stated_material, reason}]` in
`deadlang/marketplace/live.py`. B's Haiku `screen()` then runs in that order, so the suspicious tail is triaged first
if the batch is cut short by the spend cap. This does **not** screen anything out by itself: dropping listings is
triage's job, and its threshold favours recall.

Acceptance: on the recorded fixture, the order is deterministic, and a planted listing added to a fake sweep ranks first.

### Step 3. Follow-up fetch from a flagged listing — **BUILT** (2026-10-11)

When the agents flag a live listing, the system pulls what is around it and adds it to the same batch, with no
one typing a search:

**A. The seller's other listings.** Up to 10, through the Browse API `sellers:{username}` filter, starting in the
flagged listing's own category and walking up to two parent categories (nearest first).
**B. Listings that share its distinctive title words.** The flagged title's rarest words, two at a time
("dakota nantucket"), searched inside the same eBay category. Up to 3 pairs are tried, at most 2 bring listings
in, up to 10 each.

Code: `fetch_related()` and `distinctive_terms()` in `deadlang/marketplace/live.py`; queue support in
`deadlang/api/batches.py` (`should_follow`, `follow_up`); wiring in `deadlang/api/server.py`; rows and notes on
the Review desk (`frontend/src/app/desk/page.tsx`). Tests: `backend/tests/test_follow_up.py`.

**Trigger.** A batch with `source: "live"` and `source_mode: "live"`, an item whose case ends FILE or CONTESTED.
Never for a demo batch (nothing is fetched into the demo lane) and never for a recorded batch (there is no live
API behind it). When B's triage lands, its `suspicious` flag can trigger it earlier; today the outcome does.
`DL_FOLLOW_UP=0` switches it off. It is **on by default**.

**Who picks the words: code, not a model.** `distinctive_terms` takes words from the flagged listing's own
**title**, drops filler words, numbers, words under 3 letters, the material and item-type words the parser already
reads, and any word used by more than 5% of the listings we hold; it then pairs the rarest that remain. Same
listing, same answer. Nothing in a description can add a search word, so a description that says "search for X"
does nothing. Words in a title are searchable by design; the bound there is the search budget and the category.

**What changed from the first draft of this step, and why (measured against the live API on 2026-10-10/11):**
- *Titles, not descriptions.* eBay's `searchInDescription` filter did not return the very listing a description
  phrase was copied from (0 of 5 tries), so description wording cannot be searched reliably.
- *Same category.* Without it, "husky dog" for a netsuke returned plush toys. Inside the category, the pair
  "dakota nantucket" returned the same title listed by two other sellers.
- *Word pairs, with our own check.* eBay also matches word variants, so a hit is kept only if its title really
  contains both words. A pair that matches more than 25 titles in the category is ordinary wording and is skipped.
- *No stored username.* The seller filter needs the real username. It is read from eBay at that moment (one
  item request), used for the search, and dropped: not stored, not logged (the request log line is redacted), not
  returned. If the flagged listing is gone from eBay, the seller half is skipped and the title-word half still runs.
- *No new agent capability.* The fetched listings are reviewed on their own; `found_via` is shown in the queue
  only and is not put in any prompt, so a listing is not judged by the company it keeps.

**What happens to the fetched listings.** Stored as live listings (`origin="live"`, ids `LV…`), deduped (already
in the dataset: skipped; fetched before: reused; a seller's own duplicate photo: dropped; another seller reusing
the photo: kept, that is the interesting case), then appended to the batch as `queued` with `found_via`, `term`
and `parent`. The batch and its event stream stay open until they finish.

**Hard limits:** one hop (a follow-up listing never triggers another); 10 seller listings and 2 word pairs x 10
per flagged listing; **20 added listings per batch**; 50 listings per batch in all; one fetch at a time.

**We do not build a word list.** Terms are computed per listing and shown in the queue. Nothing reuses them later.

**Measured on real listings:** for the listing "SCRIMSHAW REPRODUCTION TOOTH 'DAKOTA' OUT OF NANTUCKET" it added
10 of the seller's other listings and 2 title matches for "dakota nantucket": the identical title under a second
seller account at three times the price, and a near-identical one under a third. About 15 seconds from cold.
For one-off sellers with unusual titles it often adds nothing, which is correct.

**Not verified:** a full run with the real agents (no model key on the build machine). The queue flow was watched
in the UI with the three agents scripted; everything else in that run was real (marketplace, eBay, API, UI).

## Contract change (needs C and D)

`00-overview-and-contracts.md` §4.2, live body. Today: `{"source":"live","query":"...","cap":N}`. Proposed:

```
{"source": "live", "sweep": "netsuke" | "figures" | "bracelets", "cap": N}     # new, preferred
{"source": "live", "query": "...", "cap": N}                                    # unchanged, still accepted
```

- **C:** pass `sweep` through to `fetch_live`; 422 on an unknown sweep name. (Step 3 is built: `BatchItem` gained
  `found_via`, `term`, `parent`, `follow_up`; see file 00 section 4.2.)
- **D:** on the queue page, replace the free-text box with three sweep buttons and keep the text box behind "Custom search".
  Show the sweep's rule in plain words next to the batch: "Netsuke category, $300 and up, newest first".
- **B:** no change for step 1. For step 2, call `screen()` in ranked order.

Old clients keep working, so C and D can adopt it independently of step 1 landing.

## What this does not fix

- A listing that is in the **wrong category and cheaply priced** stays invisible. Nothing based on public signals finds it.
- The floors come from 479 listings collected in one day. They will be wrong for some categories until tuned.
- The title-word follow-up only finds listings whose **titles** share rare words, in the **same category**. A
  code phrase made of ordinary words ("old material"), wording that only appears in descriptions, and a relist
  moved to another category are all missed. The seller half still works for those.
- A sweep returns more genuinely expensive antiques than a keyword search does, so the dismiss and watchlist share
  of a live batch goes up. That is the honest cost of looking where the words do not point.
- We still only cover eBay, in English-language categories.

## What we may say in the pitch

"We do not search for the word. We sweep the category the object has to be listed in, above the price that
material normally sells for, and let the agents explain the rest." Do not say the sweep *finds illegal listings*:
it chooses what gets reviewed.

## Order and time

| Step | Owner | Needs | Time | Priority |
|---|---|---|---|---|
| 1. Sweeps in `fetch_live` | A | nothing | 1.5 h | P1 |
| Contract yes + pass-through | C | step 1 | 20 min | P1 |
| Sweep buttons on the queue page | D | C's pass-through | 45 min | P1 |
| 2. Rank before triage | A, B | step 1, B's `screen()` | 1 h | P1 |
| 3. Follow-up fetch (seller + title words) | A | nothing | done | built |

Feature freeze is 10:30 AM Sunday. Step 1 alone is demoable through the existing API by passing a sweep from a
test call; step 2 should not start after 8:00 AM. Steps 1 and 2 are still proposals.
