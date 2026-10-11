# Data handling

Short and true. If the code changes, change this file in the same commit.

## Two lanes

| | Demo lane | Live lane |
|---|---|---|
| What | The stored dataset in `data/` | A capped fetch from the eBay Browse API, made when someone runs a live batch |
| `origin` | `demo` | `live` (ids `LV0001…`; the recorded fallback uses `LV9001…`) |
| Ground truth | Yes, in `data/labels.csv` (evaluation code only) | None. We never claim a live listing is illegal |
| Where it lives | `data/listings.jsonl`, `data/sellers.jsonl`, `data/images/` | `data/live/listings.jsonl`, `data/images/live/` (both gitignored) |

Live data is never written into the stored dataset. A demo-lane case is only ever compared with stored listings
(price comparables, linked sellers), so a live fetch cannot change a demo case or an evaluation number. Price
comparables for a live listing are also the stored listings; linked-seller checks for a live listing look at both.

## Sources

- **eBay Browse API** (official, application token). Used once to build the stored dataset (`scripts/pull_ebay.py`)
  and at run time for the live lane (`deadlang/marketplace/live.py`). No page scraping.
- **The Met Open Access** (CC0) photos: the labeled museum set and the photos of reconstructed listings.
- **Written by the team:** 29 reconstructed listings, the hidden relist, and one injection-attempt listing
  (`data/extra/`, demo only, not in the labeled set). All carry `is_reconstructed: true`.

## What is stored

- **Stored dataset:** listing text, price, category, ship-from, up to 3 photos, the public listing URL.
- **Live fetch, per listing:** the same fields, the eBay item id, the fetch time, and a SHA-256 of the raw API
  response (`snapshot_hash(listing_id)`), for chain of custody. The raw response itself is not kept.
- **Not stored in anything committed or in the live lane:** seller usernames, emails, addresses, buyer data.
  `data/raw/` (gitignored, on the machine that built the dataset) still holds the original API records including
  usernames; it is needed only to rebuild the dataset.

## Seller pseudonyms

A seller appears everywhere (files, API responses, UI, prompts, logs) as `seller_` + the first 6 hex characters of
`sha1(username + "deadlang")`. The same seller always gets the same pseudonym. Live-lane seller ids are
`S-live-` + the first 4 characters. This is pseudonymous, not anonymous: someone who knows a username can
recompute its pseudonym. A seller's own shop name inside listing text is replaced with the pseudonym, in the stored
dataset and in live fetches. Photos can
contain watermarks; stored-dataset photos were checked by eye (not every photo of every listing), live photos are not.

## Follow-up fetch (live lane)

When the agents flag a live listing, we fetch that seller's other listings and listings in the same eBay category
whose titles share its rarest words, and queue them for the same review (`fetch_related`). The search words are
picked by code from the flagged listing's title; no model reads the listing to choose them. The seller search
needs the seller's real eBay username: it is read from eBay at that moment, used for that search, and dropped. It
is not written to any file, not returned, and the request line in the log has it blanked. Why a listing was
fetched ("same seller", "shares these title words") is shown to the reviewer and is not given to the agents.
Each live record now also keeps the listing's eBay category id (not personal data) so the same category can be
searched after the listing is gone.

## Limits on our own fetching

At most 50 listings per live fetch, at most 3 search pages, one request per 0.1 s, at most 3 photos per listing.
The refresh check makes one request per live listing. A follow-up fetch adds at most 10 seller listings and
2 x 10 title matches per flagged listing, at most 20 listings per batch, never follows a follow-up, and uses at
most 6 search requests, plus one item request for the flagged listing and one for each new listing it looks at.

## Retention and deletion

- Live records and their photos older than 30 days are deleted automatically the next time a live fetch runs.
  Nothing deletes them if no fetch runs, so by hand: delete `data/live/` and `data/images/live/`.
- An eBay marketplace-account-deletion notice (signed by eBay) removes that seller's records and photos from
  `data/raw/` and from the live lane, and adds their stored listings to `data/seed/exclude_real.csv`. They leave
  the stored dataset only when it is next rebuilt, which changes evaluation numbers: tell Persons B and C first.
- The stored dataset is kept for the hackathon and its evaluation. No end date has been set.

## Changes to stored data

The stored dataset must not be edited, reordered or re-numbered: evaluations run on all of it. Listing and seller
ids are pinned in `data/seed/id_map.json`. Every change so far is in `data/CHANGELOG.md`; the last one (ten more
reconstructed listings, 27 positives) was made before this rule was written.
