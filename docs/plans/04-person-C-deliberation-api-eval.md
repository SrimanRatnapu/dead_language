# Person C — Deliberation, API & Evaluation Build Plan

> Read `00-watchdog-design-spec.md` and `01-shared-contracts-and-kickoff.md` first. This plan assumes both.
> Steps use `- [ ]` checkboxes. Each task ends with tests passing and a commit prefixed `delib:`.

**Goal:** Build the heart of the product: the three deliberating agents (Buyer, Defender, Caseload), the claim validator that keeps them grounded, the round protocol with pre-agreed stopping and outcome rules, the case file, the Facilitator that runs a case end to end, the API + live event stream the UI consumes, replay recording, and the baseline comparison that produces our results numbers.
**Architecture:** `Facilitator.run_case` creates an `EvidenceBoard`, runs intake through `Discovery` + `AgentTransport` (Person B) and the specialists (Persons A, B), then loops rounds: broadcast `DeliberationTurn`s → validate each `StancePost` (repair once) → run requested specialists → check stop rules. Outcome is a pure function of final stances. Every step emits an `Event` on an `EventBus` that FastAPI streams over SSE and also writes to a replay log.
**Tech Stack:** Python 3.12, FastAPI, sse-starlette, pydantic v2, pytest + pytest-asyncio.

## Global Constraints (in addition to file 01)

- The Facilitator is a referee of process, never a decider. It never decides an outcome by judgment. It only applies `rules.py` (published stop and outcome functions) and decides *who is called* by the mechanical triggers in Task 7.
- Deliberating agents get **no tools**. Their only way to get facts is `requests` in their post.
- Prompts are files in `deliberation/prompts/`, loaded at runtime, so prompt edits don't need code changes.
- Every event is also appended to `fixtures/replays/runs/<case_id>.jsonl` (gitignored except the curated ones you copy to `fixtures/replays/<name>.jsonl`).
- You can and should build Tasks 2–6 against fakes before Persons A/B are ready: a `FakeTransport` and `FakeDiscovery` in `tests/fakes.py` that return canned `SpecialistReply`s and scripted `StancePost`s.

## Files you own

`backend/pyproject.toml`, `backend/deadlang/schemas.py`, `backend/deadlang/evidence/board.py`, `backend/deadlang/deliberation/*`, `backend/deadlang/api/*`, `backend/deadlang/eval/{baselines.py,run_eval.py}`, `fixtures/*`, `results/eval.json`, `.env.example`, tests `test_board.py`, `test_validator.py`, `test_rules.py`, `test_agents.py`, `test_facilitator.py`, `test_api.py`, `tests/fakes.py`.

---

### Task 1: Kickoff deliverables

- [ ] Step 1: Create the repo skeleton (file 01 §2), `backend/deadlang/schemas.py` exactly as file 01 §3, `.env.example` exactly as file 01 §5. Run `uv run python -c "import deadlang.schemas"`.
- [ ] Step 2: Write `fixtures/sample_case_events.jsonl` following file 01 §6 (12+ events, valid against `Event`; write a tiny test `tests/test_fixture.py` that loads every line with `Event.model_validate_json` and each payload with the right model).
- [ ] Step 3: Commit `delib: schemas + fixture`. Tell Person D the fixture is ready.

---

### Task 2: EvidenceBoard

**Files:** Create `backend/deadlang/evidence/board.py` · Test `backend/tests/test_board.py`

**Produces:**
- `class EvidenceBoard(case_id: str)`
- `add(draft: EvidenceDraft, requested_by: Requester) -> Evidence` — assigns `E0`, `E1`, … in order.
- `get(evidence_id) -> Evidence | None`, `all() -> list[Evidence]`, `ids() -> set[str]`, `added_since(n: int) -> list[Evidence]`, `count() -> int`.
- `numbers_in(evidence_ids: list[str]) -> list[float]` — every number found in those items' `summary` plus every numeric value found recursively in their `data` (ints, floats, and numbers inside strings), commas stripped.
- `text_in(evidence_ids) -> str` — lowercase concatenation of summaries and every string found recursively in `data` (used for quote checks).
- `render_for_prompt() -> str` — one block per evidence item:
  `E3 · price_check · by deadlang-price-checker (code) · requested by intake`
  `  Summary: <summary>`
  `  Data: <compact JSON of data, truncated to 1,200 chars>`
  plus `  Model confidence: 0.8` when present.

- [ ] Steps 1–5: tests (id sequence; numbers_in finds 15.3 in summary, 95 in data, 1450 from "$1,450"; text_in finds a nested shared phrase; render contains ids), implement, pass, commit `delib: evidence board`.

---

### Task 3: Claim validator

**Files:** Create `backend/deadlang/deliberation/validator.py` · Test `backend/tests/test_validator.py`

**Produces:**
```
@dataclass
class Rejection: agent: AgentName; round: int; claim_text: str; reasons: list[str]

def validate_post(post: StancePost, board: EvidenceBoard, listing_text: str,
                  previous: StancePost | None, round_no: int,
                  last_round_posts: list[StancePost]) -> tuple[StancePost, list[Rejection], list[str]]
# returns (cleaned_post, rejections, post_level_problems)
```

**Claim-level checks (a failing claim is removed from `cleaned_post.claims` and reported as a Rejection):**
1. `evidence_ids` non-empty → else reason `"no evidence cited"`.
2. every id exists on the board → else `"cites E9, which does not exist"`.
3. **Number check:** first remove evidence-id tokens (`\bE\d+\b`); then extract numbers with regex `\d[\d,]*(?:\.\d+)?` and strip commas. Percentages are checked like any other number. Ignore integers ≤ 3 (small counts like "2 photos" are too noisy to check). Each remaining number must match some number from `board.numbers_in(evidence_ids)` within 10% relative difference or 0.5 absolute. Also accept a number if it equals a ratio `a/b` of two numbers in the cited evidence rounded to 1 decimal (so "about 15x" works when the data has price and median). Reason: `"number 1000 not found in cited evidence E1"`.
4. **Quote check:** every substring inside double quotes (straight or curly) with ≥ 3 words must appear (lowercase, whitespace-collapsed) in `board.text_in(ids)` or in `listing_text`. Reason: `"quoted text not found in cited evidence or listing"`.

**Post-level checks (reported as `post_level_problems`, used for the repair call):**
5. Round ≥ 2, the agent was called this round, and `rebuttal` missing → `"round 2+ requires a rebuttal of the strongest opposing claim"`. Rebuttal `target_claim` must fuzzy-match (token overlap ≥ 0.6) a claim from `last_round_posts` of `target_agent` → else `"rebuttal target claim not found"`. Rebuttal `evidence_ids` must exist.
6. Stance differs from `previous.stance` and (`changed_because` empty or `changed_because_evidence` empty or any id missing) → `"stance changed without citing the evidence that changed it"`.
7. `len(requests) > 2` → keep the first 2, problem `"max 2 requests"`.
8. `confidence` outside 0–1 is already prevented by the schema.
9. `challenge` present and `challenge.target_agent == post.agent` → drop the challenge, problem `"cannot challenge yourself"`. (Answering a received challenge is prompt-enforced only, not validated.)

**After repair (Task 6 decides when):** if `cleaned_post.claims` is empty and stance is `file` or `dismiss`, set stance to `need_more` and add problem `"no grounded claims left; stance set to need_more"`.

- [ ] Step 1: Write failing tests, one per rule, using a board with: E0 listing (price 1450), E1 price_check (median 95, ratio 15.3, n 38), E2 linked_sellers with shared phrase "ships discreetly from our family collection". Include: valid claim passes; "$1,450" passes; "15x" passes (within 10%); "1000" fails; quote of the shared phrase passes; invented quote fails; missing id fails; stance change without evidence flagged; round-2 missing rebuttal flagged; empty claims → need_more.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Commit `delib: claim validator`.

---

### Task 4: Stop and outcome rules

**Files:** Create `backend/deadlang/deliberation/rules.py` · Test `backend/tests/test_rules.py`

**Produces:**
```
def outcome(final: dict[AgentName, Stance]) -> Outcome
def stop_reason(round_no: int, max_rounds: int,
                this_round: dict[AgentName, StancePost],   # all three agents' CURRENT posts (carried-forward ones included)
                prev_round: dict[AgentName, StancePost] | None,
                new_evidence_this_round: int) -> str | None   # "unanimous" | "ready_to_close" | "no_movement" | "max_rounds" | None
```

Rules exactly as spec §6:
- `outcome`: all file → FILE; all dismiss → DISMISS; ≥1 file and ≥1 dismiss → CONTESTED; else WATCHLIST.
- `stop_reason`: unanimous (all file or all dismiss) → `"unanimous"`; else if `round_no >= 2` and all three posts have `ready_to_close` → `"ready_to_close"`; else if `prev_round` exists and no stance changed and every |Δconfidence| < 0.10 and `new_evidence_this_round == 0` → `"no_movement"`; else if `round_no >= max_rounds` → `"max_rounds"`; else None. (Budget stop is handled by the Facilitator.)

- [ ] Step 1: Table-driven failing tests covering all four outcomes and every stop branch (including "all need_more" → WATCHLIST, round 1 never returns no_movement or ready_to_close, and carried-forward posts count as unchanged).
- [ ] Step 2–4: implement → PASS. Step 5: commit `delib: rules`.

---

### Task 5: Prompts for the three agents

**Files:** Create `backend/deadlang/deliberation/prompts/shared_rules.md`, `buyer.md`, `defender.md`, `caseload.md`

These are product-critical. Write them exactly as below, then tune wording (not rules) after the first live runs. System prompt for each agent = role file + "\n\n" + shared_rules.

**`shared_rules.md`:**
> You are one of three agents reviewing one marketplace listing for possible disguised elephant ivory. The other two agents have different goals from yours. No one is in charge; the outcome is decided by a fixed rule: the listing is filed for human review only if all three of you choose "file"; it is dismissed only if all three choose "dismiss"; if at least one chooses "file" and at least one chooses "dismiss", it goes to a human as contested; otherwise it goes on a watchlist.
>
> Rules you must follow:
> 1. Every factual statement goes in `claims`, and every claim must cite evidence IDs from the evidence board (E0, E1, …). Code checks every claim: numbers you write must appear in the evidence you cite, and anything you put in double quotes must appear word for word in that evidence or the listing. Claims that fail are deleted.
> 2. Do not use outside knowledge as fact. You may use general reasoning ("a collector would not pay this much for bone"), but the facts it rests on must be on the board.
> 3. If you need a fact that is not on the board, ask for it in `requests` (at most 2). Available capabilities: price_check, seller_inventory, linked_sellers, legal_lookup, material_exam (you can pass {"image_index": n} to examine one photo closely), translation. The answer will appear on the board next round for everyone.
> 4. From round 2 on, whenever you are called, you must rebut the strongest claim made against your position in the previous round (`rebuttal`), quoting that claim's text in `target_claim`. If `questions_for_you` is not empty, answer each question with cited claims.
> 5. If you change your stance, say exactly which evidence changed your mind (`changed_because` and `changed_because_evidence`). Changing your mind when evidence warrants it is good; holding a position the evidence no longer supports is bad.
> 6. "need_more" means you cannot take a side yet and have asked for something specific.
> 7. Confidence is your probability that your stance is the right one.
> 8. Be brief: at most 4 claims, each one sentence.
> 9. Never invent seller names, prices, photo contents, laws, or statistics.
> 10. You may put one question to one other agent in `challenge` when you think their position rests on something they have not defended. Use it sparingly.
> 11. Set `ready_to_close = true` only when you have nothing more to add and would not change your stance without new evidence. The review closes early only if all three of you do this.

**`buyer.md`:**
> You are the Buyer. You think like an experienced collector of Asian carvings who knows the ivory market well. Your goal is to work out what is really being offered. A disguised listing has to fool the filter but still convince a buyer, so ask what a collector would conclude from: the price compared with what the stated material normally sells for; photos that show close-ups of a base or cut surface; details that only matter if the item were ivory; the seller's other items; and other sellers using the same wording or photos.
> You lean toward "file" when the listing only makes sense as ivory. Concede ("dismiss") when the price fits the stated material, the photos show a legal material, and nothing would make a collector pay an ivory price.

**`defender.md`:**
> You are the Defender. Your goal is to protect honest sellers from false accusations. For every listing, build the strongest innocent explanation the evidence allows: genuine bone, resin or plastic, tagua nut (often called "vegetable ivory"), "ivory" used as a color name, a cheap item priced high by an optimistic seller, or a lawful exemption shown by the legal evidence.
> You lean toward "dismiss". Ask for the specialist checks that could clear the seller (for example a close material exam of a specific photo, or a price check). Concede ("file") only when the evidence makes the innocent explanation implausible — for example the material examiner reports ivory features on a photo and the price is many times what the stated material sells for. A seller removing a listing is not, by itself, evidence that the item is illegal.

**`caseload.md`:**
> You are Caseload. You represent a small wildlife-crime investigation team with very limited hours. Your goal is to make sure that only cases worth an investigator's time get filed. Weigh: whether the sale is illegal where the item ships from (use legal_lookup evidence); how protected the species is; the value and number of items; and whether this is one item or a pattern — a seller with many similar items, or several linked sellers, is worth far more than a single listing.
> You lean toward "need_more" or "dismiss" for single low-value items even if they look suspicious, and toward "file" for patterns and networks. Ask for seller_inventory or linked_sellers when the pattern question is open. If the item is clearly legal, choose "dismiss".

- [ ] Step 1: Write the four files. Step 2: commit `delib: agent prompts`.

---

### Task 6: DeliberatingAgent

**Files:** Create `backend/deadlang/deliberation/agents.py` · Test `backend/tests/test_agents.py`

**Produces:** `class DeliberatingAgent(name: AgentName)` with `async handle(turn: DeliberationTurn) -> StancePost`.

**Behavior:**
- System prompt = role file + shared rules.
- User message sections in this order: `# Listing under review` (E0 summary + listing title/description/price verbatim) · `# Evidence board` (`board.render_for_prompt()` equivalent built from `turn.evidence`) · `# What happened in earlier rounds` (each validated post: agent, stance, confidence, claims with ids, rebuttal, requests) · `# Your previous post` · `# This round` ("Round {r} of {max}. Post your position.") · `# Fix these problems` (only when `repair_feedback` is set: each problem and each rejected claim with its reason, then "Repost your full position with these fixed.").
- Schema: `StancePost.model_json_schema()` with `agent` and `round` removed from properties/required (the code fills them). `schema_name="post_position"`, `model=MODEL_STRONG`, `max_tokens=1200`, `temperature=0.2`, `case_id=turn.case_id`.
- Parse with `StancePost.model_validate({...output, "agent": self.name, "round": turn.round})`. On a pydantic error, raise; the Facilitator treats it as that agent's failure for the round (its previous stance carries over, see Task 7).

- [ ] Step 1: Failing tests with a fake `llm.call_json` that returns a canned dict: agent/round are filled; repair feedback appears in the user message; the schema passed has no `agent`/`round`.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: One live smoke call against the sample fixture board; paste the output into the PR description. Commit `delib: deliberating agent`.

---

### Task 7: Facilitator (runs one case end to end)

**Files:** Create `backend/deadlang/deliberation/facilitator.py`, `backend/deadlang/deliberation/casefile.py`, `backend/tests/fakes.py` · Test `backend/tests/test_facilitator.py`

**Produces:**
```
class Facilitator:
    def __init__(self, market: MarketplaceClient, transport: AgentTransport,
                 discovery: Discovery, bus: EventBus, max_rounds: int = 4): ...
    async def run_case(self, case_id: str, listing_id: str) -> CaseFile
    async def notify_listing_removed(self, listing_id: str, relisted_as: str | None) -> None
```

**Flow:**
1. **Start:** snapshot = `market.get_listing_snapshot(listing_id)`, seller = `get_seller`. Emit `case.started`. Add E0: capability `listing_snapshot`, `produced_by="code"`, `specialist_name="intake"`, summary `"Listing {id} by {seller.name}: \"{title}\" for ${price:,.0f}, described as {stated_material}, ships from {ship_from}, {n} photos."`, data = full listing dump. Emit `evidence.added`.
2. **Intake** (requested_by `"intake"`, run concurrently): price_check, seller_inventory, linked_sellers, legal_lookup, material_exam (all photos), translation (only if `language != "en"`). Each goes through `_run_specialist`.
3. **`_run_specialist(capability, params, requested_by)`:** `sel = discovery.select(capability, exclude=tried)`; emit `specialist.selected` with `sel.why`; `reply = transport.call_specialist(sel.specialist_name, SpecialistCall(...))`; on `ok=False`: if error is `"timeout"` or a connection error → `discovery.mark_unhealthy`, emit `specialist.failed` with the next selection's name as `fallback`, and retry once with the next candidate (only one fallback hop); if error is `"listing_removed"` → call `notify_listing_removed` and stop; any other error → emit `specialist.failed` with `fallback: null`. On `ok=True` add every draft to the board (emit `evidence.added` each).
4. **Rounds** `r = 1..max_rounds`: decide the **active** agents mechanically. Round 1: all three. Round ≥ 2: an agent is active if (a) the board has evidence added after that agent's previous turn, or (b) a validated post from the previous round has it as `rebuttal.target_agent` or `challenge.target_agent`. Emit `round.started` with `active`. Build one `DeliberationTurn` per active agent (shared evidence + transcript; per-agent `your_previous`; `questions_for_you` from the previous round's challenges aimed at it). `results = transport.broadcast_turns(turns)`. Inactive agents are not called; their previous post is carried forward unchanged and not re-emitted.
   - For each active agent: error string → reuse its previous post (round > 1) with `confidence` unchanged, or a `need_more` post with zero claims in round 1; log it.
   - Validate each post (Task 3). If any rejections or post-level problems → **one** repair call via `transport.call_agent(agent, turn with repair_feedback)`; validate again; remaining rejections → emit `claim.rejected` for each; apply the empty-claims rule.
   - Emit `stance.posted` for each cleaned post of an active agent (order: buyer, defender, caseload).
   - Collect `requests` from the active posts; dedupe by `(capability, json(params))`; keep at most 3 this round and stop accepting new ones once the case has run 6 requested specialist calls. Run them (requested_by = the asking agent; if two agents asked for the same thing, use the first). Count new evidence items.
   - `reason = rules.stop_reason(...)` using all three current posts (carried-forward included). If set → break. If no agent was active in a round, that round is a no-op and `stop_reason` returns `no_movement`.
   - Wrap each round in `try/except BudgetExceeded` → emit `budget.exceeded`, `reason = "budget"`, break.
5. **End:** `outcome = rules.outcome(final stances)`; build the `CaseFile` (casefile.py); emit `case.ended`; return it.
6. **`notify_listing_removed`:** add a `system_notice` evidence item: `"Listing {id} was removed by the seller at {HH:MM}; the review continues from the snapshot in E0."` plus, if `relisted_as`, a second notice `"A new listing {relisted_as} appeared after the removal; linked_sellers can check whether it is related."`; emit `listing.removed`. The API's remove endpoint calls this for every running case on that listing.

**`casefile.py`:** `build_case_file(case_id, listing, seller, outcome, rounds_used, stop_reason, final_posts, board) -> CaseFile`. `legal_basis` = summaries of `legal_lookup` evidence. `linked_seller_ids` = from linked_sellers evidence data. `tip_draft` (FILE and CONTESTED only) is a **code template**, no model:

```
Possible elephant ivory offered for sale — prepared for human review, not sent.
Listing: {id} "{title}" — ${price} — ships from {ship_from} — seller {seller.name} ({seller.id})
Outcome of agent review: {outcome}
Key evidence:
- {claim text} [{ids}]            (validated claims from the final posts, deduplicated, max 6)
Linked sellers: {names or "none found"}
Legal basis: {legal summaries}
Positions: Buyer {stance} ({conf}), Defender {stance} ({conf}), Caseload {stance} ({conf})
```

- [ ] Step 1: In `tests/fakes.py` write `FakeTransport` (scripted posts per agent per round; scripted specialist replies; can be told to time out a named specialist) and `FakeDiscovery` (thorough then quick).
- [ ] Step 2: Failing tests: (a) unanimous FILE in round 2 after a requested material_exam adds E-new and the Defender changes stance citing it; (b) CONTESTED after max rounds; (c) thorough examiner times out → `specialist.failed` + quick used; (d) invented-number claim is rejected after a repair that still fails → `claim.rejected` event; (e) listing removed mid-case → system_notice evidence + `listing.removed` event and case continues; (f) `BudgetExceeded` during round 2 → `stop_reason="budget"`; (g) event `seq` strictly increasing.
- [ ] Step 3–4: implement → PASS.
- [ ] Step 5: With Persons A and B's local-mode pieces merged, run a real case: `uv run python -m deadlang.deliberation.facilitator --listing <d1 id>` (add a small `__main__` that prints events). Commit `delib: facilitator`.

---

### Task 8: Event bus, API server, SSE, replays

**Files:** Create `backend/deadlang/api/events.py`, `backend/deadlang/api/server.py` · Test `backend/tests/test_api.py`

**`events.py`:** `class EventBus` — `emit(case_id, type, payload) -> Event` (assigns per-case `seq` from 0, stores in memory, appends to `fixtures/replays/runs/<case_id>.jsonl`, wakes subscribers), `history(case_id) -> list[Event]`, `async subscribe(case_id) -> AsyncIterator[Event]` (yields history first, then live events, stops after `case.ended` or `budget.exceeded` followed by `case.ended`).

**`server.py`:** FastAPI app implementing every endpoint in file 01 §4.6, CORS for `http://localhost:3000`. On startup: build market client, discovery (`register_all()` if agntcy), transport, one `Facilitator`. `POST /api/cases` creates `C-0001`-style ids and starts `run_case` with `asyncio.create_task`. SSE via `sse-starlette` `EventSourceResponse` yielding `{"event": e.type, "data": e.model_dump_json()}`. `GET /api/listings` merges `data/triage.json` if present. `POST /api/demo/remove-listing` → `market.remove_listing` then `facilitator.notify_listing_removed` for active cases of that listing. `POST /api/demo/kill-specialist` → `discovery.mark_unhealthy(name)` and, if the transport has `disabled`, add it. `GET /api/images/{path:path}` serves from `DATA_DIR` (reject `..`).

- [ ] Step 1: Failing tests with FastAPI `TestClient` + fakes: create case → SSE yields events through `case.ended`; casefile 404 before end, 200 after; remove-listing emits `listing.removed`; image path traversal rejected; replays list/load.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: `uv run uvicorn deadlang.api.server:app --port 8000`, then `curl -N localhost:8000/api/cases/<id>/events` shows live events. Commit `delib: api + sse + replays`. Tell Person D the live API is up.

---

### Task 9: Baselines and the evaluation runner

**Files:** Create `backend/deadlang/eval/baselines.py`, `backend/deadlang/eval/run_eval.py` · Output `results/eval.json`

**Baselines (`baselines.py`):**
- `listing_only(listing) -> {"decision": "file"|"dismiss", "confidence", "reason"}` — one `MODEL_STRONG` call, system: "You review one marketplace listing for possible disguised elephant ivory. Decide whether to file it for human investigation or dismiss it." User: E0 text only.
- `single_agent_with_evidence(board) -> same + claims` — one `MODEL_STRONG` call, sees the full intake board, same claim format; run the Task 3 validator on its claims and count rejections.

**Runner (`run_eval.py`):** `uv run python -m deadlang.eval.run_eval --modes A,B,C --limit N` over `data/eval_set.txt` (Person A). Mode C = `Facilitator.run_case` with a no-op event bus writer. Intake is computed **once per listing and reused** for B and C (same evidence → fair comparison, lower cost). Reads `data/labels.csv` (only this file reads labels). Uses `case_id="eval-<mode>-<listing>"` so budgets are tracked. Resumable: writes per-listing results to `results/eval_rows.jsonl` and skips done rows.

**Metrics per mode → `results/eval.json`:**
- `n_pos`, `n_neg`
- `caught` = positives decided FILE; `caught_or_escalated` = FILE or CONTESTED (mode C only)
- `false_accusations` = negatives decided FILE; `false_accusation_rate`
- `escalated_rate` (CONTESTED share, mode C)
- `avg_input_tokens`, `avg_output_tokens` per case (from `llm.usage_snapshot(case_id)`)
- `claims_rejected_total` and per case (B and C)
- `stance_changes_after_new_evidence` (C: count of posts with `changed_because_evidence` citing an item added after that agent's previous post)
- `examples`: 3 short case ids per interesting bucket (C caught but B missed; B false accusation that C avoided)

- [ ] Step 1: Dry run `--limit 4` with all modes; check JSON shape.
- [ ] Step 2: Full run (budget first: estimate tokens from the dry run × set size; post the estimate in chat before running).
- [ ] Step 3: Post headline numbers in chat for Person D. Commit `delib: eval results`.

---

### Task 10: Record replays and tune the demo (with Persons A and D)

- [ ] Run D1–D4 live 3 times each in `TRANSPORT=agntcy` (or local if that was the decision). Pick the best run of each and copy its run log to `fixtures/replays/d1_network.jsonl`, `d2_tagua.jsonl`, `d3_removed.jsonl`, `d4_ambiguous.jsonl`.
- [ ] If a case doesn't tell its story, first ask Person A to adjust data; change prompt wording only if the agents are misreading the rules, and re-run the unit tests after any prompt change.
- [ ] Commit `delib: demo replays`.

## Self-check before you call it done

- `uv run pytest -m "not integration"` green.
- A full live case produces: intake evidence, ≥2 rounds, at least one specialist request answered mid-case, validated claims with citations, and a case file.
- `results/eval.json` exists and every number on Person D's results slide is copied from it.
