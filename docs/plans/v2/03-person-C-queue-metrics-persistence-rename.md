# Person C (v2): Queue API, Metrics, Persistence, Strike, Rename

> Read `00-overview-and-contracts.md` first. Old plan: `../04-person-C-deliberation-api-eval.md`. In v2 the **evaluation runner moves to Person B**; you add the queue and metrics.

## Goal
Turn single-case runs into a batch pipeline you can measure: submit many listings, watch them move through triage and deliberation asynchronously, record every number honestly, and keep an audit trail. Human approval gates every strike.

## Metrics vs evaluations (important)
You own **metrics**: how the system *performs* (throughput, latency, cost, funnel counts, removals detected, strikes by status). Person B owns **evaluations** (are the model outputs good). Do not build eval tables.

## You own
`backend/deadlang/deliberation/*`, `backend/deadlang/api/*`, `backend/deadlang/costs.py`, `backend/deadlang/schemas.py` (shared contract, edit only per file 00), new `queue.py`, `metrics.py`, `store.py` (persistence), plus the rename commit.

## Not yours
Triage and eval code (B), data and refresh detection (A), UI (D).

## Tasks

### C1. Rename and `origin` field (P0, do first, one commit)
1. Post in team chat that you are about to rename. Then in one commit:
   - `AgentName` -> `Literal["undercover", "counsel", "case_officer"]`; update `Requester`.
   - Prompt files in `deliberation/prompts/`, `AGENT_ORDER`/`AGENTS` in `frontend/src/lib/agents.ts` (labels: Undercover, Counsel, Case Officer; keep goals as short phrases of the question each owns: see file 00 §3), replay fixtures in `fixtures/replays/` and `frontend/public/replays/`, `scripts/record_scripted_demo.py`, `tests/`.
   - Add `origin: Literal["demo", "live"] = "demo"` to `Listing`.
   - Add `APP_NAME` constant in `frontend/src/lib/agents.ts` once the team picks the app name (undecided; do not hard-code it elsewhere).
2. Replay fixtures contain hand-written `take` text that names roles. Update wording where an old name appears in prose.
3. Run backend tests and `npx tsc --noEmit && npm run build`. Push, announce, everyone pulls.

### C2. Queue and batch API (P0 with a fake worker, P1 real)
Contract in file 00 §4.2. Implementation, keeping it boring:
- A `JobQueue` protocol (`submit`, `status`) with an in-process asyncio implementation now: a bounded `asyncio.Semaphore` concurrency limit (`DL_MAX_CONCURRENT_CASES`) and an `asyncio.Queue`. # ponytail: single-process queue, swap the implementation for Redis/SQS behind the same protocol when scaling past one API process.
- Worker per item: `queued -> triaging` (call B's `screen()`; use `FakeTriage` until it lands) -> `screened_out` (no agents) **or** `deliberating` (run the existing `Facilitator.run_case`) -> `done` with outcome, or `error` with message. One bad item never fails the batch.
- Emit `batch.item` SSE events on every status change; keep an in-memory history per batch for late subscribers.
- `source: "demo"` uses `load_demo_set()` (A). `source: "live"` calls `fetch_live(query, cap)` (A), then enqueues the results.
- Spend and rate guard: per API key request limit and a global `DL_MAX_SPEND_USD` per day, enforced before each Sonnet case. When hit, items go `error` with a clear reason.
- Fake worker first (random delays and outcomes from the demo set's designed outcomes) so D can build the queue UI on day one. Make the switch `DL_WORKER=fake|real`. The fake must be obviously labeled in the response (`"mode": "fake"`) so it is never mistaken for real results.

### C3. Persistence and audit log (P1)
SQLite via stdlib `sqlite3` (single file `data/runs.db`). # ponytail: SQLite, move to Postgres when more than one writer process is needed.
Tables: `cases` (case_id, listing_id, origin, outcome, started_at, ended_at, model_versions, prompt_hash, rules_version, snapshot_sha256), `events` (the existing event log, append-only), `strikes` (history), `changes` (A's `ListingChange`), `usage` (per call: model, tokens, usd, stage, duration_ms).
Rules: append-only for `events` and `strikes`. A finished case is immutable and replayable from its events. Store the prompt files' hash and the rules version with each case so any outcome can be reproduced.

### C4. Metrics backend (P1)
`GET /api/metrics` with the exact shape in file 00 §4.6. Compute from the `usage`, `cases`, `changes` and `strikes` tables and live counters. Rules:
- Latency percentiles per stage from `usage.duration_ms`.
- `throughput_per_min` from completed items over a trailing window.
- `usd` from `costs.py` using the real token counts the SDK returns. Include cache-read savings when reported.
- Nothing synthetic. No runs yet means zeros.
- `by_model` makes the Haiku/Sonnet split visible for the funnel story.
Also expose `market_stats()` from A through `GET /api/market` so D can draw the market view (use the same response, do not re-compute).

### C5. Strike API and refresh scheduling (P1/P2)
Contract in file 00 §4.3-4.4.
- Strike: statuses `none -> pending_review` (set automatically when a case ends FILE or CONTESTED; a human decides) `-> approved` (POST, requires `by`) `-> submitted_simulated` (POST submit; generates `notice_draft` from the existing code-template case file, no model) `-> observed_removed` (set by the refresh job).
- Reject `submit` unless status is `approved`. Reject any attempt without a `by` value. This is the human gate: add a test that proves a FILE case cannot reach `submitted_simulated` without an approval.
- Refresh: `POST /api/refresh` calls A's `refresh_listings` on active listings, stores changes, advances strike statuses, and returns the changes. Optional interval via `DL_REFRESH_SECS` (default 0 = manual).

### C6. Auth and abuse limits (P1, safety)
Static API keys from env (`DL_API_KEYS`), checked by a FastAPI dependency on every `/api/*` route except `/api/images` and read-only replays. Per-key rate limit and spend cap. # ponytail: static keys and in-memory counters, replace with real identity and shared limits for multi-instance deployments. The frontend uses a demo key from `NEXT_PUBLIC_*` env.

### C7. Concurrency load test (P2)
A script `scripts/load_test.py`: submits N demo-lane items with the fake worker and then a small real batch, records time to completion and the metrics output. This is where the "speed" number for the pitch comes from, and it must be measured, not estimated.

## Dependencies and fakes
- B's `screen()`: use `FakeTriage` until it lands.
- A's `load_demo_set()`, `fetch_live`, `refresh_listings`: stub them with canned returns until A pushes.
- D builds against your fake worker. Keep the batch JSON shape frozen.

## Done means
- Rename landed with tests and fixtures consistent, tsc and build green.
- A batch of 12 demo items completes asynchronously with the real worker, statuses stream over SSE, and `GET /api/metrics` returns measured numbers.
- A FILE case cannot be struck without a named approver (test).
- Every case has an audit record with model, prompt hash, rules version and snapshot hash.
- Auth and spend cap work (a test that the cap stops a case).
