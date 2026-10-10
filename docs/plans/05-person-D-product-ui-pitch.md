# Person D — Product, UI & Pitch Build Plan

> Read `00-dead-language-design-spec.md` and `01-shared-contracts-and-kickoff.md` first. This plan assumes both.
> Steps use `- [ ]` checkboxes. UI commits are prefixed `ui:`, pitch commits `docs:`.

**Goal:** Own everything the judges see and hear: the web interface (browse listings, watch a case review live or from a replay, results), the story (use cases, value proposition), the deck, the demo script, the Devpost writeup, the architecture diagram, and the backup video.
**Architecture:** Next.js App Router frontend that only talks to the FastAPI backend (file 01 §4.6) and renders the event stream (file 01 §4.7). All UI state for a case is derived from the ordered list of `Event`s, so live mode and replay mode share one code path.
**Tech Stack:** Next.js (App Router) + TypeScript + Tailwind + Recharts. Slides in whatever tool you prefer (Google Slides, Keynote, or Claude's slide tool); export a PDF into `pitch/`.

## Global Constraints (in addition to file 01)

- **No courtroom framing anywhere** (UI copy, slides, script, Devpost). Banned words: court, courtroom, trial, verdict, jury, judge (as a role), prosecutor, defense lawyer, guilty. Use "case review", "outcome", "positions", "evidence".
- Agent display names and colors are fixed across UI, slides and diagram: **Buyer** (amber), **Defender** (teal), **Caseload** (violet). Specialists are neutral gray.
- Every claim shown in the UI shows its evidence chips; clicking a chip opens the raw evidence. Never show a claim without its chips.
- Reconstructed listings always show a small "Reconstructed from a documented case" badge. Real seller names are pseudonyms already; never add real usernames.
- Every number on a slide must come from `results/eval.json`, `results/examiner_eval.json`, or a cited source in spec §14. No made-up numbers, not even placeholders on the final deck.
- The UI must run against `fixtures/sample_case_events.jsonl` and the recorded replays with the backend **off**.

## Files you own

`frontend/**`, `pitch/deck.pdf` (+ source), `pitch/demo_script.md`, `pitch/devpost.md`, `pitch/use_cases.md`, `pitch/qa.md`, `pitch/architecture.png` (+ source), `pitch/backup_demo.mp4`.

---

### Task 1: Product framing doc (first hour, before UI polish)

**Files:** Create `pitch/use_cases.md`

Write one page (plain language) covering:
- **The problem** (from spec §1, with the cited numbers).
- **The insight** — "a coded listing has two readers" and "they can hide the word ivory, they can't hide the price".
- **Who uses it** (three users, one paragraph each, with what they get):
  1. *Trust & safety teams at marketplaces outside the Coalition* (examples: Craigslist, Mercari, Carousell, Shopee, Catawiki, LiveAuctioneers — none on the Coalition member list as of Sept 2026). They get a ranked queue and case files instead of keyword blocklists that sellers dodge.
  2. *Volunteer spotter programs (IFAW / WWF cyber spotters)*. Today volunteers flag one listing at a time by hand; they get pre-reviewed cases with evidence and a clear "why".
  3. *Wildlife enforcement units (US Fish & Wildlife Service Office of Law Enforcement, California Department of Fish and Wildlife)*. They get seller-level case files with the legal basis attached, and only cases worth their time.
- **Value proposition** in one sentence each: catches what keyword filters miss (reads like a buyer); protects honest sellers (an agent whose only job is to defend them, plus a human approves every filing); every claim is checkable (citations verified by code); spends investigator time on networks, not one-offs.
- **Why multiple agents** (Cisco wants this explained): one agent judging alone has no one to challenge it; three agents with competing goals surface the innocent explanation, the buyer's-eye reading, and the cost of investigating, and the disagreement itself is information (CONTESTED goes to a human).

- [ ] Step 1: Draft. Step 2: Share in chat for a 5-minute read by the team. Step 3: Commit `docs: use cases + value prop`.

---

### Task 2: UI foundation and types

**Files:** Create `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/app/layout.tsx`, `frontend/src/app/globals.css`

- **Visual direction:** a calm investigative workspace — dense but readable, like a good analytics tool. Neutral off-white background, near-black text, one accent per agent (amber / teal / violet), red reserved only for rejected claims, green only for "cleared". Use a monospace face for evidence IDs and numbers. Light and dark mode via CSS variables.
- **`types.ts`:** TypeScript mirrors of every model in file 01 §3 (`Listing`, `Seller`, `Evidence`, `StancePost`, `Claim`, `Rebuttal`, `SpecialistRequest`, `CaseFile`, `Event`, union `EventType`, `Outcome`, `Stance`, `AgentName`). Keep field names identical (snake_case).
- **`api.ts`:** `API_BASE = process.env.NEXT_PUBLIC_API_BASE`; functions `getListings()`, `getListing(id)`, `startCase(listingId)`, `getCaseFile(caseId)`, `removeListing(id)`, `killSpecialist(name)`, `resetDemo()`, `getReplays()`, `getReplay(name)`, `getEval()`, `imageUrl(relPath)`. Each throws on non-2xx.

- [ ] Step 1: Write files; `npm run build` passes. Step 2: Commit `ui: foundation + types`.

---

### Task 3: Case state from events (one code path for live and replay)

**Files:** Create `frontend/src/lib/caseState.ts`, `frontend/src/lib/useCaseEvents.ts`

- **`caseState.ts`:** a pure reducer `reduce(state: CaseState, e: Event): CaseState` with
  `CaseState = { listing, seller, evidence: Record<id, Evidence>, evidenceOrder: string[], rounds: { round: number, posts: Partial<Record<AgentName, StancePost>>, rejected: {agent, claim_text, reasons}[] }[], selections: {capability, specialist_name, why, requested_by, at}[], failures: [...], removed: {listing_id, relisted_as} | null, caseFile: CaseFile | null, budgetExceeded: string | null, lastSeq: number }`.
  Events with `seq <= lastSeq` are ignored (safe for reconnects).
- **`useCaseEvents(source)`** where `source = {kind: "live", caseId} | {kind: "replay", name, speed: 1|2|4} | {kind: "fixture"}`:
  - live: `new EventSource(`${API_BASE}/api/cases/${caseId}/events`)`, listen to every event type, feed the reducer, close on `case.ended`.
  - replay/fixture: load the event array, then release events on a timer that preserves the recorded gaps between `at` timestamps divided by `speed`, capped at 2.5 s per gap (so long model calls don't stall the demo). Expose `pause()`, `play()`, `skipToEnd()`.
- [ ] Step 1: A small unit test (Vitest or a plain node script) that reduces the fixture file and asserts: 2 rounds, 3 posts in round 2, outcome FILE, evidence count matches. Step 2: Commit `ui: case state reducer + event hook`.

---

### Task 4: Browse page (`/`)

**Files:** Create `frontend/src/app/page.tsx`, `frontend/src/components/ListingRow.tsx`

- Table of listings from `getListings()` sorted by triage score: thumbnail, title, price, stated material, seller name, triage score bar + one-line reason, "Reconstructed" badge where relevant, and a **Review** button (`startCase` then navigate to `/case/[caseId]`).
- Header strip with three buttons for the prepared demo cases (ids from `data/demo_cases.json` — ask Person A, hard-code them in `frontend/src/lib/demoCases.ts`) and a **Replays** menu (`getReplays()` → `/replay/[name]`).
- If the API is down, show a banner "Backend offline — replays only" and keep the Replays menu working from static copies placed in `frontend/public/replays/*.jsonl` (copy Person C's curated replays there before freeze).
- [ ] Step 1: Build against the live API once Person C's Task 8 is up; until then use a static JSON of 10 listings. Step 2: Commit `ui: browse page`.

---

### Task 5: Case page (`/case/[caseId]` and `/replay/[name]`) — the demo screen

**Files:** Create `frontend/src/app/case/[caseId]/page.tsx`, `frontend/src/app/replay/[name]/page.tsx`, components `ListingPanel.tsx`, `EvidenceBoard.tsx`, `EvidenceChip.tsx`, `EvidenceDrawer.tsx`, `RoundTimeline.tsx`, `PostCard.tsx`, `ConfidenceChart.tsx`, `SpecialistFeed.tsx`, `OutcomeBanner.tsx`, `CaseFileDrawer.tsx`, `DemoControls.tsx`

Layout at 1440×900 (the projector), three columns:
- **Left — ListingPanel:** photos (click to enlarge; when a material_exam evidence names a photo index, outline that photo and show the examiner's feature text under it), title, price, description, stated material, ships from, seller. A gray "Removed by seller" overlay appears on `listing.removed`, with "Snapshot kept as E0" and, if present, "Relisted as L0xxx".
- **Center — RoundTimeline:** one section per round. Within a round, **PostCards** side by side for the agents called that round (`round.started.active`; all three in round 1, only the triggered ones later; show a dimmed "Not called — nothing new for them" placeholder for the rest) (Buyer, Defender, Caseload) showing: stance pill (file / dismiss / need more), confidence, claims each followed by **EvidenceChips** (`E3`), rebuttal ("Answering Defender: …"), challenge ("Asks Caseload: …"), requests ("Asked for: material exam of photo 2 — because …"), a "Ready to close" tag when `ready_to_close` is true, and "Changed position because …" highlighted when present. Rejected claims for that agent appear struck through in red with the reason ("number 1000 not found in E1") — this is a feature, make it visible. A new round animates in as events arrive.
- **Right — EvidenceBoard + SpecialistFeed:** evidence list in order (id, capability icon, summary, "code" or "AI · conf 0.8" tag, who requested it). New items flash briefly. Clicking any item or chip opens **EvidenceDrawer** with the raw `data` JSON pretty-printed and, for material_exam, the photo. **SpecialistFeed** shows `specialist.selected` "why" sentences and `specialist.failed` lines — this is where judges see dynamic discovery and fallback.
- **Top — ConfidenceChart:** Recharts line chart, x = round, y = confidence 0–1, one line per agent in its color, point shape by stance (circle file, square dismiss, triangle need more).
- **Bottom — OutcomeBanner:** appears on `case.ended`: outcome word, stop reason in plain words ("All three agreed" for `unanimous`, "All three said they had nothing more to add" for `ready_to_close`, "Positions stopped moving", "Reached the round limit", "Budget limit reached"), and a button opening **CaseFileDrawer** (tip draft in monospace, "Prepared for human review — not sent" label, final positions, linked sellers, legal basis).
- **DemoControls** (small, bottom-right, hidden behind a "Demo" toggle): Remove listing (calls `removeListing(listing.id)`), Stop thorough examiner (calls `killSpecialist("deadlang-examiner-thorough")`), Reset demo, replay speed 1×/2×/4×, Skip to end.
- [ ] Step 1: Build all components against `{kind: "fixture"}` first.
- [ ] Step 2: Switch to live with Person C's API; watch a real case.
- [ ] Step 3: Check the screen at 1440×900 and on a 1280×720 projector fallback; nothing important below the fold.
- [ ] Step 4: Commit `ui: case page`.

---

### Task 6: Results page (`/results`)

**Files:** Create `frontend/src/app/results/page.tsx`

From `getEval()` and the examiner results (ask Person B to expose `results/examiner_eval.json` through the same endpoint or copy it into `frontend/public/`): a three-column comparison (A listing-only, B single agent with evidence, C three-agent review) for caught, false accusations, sent to a human, tokens per case, claims rejected; plus the examiner accuracy line; plus links to the example cases. Use plain labels: "Caught", "Wrongly flagged", "Sent to a person to decide".

- [ ] Step 1: Build with a hand-made JSON of the right shape; switch to real data when Person C posts results. Step 2: Commit `ui: results`.

---

### Task 7: Architecture diagram

**Files:** Create `pitch/architecture.png` (+ source file)

One diagram, left to right: **Marketplace (MCP server, recorded real listings)** → **Specialists** (Price Checker, Seller Inventory, Linked Sellers, Legal Table — labeled "code"; Material Examiner thorough + quick, Translator — labeled "AI") → **Evidence board (E0, E1, …)** → **Buyer / Defender / Caseload** (each with its goal in 5 words; they can question each other directly and speak only when something relevant changed) ↔ **Facilitator (wakes agents on change, checks claims, applies a published rule — a referee that decides nothing)** → **Outcome: FILE / DISMISS / CONTESTED / WATCHLIST → human review**. Show the AGNTCY layer as a band underneath: "A2A over SLIM · broadcast to the agents called each round · AGNTCY Directory for finding specialists by capability". Mark which parts are ours vs AGNTCY.

- [ ] Step 1: Draft; show Persons B and C for accuracy. Step 2: Commit `docs: architecture diagram`.

---

### Task 8: Deck (target 8 slides, 3 minutes with the live demo inside)

**Files:** Create `pitch/deck.pdf` (+ source)

1. **Title:** Dead Language — "Agents that disagree, so honest sellers don't get flagged and real ivory doesn't get missed." Team names.
2. **Problem:** 266,535 wildlife products on 61 marketplaces (Apr 2024–Mar 2026); eBay banned ivory in 2009 yet researchers found ivory sold as "bone" and only 1.3–6.9% removed a month later. Sources in small text.
3. **Insight:** "A coded listing has two readers." Visual: one listing, the filter sees "bone carving", the buyer sees the $1,450 price and the close-up of the base. "They can hide the word ivory. They can't hide the price."
4. **How it works:** the architecture diagram, simplified. Three agents, competing goals, neutral specialists, nobody in charge.
5. **Live demo** (switch to the browser; see Task 9).
6. **Grounded by design:** "Click any claim — nothing is made up." Facts mostly from code; every claim cites evidence; code checks numbers and quotes; rejected claims shown. Examiner accuracy from `results/examiner_eval.json`.
7. **Results:** single agent vs three-agent review from `results/eval.json`. Honest footnote: trafficking cases are reconstructed from documented ones; negatives are real listings.
8. **Who uses it + what's next:** the three users from Task 1; next: connect a real marketplace (one connector), more species, more languages.

- [ ] Step 1: Draft slides 1–4 and 8 by hour 6. Step 2: Slides 6–7 after results land. Step 3: Commit PDF `docs: deck`.

---

### Task 9: Demo script and rehearsals

**Files:** Create `pitch/demo_script.md`, `pitch/qa.md`

**`demo_script.md`** — exact words and clicks with timings (total ≈ 3:00):
- 0:00–0:20 Hook (slides 1–3).
- 0:20–1:35 **D1 network case** live (or replay at 2× if anything is slow): point at the price evidence, the round-1 split, the Defender asking for a close exam, the examiner's finding on photo N, the Defender changing position "because of E6", Caseload asking for linked sellers, the network appearing, outcome FILE, open the case file.
- 1:35–2:05 **D2 tagua case** (replay 4×): Buyer wants to file, Defender wins with examiner + normal price → DISMISS. Line: "It clears honest sellers too."
- 2:05–2:30 **Failure:** on D3, click "Remove listing" → overlay + system notice, Linked Sellers finds the relist; optionally stop the thorough examiner → feed shows the fallback sentence.
- 2:30–2:50 Results slide.
- 2:50–3:00 Close: "Every accusation gets a defender. Click any claim — nothing is made up."
- A **fallback column** for each step: what to click if live fails (replay name and speed).

**`qa.md`** — prepared answers (two sentences each): What if you accuse an honest antique dealer? · Isn't this just one model with three prompts? (separate agents with separate objectives, run as independent AGNTCY agents, a fixed outcome rule, and measured differences vs single agent) · How do you stop hallucinations? · Is scraping allowed? (fixed dataset; real product plugs into a marketplace's own moderation feed) · Doesn't NYU already do this? (keyword search + one-listing classification; we read like a buyer, follow the seller, and produce case files) · What does it cost per listing? (from eval.json) · Why does Caseload exist? · When does it ask a human? · What did you learn? (pull 2–3 real findings from the eval and examiner results).

- [ ] Rehearsal 1 after the 8:00 checkpoint (rough), rehearsal 2 Sunday 9:00 AM, rehearsals 3–4 after the 10:30 freeze with a stopwatch. Each rehearsal: note what broke, tell the owner.
- [ ] Commit `docs: demo script + q&a`.

---

### Task 10: Devpost and backup video (Sunday morning)

**Files:** Create `pitch/devpost.md`, `pitch/backup_demo.mp4`

`devpost.md` sections (Cisco asked for the first four explicitly):
1. **Working demonstration** — link to the video; 3 sentences on what it shows.
2. **Architecture overview** — the diagram + one paragraph; a short list "What we built" vs "What came from AGNTCY / coffeeAGNTCY patterns".
3. **Technical implementation** — agents and their objectives, specialists (code vs AI), the evidence board and claim checks, the round protocol and outcome rule, AGNTCY broadcast + Directory discovery + fallback, the spend cap.
4. **Results and lessons learned** — numbers from `results/*.json`, what surprised us, where the system still fails, honest note on reconstructed positives.
5. Inspiration, challenges, what's next, built with (tags).

Backup video: screen-record the full demo (D1, D2, D3 + results) from replays at 1× with voiceover, 2:30–3:00. Upload unlisted to YouTube; link in Devpost.

- [ ] Step 1: Record video by **11:30 AM Sunday**. Step 2: Devpost text complete by **12:30 PM**. Step 3: **Submit by 1:00 PM** (deadline 1:30). Step 4: Commit `docs: devpost + video link`.

## Self-check before you call it done

- UI runs with backend off (replays) and on (live); demo controls work; 1440×900 looks right.
- No banned words: search the frontend and pitch folders for every banned word in Global Constraints and fix any hits.
- Every number in the deck traces to `results/` or spec §14 sources.
