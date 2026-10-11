# Person D (v2): Queue View, Metrics Page, Strike UI, Pitch

> Read `00-overview-and-contracts.md` first. Old plan: `../05-person-D-product-ui-pitch.md`.

## Goal
Make the pipeline visible and convincing to a judge in under a minute: a queue that fills with marks asynchronously, a metrics page with real numbers, an honest strike flow, and a clear Demo/Live distinction. Minimal text. Visuals carry the story.

## You own
`frontend/**`, `docs/pitch/**`, the demo script, `frontend/public/replays`. The pitch slides and Devpost draft are yours with input from everyone.

## Not yours
Backend. If you need a field that is not in the contracts, ask the owner (C for API, A for data, B for eval).

## Existing UI you build on
Pages: `/` listings, `/listing/[id]`, `/replays`, `/replay/[name]`, `/results`, `/case/[caseId]`. Case view has an Examine stage and an Agents stage. Keep the existing design language and the readable-first rules from earlier UI passes: no tiny text, no jargon, no slideshow look, no pill clutter, plain wording.

## Tasks

### D1. Build against the real batch API (P0)
C's batch API is live (`POST /api/batches` and its SSE stream) and runs real cases, so there is no fake mode. For anything C hasn't shipped yet (metrics, strike, refresh), add a local fake in `frontend/src/lib/stubs.ts` that mimics the shapes in file 00 §4.2 and §4.6 so you are never blocked. The existing `withFallback` pattern in `lib/stubs.ts` is the model.

### D2. Queue view (P0/P1)
New page `frontend/src/app/queue/page.tsx` (primary nav item "Queue"; the listings page can link to it).
- Two start actions at the top: **Run demo set** (12 curated) and **Fetch live** (query box and an item cap; cap defaults to 25 and has a visible maximum). Both call `POST /api/batches` and subscribe to `/api/batches/{id}/events`.
- A row per listing: thumbnail, title, price, a **Demo** or **Live** badge (from `Listing.origin`), and a status mark that updates asynchronously:
  - queued: quiet dot. triaging and deliberating: animated progress.
  - done marks: **flag** = FILE, **check** = DISMISS or screened out by triage, **split mark** = CONTESTED, **clock** = WATCHLIST, **warning** = error.
  - Never use an X for dismiss. It reads as failure.
- Rows with agents running show who is currently speaking (reuse the seat colors), but keep it compact.
- Clicking a done row opens the existing case view (live case or its replay).
- A thin summary strip above the list: counts by mark and elapsed time, updating live.
- Honesty: live-lane rows say "flagged for human review", never "illegal". If the connector returned recorded data, show a small "recorded" label (A's response metadata).

### D3. Metrics page (P1)
New page `frontend/src/app/metrics/page.tsx` reading `GET /api/metrics` (shape in file 00 §4.6). Not the same as `/results` (evaluations).
- Top row: the funnel as a horizontal bar (ingested -> screened out -> deliberated -> FILE/CONTESTED/WATCHLIST/DISMISS). This is the hero.
- Speed: listings per minute and p50/p95 time per stage, plain numbers with units.
- Cost: dollars per case and total, with a Haiku vs Sonnet split.
- Refresh: last run, checked, changed, removed.
- Strikes: pending, approved, submitted (simulated), observed removed.
- Market view: simple charts from `GET /api/market` (median price by material and country, listing counts). Use Recharts (already in the stack).
- Zero state: if no runs yet, show zeros. Never show sample numbers.
- Make a clear "Refresh now" button that calls `POST /api/refresh` and shows the returned changes. This is the live "ping" moment in the demo.

### D4. Strike flow (P1)
In the case view and the case-file drawer (`CaseFileDrawer.tsx`), add a review block for FILE and CONTESTED cases, from `GET/POST /api/cases/{id}/strike`:
- A name field (who is approving), an **Approve** button, then a **Submit report** button that only enables after approval.
- Show the notice draft in the existing monospace block.
- Status line in plain words: "Waiting for review", "Approved by <name>", "Submitted (simulated)", "Listing removed".
- Always show "Simulated: nothing is sent to any marketplace" when the status is `submitted_simulated`. This label must not be removable by a prop.

### D5. Rename and branding (P0 after C's commit)
After C's rename lands, verify there is no leftover "Buyer", "Defender", "Caseload" in visible text, alt text, titles or replay text. App name comes from `APP_NAME`. Update the favicon text and page titles. Spot check the replays.

### D6. Evaluations page (P1)
The existing `/results` page shows evaluations. B will add keys to `results/eval.json`: config comparison (Haiku/Sonnet/tiered), triage recall sweep, examiner accuracy, stability, injection results, subgroup table. Ask B for the final shape and render it with the same plain style. Keep the existing "not measured yet" empty state. Keep claims honest: show n next to every percentage and the reconstructed-positives caveat.

### D7. Pitch (P1/P2)
- **Plugin vs website slide.** One visual: a plugin sees one page; the platform sees the whole network (same photo under a new account, shared wording, price against the market, removal over time). Say: "the plugin is a sensor, the platform is the brain." Optional stretch: a tiny extension that POSTs the current URL to `/api/batches`.
- **Scale slide.** The funnel with measured numbers from C's `/api/metrics`. Only use numbers we measured. Say what is measured on what hardware.
- **Safety slide.** Human approval, simulated strike, injection test result, subgroup error table, no live "illegal" claims.
- **Models slide.** Haiku for triage, Sonnet for anything that can accuse, and B's evidence for the choice.
- Demo run order is in file 00 §10. Record a backup video of the whole flow and a replay of one live run (A saves it).

### D8. Mobile and states (P2)
Queue and metrics pages must work at 390px: no horizontal scroll, tap targets 44px, no text under 14px. Empty, loading, error and offline states for every new page. Respect reduced motion.

## Dependencies
- C: batch API, metrics, strike, market endpoint, rename.
- A: `Listing.origin`, `recorded` metadata, `GET /api/market` payload.
- B: `results/eval.json` keys.

## Done means
- Queue fills asynchronously with correct marks and Demo/Live badges, both lanes.
- Metrics page shows real measured numbers and a working "Refresh now".
- A FILE case goes through approve then submit (simulated) in the UI with the visible simulated label.
- No old agent names visible anywhere, app name from one constant.
- `npx tsc --noEmit` and `npm run build` pass. Mobile checked once.
