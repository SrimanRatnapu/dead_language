# Dead Language — Design Spec

UCSC AI Hackathon @ SF Tech Week, Oct 10–11, 2026
Track: Cloud AI (Cisco Outshift / AGNTCY) — "When AI Agents Disagree", **Level 3: Collective Intelligence**
Also competing for: Overall Prize.
Submission: Devpost by **1:30 PM Sunday Oct 11**. Late = not judged.

Read this whole file before reading your own plan. Every plan assumes you know everything here.

---

## 1. The problem (one paragraph)

Illegal wildlife products, mainly elephant ivory, are sold openly on online marketplaces under disguised descriptions. A 2026 Global Initiative report counted about 266,000 wildlife products across 61 online marketplaces between April 2024 and March 2026; 84% of the animals sold violated CITES, and only 12% of posts were in English while most platform moderation is English-only. eBay has banned ivory since 2009, yet a University of Kent study (Tropical Conservation Science, 2021) found genuine ivory netsuke listed as "bone", identifiable only from photos, and a month after the researchers reported them eBay had removed only 1.3–6.9%. Smaller marketplaces that are not members of the Coalition to End Wildlife Trafficking Online (for example Craigslist, Mercari, Carousell, Shopee, Catawiki, LiveAuctioneers — none appear on the Coalition's member list as of Sept 2026) do even less. Today the work of spotting these listings is done by hand, including volunteer "cyber spotter" programs run by IFAW and WWF.

## 2. The key insight

A coded listing has two readers: the filter and the buyer. It has to fool the filter and still convince the buyer. So the real signal is always somewhere the buyer can see it:

- **Price.** A "bone" carving priced like ivory only makes sense if it is ivory. Sellers can change the words; they cannot hide the price, because the price is how the buyer knows.
- **Photos.** Close-ups of a base or cut surface show the cross-hatched grain pattern (Schreger lines) that only elephant ivory has. Researchers used exactly this to confirm the eBay cases.
- **Details that only matter if it's real** (weight, age claims, "serious buyers only").
- **The seller's other items, and other sellers using identical wording or identical photos.**

Pitch line: **"They can hide the word ivory. They can't hide the price."**

## 3. What we are building (one paragraph)

For every suspicious listing, three AI agents with **competing goals** review the case together. None of them is in charge. Neutral **specialists** (mostly plain code, a few AI) supply facts to a shared **evidence board**. The three agents argue over a few short rounds, citing evidence by ID, but there is **no fixed speaking order or turn script**: an agent speaks only when something relevant changed (new evidence, or a peer rebutted or questioned it), can put a question directly to a peer, and declares for itself when it is ready to close. The review ends when they all agree, are all ready to close, stop changing their minds, or run out of rounds. The result is one of four outcomes: **FILE** (a case file goes to a human for approval), **DISMISS**, **CONTESTED** (sent to a human with both sides' best arguments), or **WATCHLIST** (not enough evidence; re-check the seller later). Nothing is ever sent to authorities automatically.

### Language rule (applies to code, UI, slides, Devpost)

Do **not** describe the product as a courtroom or trial. Never use: court, courtroom, trial, verdict, jury, judge (as an agent role), prosecutor, defense lawyer, guilty. Use: case review, outcome, agents, evidence, positions. The agent names below (Buyer, Defender, Caseload) are fixed.

---

## 4. The agents

### 4.1 The three deliberating agents (competing objectives)

| Agent | Objective | Leans toward | Concedes when |
|---|---|---|---|
| **Buyer** | Work out what is *really* being offered, by reading the listing like an experienced collector would. Push to FILE when the listing only makes sense as ivory. | FILE | Price fits the stated material, photos show a legal material, and nothing about the listing would make a collector pay an ivory price. |
| **Defender** | Protect honest sellers from false accusations. Build the strongest innocent explanation the evidence allows: real bone, resin, tagua nut ("vegetable ivory"), "ivory" meaning a color, or a lawful exemption. | DISMISS | Evidence makes the innocent explanation implausible (e.g., examiner sees ivory grain AND price is many times the norm for the stated material). |
| **Caseload** | Protect scarce investigator time. Support FILE only when the case is worth a human investigator's hours: illegal where sold, protected species, meaningful value or quantity, and ideally a whole shop or a network rather than one item. | WATCHLIST for small one-offs; FILE for networks | Network or high value shown by evidence; or, for dismissing, evidence shows the item is legal. |

These three objectives genuinely conflict: Buyer vs Defender on whether the item is ivory, and Caseload vs both on whether a probably-illegal single cheap item is worth filing. That is the "genuine disagreement" Cisco asks for.

### 4.2 Specialists (neutral fact-finders; they never vote)

Specialists only report facts. They never take a position. This keeps the evidence neutral so all three agents argue from the same facts.

| Capability | Specialist | Implementation | What it returns |
|---|---|---|---|
| `listing_snapshot` | Intake | code | The full listing (text, price, photos list, seller) frozen at case start. Always evidence **E0**. |
| `price_check` | Price Checker | **code** | Typical price of comparable listings (same item type + same stated material), median and middle range, how many comparables, and the ratio of this listing's price to the median. Flags "weak comparison" when fewer than 5 comparables. |
| `seller_inventory` | Network Tracer | **code** | The seller's other listings (including removed ones), count, price total, how many share the stated material/type, price ratios. |
| `linked_sellers` | Network Tracer | **code** | Other sellers whose listings share rare multi-word phrases with this one, and listings that reuse the same photo (perceptual image hash). Returns the matching phrases and matched image pairs. |
| `legal_lookup` | Legal Table | **code** | From a fixed, sourced table: CITES appendix for the species, US federal rules, and the law where the sale happens (California Fish & Game Code §2022 bans almost all ivory sales). |
| `material_exam` | Material Examiner (thorough / quick) | **AI (vision)** | For each photo: material guess from a fixed list, confidence, which photo, and the visible features it based that on. Allowed and encouraged to answer `cannot_tell`. |
| `translation` | Language Specialist | **AI** | English translation of a non-English listing plus notable phrases with literal meanings. Only called when `language != "en"`. |
| `system_notice` | Facilitator | code | Facts about the process itself, e.g. "listing was removed by the seller at 14:02; a snapshot was kept as E0". |

There are **two** Material Examiners registered for the same capability: **thorough** (strong model, runs twice and only reports a material if both runs agree) and **quick** (cheaper model, single run, its confidence is capped at 0.6). The thorough one is preferred. If it is unavailable or times out, the system picks the quick one and says why. This is our "capability-based selection" and "respond to failure" story.

### 4.3 The Facilitator (not a decision-maker)

The Facilitator is plain code and a **referee of process only**: it runs the rounds, wakes the agents a change is relevant to, routes specialist requests to the right specialist (found by capability through the AGNTCY Directory), checks every claim against the evidence board, and applies the **pre-agreed stopping and outcome rules** below. It never decides the outcome itself; the outcome is a fixed, published function of the three agents' final stances that anyone can recompute from the public posts. It holds no opinion and can be replaced by any other implementation of the same rules. The Cisco brief explicitly allows "shared messaging or facilitation" as long as no supervisor imposes the final decision.

---

## 5. Grounding (anti-hallucination) — the most important rules

The three deliberating agents could make things up. Every rule below exists to stop that. Every person must respect these.

1. **Evidence first.** Before round 1, the Facilitator runs an **intake** pass: E0 snapshot, price_check, seller_inventory, linked_sellers, legal_lookup, material_exam on all photos, and translation if needed. The agents start round 1 with a full board.
2. **Most facts come from code.** Price, seller inventory, linked sellers, and legal status are computed by code. Code cannot invent facts. Only material_exam and translation use AI.
3. **Every evidence item has a one-sentence `summary` and raw `data`.** Every number in a summary also appears in its data.
4. **Every claim cites evidence.** A deliberating agent may only state facts inside `claims`, and each claim must list ≥1 evidence ID that exists on this case's board.
5. **Automatic claim checks (code, in the Facilitator):**
   - every cited ID exists on the board;
   - every number in the claim text matches a number in the cited evidence (within 10% relative or 0.5 absolute); evidence IDs like "E12" are ignored by this check;
   - every quoted phrase (text inside double quotes) appears in the cited evidence or the listing text, case-insensitive;
   - a stance change must give `changed_because` citing at least one existing evidence ID.
6. **Repair once, then drop.** If any claim fails, the agent gets one repair call listing exactly what failed. Claims that still fail are dropped and shown in the UI as rejected. If an agent ends up with **zero valid claims**, its stance is downgraded to `need_more` (you cannot take a side without a grounded reason).
7. **Agents have no web access and no other tools.** Their only way to get a new fact is to put a `SpecialistRequest` in their post. The answer goes on the board with a new ID for everyone.
8. **Material Examiner rules:** fixed answer list (`elephant_ivory`, `bone`, `resin_or_plastic`, `tagua_nut`, `wood`, `other`, `cannot_tell`); must name the photo index and the visible features; thorough mode reports a material only if two independent runs agree, otherwise `cannot_tell`. We measure its real accuracy on labeled museum photos and show that number.
9. **The UI shows the citation on every claim**; clicking it shows the raw evidence. Demo line: "Click any claim. Nothing here is made up."
10. **Labels are never visible to any agent.** Ground truth lives in a separate file used only by the evaluation runner.

---

## 6. Deliberation protocol

- **Rounds:** up to **4**. In round 1 all three agents are sent the same snapshot (board + transcript) **at the same time** (AGNTCY broadcast), so nobody gets an ordering advantage. From round 2 an agent is called **only if triggered**: (a) new evidence was added since its last post, (b) another agent's validated post targets it (a rebuttal or a challenge), or (c) a specialist it requested has answered. An untriggered agent keeps its previous post and is not called.
- **Each post** (`StancePost`) contains: stance (`file` / `dismiss` / `need_more`), confidence 0–1, claims with evidence IDs, a rebuttal (required from round 2 when the agent is called: answer the strongest opposing claim from the previous round), up to 2 specialist requests, an optional **challenge** (one question to one named peer, which that peer must answer in its next post), `ready_to_close` (true when the agent has nothing more to add), and `changed_because` if the stance changed.
- **Between rounds:** the Facilitator validates posts (Section 5), runs requested specialists (max 3 specialist calls per round, max 6 per case, duplicates merged), adds results to the board, and emits events for the UI.
- **Stop after a round when any of these is true:**
  1. **Unanimous:** all three stances are `file`, or all three are `dismiss`.
  2. **Agreed to close:** from round 2 on, all three current posts have `ready_to_close = true`.
  3. **No movement:** no agent changed stance, every agent's confidence moved by less than 0.10, and no new evidence was added this round (this includes a round in which no agent was triggered).
  4. **Max rounds:** round 4 finished.
  5. **Budget:** the case hit its token cap.
- **Outcome rule (applied to the final stances):**
  - all `file` → **FILE**
  - all `dismiss` → **DISMISS**
  - at least one `file` AND at least one `dismiss` → **CONTESTED** (keep the disagreement, send to a human with each side's best argument)
  - anything else (some `need_more`, no file-vs-dismiss conflict) → **WATCHLIST**
- **Why unanimity for FILE:** a false accusation is costly, so any one agent can block filing — but blocking with a grounded reason against another agent's grounded reason produces CONTESTED, which goes to a human. The system never hides disagreement.
- **Outcome rule is public:** the mapping above and the stop rules are written down before any case runs and are the only thing that ends a case. The Facilitator cannot override them, and the UI shows which rule ended each case.
- **When to ask a human:** FILE (approval before anything is sent) and CONTESTED (decide). This answers Cisco's "explain when the system should stop, preserve disagreement, or seek human input."

### Case file (FILE and CONTESTED)

Seller, listing(s), linked sellers, the full evidence list, each agent's final position and best claims, legal basis (from legal_lookup), and a drafted tip in plain language assembled from validated claims only. Status `awaiting_human_review`. Never auto-sent.

---

## 7. Data: recorded real listings + our own marketplace

We do **not** scrape live during the demo. We build a fixed dataset and serve it through our own marketplace server (an MCP server shaped like a marketplace API).

- **Real innocent look-alikes (~200–300):** pulled once from the eBay Browse API (antique carvings, netsuke, bone carvings, resin figurines, tagua / vegetable ivory, faux ivory jewelry), with up to 3 photos each. Fallback if eBay keys don't work: hand-copy ~60 listings with a CSV template.
- **Reconstructed trafficking cases (15–20):** written by the team following the patterns documented in published research (Kent 2021 eBay study; the Oryx EU code-word study), at pattern level: wrong material named, ivory-level price, close-up of base. Photos come from **The Met Open Access** collection (CC0, public domain) using objects whose `medium` field says ivory. Each is marked `is_reconstructed: true` with a citation. We say this openly in the pitch: live trafficking listings get taken down, so we rebuilt documented ones.
- **Designed seller networks (3):**
  - **N1 "linked network":** 3 sellers sharing rare phrasing, one photo reused across two sellers, ivory-level prices.
  - **N2 "shop":** one seller with ~6 "bone" netsuke all at ivory-level prices.
  - **N3 "honest dealer":** a seller of genuinely old bone and tagua items at normal prices. This is the hard negative.
- **Relist:** one hidden listing under a new seller account with the same photo and near-identical text; it becomes visible when the original is removed (demo moment).
- **Museum photo test set:** ~40 Met Open Access objects labeled by their `medium` (ivory / bone / wood / other) to measure Material Examiner accuracy.
- **Labels file** (ground truth) used only by evaluation.

**Pitch line on data:** "Connecting a real marketplace means swapping one connector — the agents only talk to the marketplace through the same tool interface."

---

## 8. AGNTCY usage (Cisco sponsor stack)

- **Agents as A2A servers over SLIM** (SLIM patterns transport): all 3 deliberating agents and all specialists run as separate A2A agents with AgentCards.
- **Broadcast:** each round is sent to the 3 deliberating agents with `broadcast_message` (parallel fan-out over SLIM).
- **Directory discovery:** every specialist's AgentCard is pushed to the AGNTCY Directory at startup. When an agent requests a capability, the Facilitator searches the Directory, reads candidate cards' skill tags (`capability:<name>`), picks one by a stated rule (preferred quality tier → healthy → fastest), and emits a `specialist.selected` event explaining why.
- **Fallback (must exist):** a `TRANSPORT=local` mode that calls the same agent handler classes in-process, and a local card registry with the same search interface. If SLIM or the Directory misbehaves during the demo, flip one env var. Every agent is written as a plain async handler first; AGNTCY is a thin wrapper around it.
- In the Devpost writeup, clearly separate what came from AGNTCY/coffeeAGNTCY patterns and what we built.

## 9. Demo (about 3 minutes)

1. **Hook (20s):** "266,000 wildlife products across 61 marketplaces. eBay banned ivory in 2009 and still missed it. They hide the word ivory — they can't hide the price."
2. **Case 1 — network (75s):** a "bone" netsuke at ~10× the typical price. Intake fills the board. Round 1: Buyer FILE, Defender DISMISS ("could be antique bone"), Caseload WATCHLIST ("one item"). Defender requests a closer material exam → thorough examiner reports ivory grain on the base photo → Defender changes position, citing the new evidence. Caseload requests linked sellers → two linked sellers sharing phrasing and a reused photo → Caseload moves to FILE. Outcome FILE; case file shown.
3. **Case 2 — innocent (30s):** a tagua carving. Buyer wants to file; Defender wins with examiner (tagua) + price that fits. DISMISS. "It clears honest sellers too."
4. **Failure (25s):** click "seller removes listing" mid-case. Agents continue from the E0 snapshot; Network Tracer finds the relist under a new account by its reused photo. Optionally stop the thorough examiner process live → system picks the quick examiner and says why.
5. **Results (20s):** one slide: single agent vs the three-agent review on our labeled set (misses, false accusations, cost per listing, rejected claims). Use only numbers we actually measured.
6. **Close (10s):** "Every accusation gets a defender. Click any claim — nothing is made up." Hand a judge the keyboard if time allows.

Always have a **recorded replay** of each demo case (event log JSON) that the UI can play back without the backend, plus a backup screen recording.

## 10. Evaluation (Cisco wants "comparison against a simpler baseline" and "learning and evidence")

Run three modes over a fixed, stratified eval set (all ~15–20 reconstructed positives + ~40 hard negatives: tagua, real bone, resin, antiques; fixed random seed):

- **A. Listing-only single agent:** one model call sees E0 only and answers file/dismiss.
- **B. Single agent with the same evidence:** one model call sees the full intake board, same claim validator.
- **C. Three-agent review (ours).**

Metrics per mode: caught (positives with FILE, or FILE+CONTESTED reported separately), false accusations (negatives with FILE), sent-to-human rate (CONTESTED), average tokens per case, claims rejected by the validator, and number of position changes caused by new evidence. Plus Material Examiner accuracy on the museum photo set. Be honest in the writeup that positives are reconstructed, so numbers are indicative.

## 11. Tech stack and models

- **Backend:** Python 3.12 (required by `agntcy-app-sdk`), `uv`, FastAPI (API + Server-Sent Events), `agntcy-app-sdk` 0.5.x, `a2a-sdk` 0.3.20 (pinned by the SDK), MCP Python SDK (FastMCP) for the marketplace server, `anthropic` SDK, `pydantic` v2, `imagehash` + `Pillow`, `pytest`.
- **Infra:** Docker Compose with SLIM (`ghcr.io/agntcy/slim:1.0.0`), Directory (`ghcr.io/agntcy/dir-apiserver:v1.0.0-rc.3`) and `zot`, copied from `agntcy/app-sdk/services/docker/docker-compose.yaml`.
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind; Recharts for the confidence chart.
- **Models (Anthropic, key already in `ANTHROPIC_API_KEY`):** `claude-sonnet-5-5` for the three deliberating agents, the thorough Material Examiner, and baselines A/B; `claude-haiku-4-5-20251001` for the quick Material Examiner, translation, and triage. Model names live in config, never hard-coded in agents.
- **Spend cap from the first commit:** a single LLM wrapper that every model call goes through, tracking input/output tokens in a file, with a global cap and a per-case cap, no automatic retry loops (max 1 retry on transient API errors), and a hard stop that raises an error and emits `budget.exceeded`.

## 12. Team split

| Person | Owns | Plan file |
|---|---|---|
| **A — Data & Marketplace** | dataset, labels, marketplace store + MCP server, code specialists (price, seller inventory, linked sellers, legal), relist/remove demo controls | `02-person-A-data-and-marketplace.md` |
| **B — Agent Network & AI Specialists** | Docker/SLIM/Directory, AGNTCY wrappers, discovery + selection, LLM wrapper + spend cap, Material Examiners, Language specialist, triage scores, process runner | `03-person-B-agent-network-and-ai-specialists.md` |
| **C — Deliberation, API & Evaluation** | the three agents' prompts, claim validator, round protocol, outcomes, case file, Facilitator, FastAPI + SSE events + replay logs, baselines + eval runner | `04-person-C-deliberation-api-eval.md` |
| **D — Product, UI & Pitch** | Next.js UI, demo flow, use cases, value proposition, pitch deck, demo script, Devpost writeup, architecture diagram, backup video | `05-person-D-product-ui-pitch.md` |

Shared kickoff and the frozen contracts (data models, event stream, ports, env vars, timeline) are in `01-shared-contracts-and-kickoff.md`. **Read it right after this file.**

## 13. Out of scope (do not build)

Live scraping or crawling; Browserbase; any automatic submission of tips; species other than elephant ivory; user accounts/auth; a database server (files + memory are enough); ElevenLabs/voice; mobile layout beyond "doesn't break".

## 14. Sources (for the pitch and Devpost)

- Mongabay, May 2026 — Facebook hub for illegal wildlife trade (266,535 products, 61 marketplaces, 84% CITES violations, 12% English): https://news.mongabay.com/2026/05/facebook-is-a-hub-for-illegal-wildlife-trade-and-thats-by-design-report-says/
- EcoWatch on the Kent eBay study (ivory listed as bone; 1.3–6.9% removed after a month): https://www.ecowatch.com/ebay-illegal-ivory-products-2649935488.html
- Coalition to End Wildlife Trafficking Online member list: https://www.endwildlifetraffickingonline.org/aboutthecoalition-1
- NYU-led LLM study (closest prior work; keyword search, per-listing classification): https://arxiv.org/html/2504.21211v1
- IFAW cyber-spotter program: https://www.ifaw.org/international/journal/we-need-everyones-help-ifaws-cyber-spotter-program-tackles-wildlife-cybercrime
- USFWS elephant ivory FAQ (federal rules): https://www.fws.gov/frequently-asked-questions-about-elephant-ivory
- California Fish & Game Code §2022: https://codes.findlaw.com/ca/fish-and-game-code/fgc-sect-2022/
- The Met Open Access (CC0 images): https://github.com/metmuseum/openaccess
- Cisco track statement + AGNTCY: https://github.com/agntcy/app-sdk , https://github.com/agntcy/coffeeAgntcy
