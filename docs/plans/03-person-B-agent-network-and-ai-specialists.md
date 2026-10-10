# Person B — Agent Network (AGNTCY) & AI Specialists Build Plan

> Read `00-dead-language-design-spec.md` and `01-shared-contracts-and-kickoff.md` first. This plan assumes both.
> Steps use `- [ ]` checkboxes. Each task ends with tests passing and a commit prefixed `net:`.

**Goal:** Make every agent a real AGNTCY agent (A2A over SLIM, registered in the AGNTCY Directory, found by capability), own the only path to the Anthropic API (with a hard spend cap), and build the AI specialists (two Material Examiners and the Translator) plus triage scores and the examiner accuracy test.
**Architecture:** Every agent is first a plain async Python handler (`Specialist.run` or `DeliberatingAgent.handle`). Your AGNTCY layer wraps those handlers as A2A servers over SLIM, publishes their AgentCards to the Directory, and gives the Facilitator a `AgentTransport` (call one agent / broadcast to the three deliberators) and a `Discovery` (pick a specialist by capability). Both have a local in-process fallback selected by env var, so the demo can never be blocked by infrastructure.
**Tech Stack:** Python 3.12, uv, agntcy-app-sdk 0.5.x (pins a2a-sdk 0.3.20, slim-bindings, agntcy-dir), Docker Compose (SLIM 1.0.0, dir-apiserver v1.0.0-rc.3, zot), anthropic SDK, Pillow, pytest.

## Global Constraints (in addition to file 01)

- Nothing else in the codebase may import `anthropic`. Only `deadlang/llm.py`.
- Every AGNTCY call has a timeout. A timeout or exception becomes an error string / `SpecialistReply(ok=False, error=...)`, never an unhandled crash in the Facilitator.
- `TRANSPORT=local` and `DISCOVERY=local` must always work, even if you never get SLIM running.
- SLIM identities are `default/default/<agent name>`. Deliberators: `deadlang-buyer`, `deadlang-defender`, `deadlang-caseload`. Specialists: names in file 01 §4.2.
- Reference code to copy patterns from (clone `github.com/agntcy/app-sdk` at the tag matching your installed version):
  - server over SLIM patterns: `tests/server/a2a_starlette_server.py` (build `A2AStarletteApplication`, `factory.create_transport("SLIM", endpoint=..., name=...)`, `app_session.add(server).with_transport(t).with_topic(name).with_session_id(...).build()`, `await app_session.start_all_sessions(keep_alive=True)`)
  - client point-to-point and broadcast: `tests/e2e/test_a2a_starlette.py` (`test_broadcast`) and `tests/e2e/conftest.py` (`make_agent_card`, `make_send_request`); README sections "Connect to an Agent" and "Broadcast to Many Agents"
  - Directory: `tests/e2e/test_directory.py` (`AgentDirectory(config=Config(server_address="127.0.0.1:8888"))`, `push_agent_record(card)`, `search_agent_records(query, limit)`, `oasf_to_agent_card`)
  - Note from reading the SDK source: `agent_card_to_oasf` stores the whole AgentCard inside the record but sets the OASF skill to a placeholder, so Directory **skill** search will not match our skills. Search by **name** and read capabilities from the embedded card's skill tags.

## Files you own

`infra/*`, `Procfile`, `backend/deadlang/config.py`, `backend/deadlang/llm.py`, `backend/deadlang/specialists/{base.py,material.py,language.py,registry.py}`, `backend/deadlang/agntcy/{cards.py,serve.py,transport.py,discovery.py}`, `scripts/compute_triage.py`, `backend/deadlang/eval/examiner_eval.py`, `docs/agntcy-notes.md`, tests `test_llm.py`, `test_material.py`, `test_language.py`, `test_discovery.py`, `test_transport_local.py`, `test_agntcy_e2e.py` (integration).

---

### Task 1: Config and the Specialist protocol (do this in the first 30 minutes; others depend on it)

**Files:** Create `backend/deadlang/config.py`, `backend/deadlang/specialists/base.py`

**Produces:**
- `config.py`: loads `.env` (python-dotenv, from repo root) and exposes constants: `DATA_DIR: Path`, `MODEL_STRONG`, `MODEL_FAST`, the four token caps, `USAGE_FILE: Path`, `MARKETPLACE_MODE`, `MARKETPLACE_MCP_URL`, `TRANSPORT`, `DISCOVERY`, `SLIM_ENDPOINT`, `SLIM_SHARED_SECRET`, `DIRECTORY_ADDRESS`, `REPO_ROOT: Path`. Defaults exactly as `.env.example`.
- `base.py`: the `Specialist` Protocol exactly as file 01 §4.2 (`name`, `capability`, `tier`, `async run(call) -> SpecialistReply`).

- [ ] Step 1: Write both files. Step 2: `uv run python -c "import deadlang.config, deadlang.specialists.base"` → no error.
- [ ] Step 3: Commit `net: config + specialist protocol` and tell Person A.

---

### Task 2: LLM wrapper with hard spend cap

**Files:** Create `backend/deadlang/llm.py` · Test `backend/tests/test_llm.py`

**Produces (exact signatures from file 01 §4.5):** `BudgetExceeded`, `call_json(...)`, `call_vision_json(...)`, `usage_snapshot(case_id=None)`, plus `set_client_for_tests(fake)`.

**Behavior:**
1. One module-level `anthropic.AsyncAnthropic()` created lazily (tests replace it).
2. **Structured output by forced tool use:** send `tools=[{"name": schema_name, "description": "Return your answer by calling this tool.", "input_schema": schema}]` and `tool_choice={"type": "tool", "name": schema_name}`; return the `input` of the first `tool_use` block. If none, raise `ValueError("no tool output")` (no retry).
3. **Vision:** each image becomes a content block `{"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":...}}` placed before the text block. Downscale so the longest side ≤ 1,568 px before encoding.
4. **Budget check before every call:** estimate input tokens as `len(system + user) / 3.5 + 1,600 per image`; if `global_used_in + estimate > DL_MAX_INPUT_TOKENS` or `global_used_out + max_tokens > DL_MAX_OUTPUT_TOKENS`, raise `BudgetExceeded`. Same check against the per-case caps when `case_id` is given.
5. **Record actual usage after every call** from `response.usage.input_tokens/output_tokens` into `USAGE_FILE` (JSON `{"global": {"input_tokens", "output_tokens", "calls"}, "cases": {case_id: {...}}}`), guarded by an `asyncio.Lock`, written atomically (write temp file, rename).
6. **Retries:** at most 1 retry, only for HTTP 429, 500, 529 or connection errors, after a 3 s sleep. Any other error propagates.
7. Log one line per call: model, schema_name, case_id, tokens in/out, ms.

- [ ] Step 1: Failing tests with a fake client: returns tool input dict; budget raises before calling the API when global cap is 100 tokens; per-case cap independent of global; usage file accumulates across two calls; retry happens once on a fake 529 then succeeds; a fake 400 is not retried.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Commit `net: llm wrapper with spend cap`. Post in chat: "llm.py ready — no more stubs."

---

### Task 3: Infrastructure + AGNTCY spike (time box: 2 hours — decision at the 4:00 checkpoint)

**Files:** Create `infra/docker-compose.yaml` (from app-sdk, trimmed per file 01 K5), `docs/agntcy-notes.md`, throwaway `backend/spike/` (delete after)

Goal: prove four things with tiny echo agents before building real wrappers.

- [ ] Step 1: `docker compose -f infra/docker-compose.yaml up -d`; check `docker ps` shows slim, dir-api-server, zot healthy; `curl -s http://localhost:8889/healthz/ready`.
- [ ] Step 2: **Point-to-point:** run one echo A2A server over SLIM patterns (pattern from `tests/server/a2a_starlette_server.py`) named `default/default/spike-echo-1`; from a client, `send_message` and print the echo.
- [ ] Step 3: **Broadcast:** run 3 echo servers; `client.broadcast_message(request, recipients=[...3 names...])` returns 3 responses. Record how to pull the text out of each `SendMessageResponse` (e.g. `resp.root.result.parts[0].root.text`) in the notes.
- [ ] Step 4: **Directory:** push 2 AgentCards named `deadlang-spike-a`, `deadlang-spike-b`; `search_agent_records("deadlang-spike-a")` finds it. Then test whether a wildcard name query works: `search_agent_records("deadlang-*")`. Write the result in the notes. If wildcards don't work, discovery will search each **known candidate name** for a capability (see Task 7) — still real Directory lookups.
- [ ] Step 5: **Kill test:** stop one echo server; confirm the client times out cleanly with your timeout and what exception type appears.
- [ ] Step 6: Write `docs/agntcy-notes.md`: exact versions, working snippets, response-parsing code, wildcard result, timeout behavior, gotchas (e.g. `SLIM_SHARED_SECRET` must be ≥32 chars and the same everywhere).
- [ ] **Go/no-go at 4:00:** if point-to-point works → go. If broadcast fails but point-to-point works → `broadcast_turns` sends three point-to-point calls with `asyncio.gather` (still AGNTCY). If SLIM fails entirely → `TRANSPORT=local` for the demo, keep Directory if it works, and say so honestly in the Devpost. Post the decision in chat.
- [ ] Step 7: Commit infra + notes `net: agntcy spike`.

---

### Task 4: AgentCards

**Files:** Create `backend/deadlang/agntcy/cards.py`

**Produces:** `def card_for(name: str) -> AgentCard` and `ALL_AGENT_NAMES: list[str]`, `SPECIALIST_NAMES: list[str]`, `DELIBERATOR_NAMES: dict[AgentName, str]` (`{"buyer": "deadlang-buyer", ...}`).

Each card: `name=<agent name>`, `description` (one plain sentence of what it does), `version="1.0.0"`, `capabilities=AgentCapabilities()`, `defaultInputModes/OutputModes=["text"]`, `preferredTransport=InterfaceTransport.SLIM_PATTERNS`, `url` and `additional_interfaces` with `slim://localhost:46357/default/default/<name>` (follow `make_agent_card` in the SDK tests), and one `AgentSkill` with:
- `id = <capability>` (or `deliberate` for the three deliberators)
- `tags = ["capability:<capability>", "tier:<preferred|fallback>", "produced_by:<code|model>", "model:<model or none>"]`
- `description` stating the input it needs and what it returns.

- [ ] Step 1: Write it. Step 2: a test asserts every name in file 01 §4.2 has a card and the tags parse. Step 3: commit `net: agent cards`.

---

### Task 5: Local transport and local discovery (the fallback — build before the AGNTCY versions)

**Files:** Create `backend/deadlang/agntcy/transport.py` (LocalTransport part), `backend/deadlang/agntcy/discovery.py` (LocalDiscovery part), `backend/deadlang/specialists/registry.py` · Test `backend/tests/test_transport_local.py`, `backend/tests/test_discovery.py`

**Produces:**
- `registry.build_specialists(market) -> list[Specialist]` — imports Person A's `PriceChecker`, `SellerInventory`, `LinkedSellers`, `LegalTable` and your `ThoroughExaminer`, `QuickExaminer`, `Translator`.
- `LocalTransport(specialists: dict[str, Specialist], agents: dict[AgentName, DeliberatingAgent])` implementing `AgentTransport` (file 01 §4.3): `call_specialist` awaits `run` with `asyncio.wait_for(timeout)`; on timeout returns `SpecialistReply(ok=False, error="timeout")`; on exception `error=str(exc)`. `broadcast_turns` gathers the three `handle` calls in parallel; per-agent failures become error strings. Has `disabled: set[str]` so `kill-specialist` can simulate a dead process in local mode (a disabled specialist always times out).
- `LocalDiscovery(cards: list[AgentCard])` implementing `Discovery`: `select(capability, exclude)` → candidates = cards whose skill tags include `capability:<capability>`, minus `exclude` and minus unhealthy (unhealthy expires after 60 s). Order: `tier:preferred` before `tier:fallback`, then lowest average latency recorded via `record_latency(name, ms)`. Returns `Selection(specialist_name, why, candidates)`.
- **`why` sentence templates** (the UI shows these; keep them plain):
  - only one candidate: `"{name} is the only registered agent offering {capability}."`
  - preferred chosen: `"Chose {name}: it offers {capability} at the preferred quality tier and is responding."`
  - fallback chosen because preferred unhealthy: `"{preferred} did not respond, so chose {name}, which offers {capability} at a lower quality tier."`
- `get_transport()` / `get_discovery()` factories read env and return singletons.

- [ ] Step 1: Failing tests: select prefers thorough over quick; after `mark_unhealthy("deadlang-examiner-thorough")` select returns quick with the fallback sentence; `exclude` works; LocalTransport timeout returns `ok=False,error="timeout"`; broadcast returns 3 results with one error string when one fake agent raises.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Commit `net: local transport + discovery`. Tell Person C they can run the full Facilitator in local mode now.

---

### Task 6: AGNTCY servers (`serve.py`)

**Files:** Create `backend/deadlang/agntcy/serve.py`

**Produces:** CLI `python -m deadlang.agntcy.serve --group <specialists|examiner-thorough|examiner-quick|deliberators|all>`.

**Behavior:**
- Builds the marketplace client, the specialists (registry) and the three `DeliberatingAgent`s, then for each agent in the group creates one A2A server over SLIM patterns with its card (Task 4) and a generic `AgentExecutor`:
  - read the incoming text part, parse JSON into `SpecialistCall` (specialists) or `DeliberationTurn` (deliberators); for a broadcast payload, see Task 7 note;
  - call `run` / `handle`;
  - enqueue one text message containing the reply model's JSON (`SpecialistReply` / `StancePost`). On exception reply `SpecialistReply(ok=False, error=...)` or `{"error": "..."}`.
- Registers all agents in one `AppSession` per process (`max_sessions` = number of agents), `start_all_sessions(keep_alive=True)`.
- The thorough examiner runs in its **own** process group (`examiner-thorough`) so it can be killed live in the demo.
- On startup, if `DISCOVERY=agntcy`, push this process's cards to the Directory (Task 7 `register(names)`).

- [ ] Step 1: Start `--group specialists` with SLIM up; from a scratch client call `deadlang-price-checker` with a real `SpecialistCall` for a real listing → valid `SpecialistReply` JSON.
- [ ] Step 2: Same for `deadlang-buyer` with a minimal `DeliberationTurn` (only after Person C's `DeliberatingAgent` exists; until then use a stub agent that returns a fixed `StancePost`).
- [ ] Step 3: Commit `net: a2a servers`.

---

### Task 7: AGNTCY transport and Directory discovery

**Files:** Extend `backend/deadlang/agntcy/transport.py` (AgntcyTransport), `backend/deadlang/agntcy/discovery.py` (AgntcyDirectoryDiscovery) · Test `backend/tests/test_agntcy_e2e.py` (`@pytest.mark.integration`)

**AgntcyTransport:**
- One `AgntcyFactory`, one SLIM transport named `default/default/deadlang-facilitator`, one A2A client per target card (cache).
- `call_specialist(name, call, timeout)`: point-to-point `send_message`, parse reply text as `SpecialistReply`; timeout → `ok=False,error="timeout"`; record latency in discovery.
- `broadcast_turns(turns, timeout)`: one `broadcast_message` to the three deliberator identities. Payload: a JSON object `{"kind": "turns", "turns": {"buyer": <DeliberationTurn>, "defender": ..., "caseload": ...}}`; each deliberator's executor picks its own entry by its name. Map each response back to its agent by the `agent` field of the returned `StancePost`. Missing responses after timeout → error string for that agent.
- `call_agent(agent, turn, timeout)`: point-to-point (used for repair calls).
- If broadcast was a "no-go" in Task 3, implement `broadcast_turns` as `asyncio.gather` of `call_agent`.

**AgntcyDirectoryDiscovery:**
- `register_all()` / `register(names)`: `push_agent_record(card_for(name))` for each, store CIDs in memory; ignore "already exists" errors.
- `select(capability, exclude)`: get candidate names for the capability from `cards.py` (static list of who *should* offer it); for each name, `search_agent_records(name)` in the Directory (or one wildcard search if it worked in the spike); convert results with `oasf_to_agent_card`; keep those whose skill tags include `capability:<capability>`; then the same health/tier/latency ordering and `why` templates as `LocalDiscovery` (share that code), appending `" Found via the AGNTCY Directory."` to `why`.
- If the Directory call itself fails, fall back to `LocalDiscovery` for that call and log it.

- [ ] Step 1: Integration test with compose + `serve --group all` running: select("material_exam") → thorough; kill the `examiner-thorough` process; `call_specialist` times out; `mark_unhealthy`; select → quick with fallback sentence; broadcast to three stub deliberators returns three StancePosts.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Commit `net: agntcy transport + directory discovery`.

---

### Task 8: Material Examiners (thorough and quick)

**Files:** Create `backend/deadlang/specialists/material.py`, `backend/deadlang/specialists/prompts/material_exam.md` · Test `backend/tests/test_material.py`

**Produces:** `ThoroughExaminer` (`name="deadlang-examiner-thorough"`, tier preferred, model `MODEL_STRONG`) and `QuickExaminer` (`name="deadlang-examiner-quick"`, tier fallback, model `MODEL_FAST`), both `capability="material_exam"`.

**Input:** `SpecialistCall`; `params.image_index` (optional int) limits the exam to one photo; otherwise all photos of the listing (max 3). Images come from `market.image_path(rel)`. If the listing has no images → `ok=False, error="no_images"`.

**Prompt (`material_exam.md`, system prompt):**

> You examine photos of carved objects and report what material they appear to be made of. You are a neutral fact-finder: you do not decide whether anything is illegal, and you do not read or consider the seller's description or price — you only see photos.
> For each photo, choose exactly one material from: elephant_ivory, bone, resin_or_plastic, tagua_nut, wood, other, cannot_tell.
> Base your answer only on features you can actually see, and name them. Useful visible features:
> - elephant_ivory: cross-hatched or checkerboard pattern of curved lines (Schreger lines) on a cut cross-section or base; fine, even grain; warm creamy, slightly translucent surface.
> - bone: small dark pits, dots or short streaks (from blood-vessel channels); more opaque, chalky or dry-looking surface; no cross-hatching.
> - resin_or_plastic: perfectly uniform color and texture; mold seams; bubbles; a "too perfect" glossy finish; repeated identical details.
> - tagua_nut: small object (a tagua nut is about egg-sized); very fine, faint concentric grain; may show a patch of brown seed skin.
> - wood: visible wood grain lines or rings; brown tones.
> If the photo is too small, blurry, distant, or shows no informative surface, answer cannot_tell. cannot_tell is a good answer when you are unsure. Never guess from the object's style or subject.
> Confidence is your probability (0–1) that your material answer is correct.

User message: `"Photos are numbered in the order given, starting at 0. Return one entry per photo."` (+ the images).

**Output schema (`schema_name="report_material"`):** `{"photos": [{"index": int, "material": enum, "confidence": number 0–1, "visible_features": [string, max 3], "best_region": string}]}`.

**Thorough mode:** run the call **twice** independently (same prompt). For each photo: if both runs give the same material (not cannot_tell), report it with confidence = min of the two; otherwise report `cannot_tell` with confidence 0 and `visible_features` from both runs. **Quick mode:** single run; cap every confidence at 0.6.

**EvidenceDraft (one per call):** `produced_by="model"`, `confidence` = highest per-photo confidence among non-cannot_tell photos (or 0), `data = {"listing_id", "mode": "thorough"|"quick", "model", "photos": [...per photo...], "overall": <material of the highest-confidence photo or "cannot_tell">}`, summary templates:
- any decisive photo: `"Photo {i} shows {feature 1} consistent with {material} (confidence {c:.1f}); {k} other photos: cannot tell."` (adjust wording when k=0)
- none decisive: `"The examiner could not tell the material from the {n} photos (thorough mode: the two runs disagreed or both were unsure)."` / quick-mode variant.
Make sure every number printed (photo index, confidence with 1 decimal, counts) is stored in data with the same rounding.

- [ ] Step 1: Failing tests with a fake `llm.call_vision_json`: agreement → material reported with min confidence; disagreement → cannot_tell; quick caps at 0.6; image_index limits to one photo; no images → error.
- [ ] Step 2–4: implement → PASS.
- [ ] Step 5: Manual smoke test on 3 museum photos (one ivory, one bone, one wood) with the real API; paste results into `docs/agntcy-notes.md`.
- [ ] Step 6: Commit `net: material examiners`.

---

### Task 9: Translator

**Files:** Create `backend/deadlang/specialists/language.py` · Test `backend/tests/test_language.py`

**Produces:** `Translator` (`name="deadlang-translator"`, `capability="translation"`, model `MODEL_FAST`). If `listing.language == "en"` → `ok=False, error="already_english"`.

System prompt: "Translate the marketplace listing to plain English. Then list up to 5 notable phrases from the original whose literal meaning matters for understanding what is being sold (materials, age, origin, quantity, payment or contact instructions). Do not judge legality." Output schema `report_translation`: `{"title_en": str, "description_en": str, "notable_phrases": [{"original": str, "literal_en": str}]}`.

EvidenceDraft: `produced_by="model"`, `confidence=null`, `data` = the output + `source_language`, summary: `"Translated from {language}: \"{title_en}\"."`.

- [ ] Steps 1–5: tests with a fake llm (English listing refused; Vietnamese listing produces draft with title in summary and in data), implement, pass, commit `net: translator`.

---

### Task 10: Process runner and demo kill switch

**Files:** Create `Procfile` (file 01 §5), `scripts/dev_up.sh`, `scripts/dev_down.sh`

- `dev_up.sh`: `docker compose up -d`, wait for SLIM port and Directory health, then `uvx honcho start`.
- Kill switch: the API's `POST /api/demo/kill-specialist` (Person C) calls `discovery.mark_unhealthy(name)` and, in local mode, `LocalTransport.disabled.add(name)`. For the real thing in agntcy mode, Person D's demo script stops the `examiner` process from the terminal (`honcho` lets you stop one process; or run it in a separate terminal and Ctrl-C it). Document both in `docs/agntcy-notes.md`.

- [ ] Step 1: Full stack up with `TRANSPORT=agntcy DISCOVERY=agntcy`; run D1 via the API with Person C; watch events.
- [ ] Step 2: Kill the thorough examiner mid-case; confirm `specialist.failed` then `specialist.selected` (quick) appear.
- [ ] Step 3: Commit `net: process runner`.

---

### Task 11: Triage scores for the browse page

**Files:** Create `scripts/compute_triage.py` · Output `data/triage.json`

For every active listing: a fast-model text read (title, description, price, stated material, item type — **no photos**), schema `report_triage`: `{"text_suspicion": 0–1, "reason": one sentence}` with system prompt: "You screen marketplace listings for possible disguised elephant ivory. Read it as an experienced collector would: does anything about the price, wording, or details only make sense if the item were ivory? Most listings are innocent; give low scores unless something specific stands out." Then `score = round(0.5 * text_suspicion + 0.5 * min(price_ratio / 10, 1), 2)` where `price_ratio` comes from Person A's `PriceChecker` (0 if no comparables). Output `{listing_id: {"score", "reason", "price_ratio"}}`. Use `case_id="triage"` so it has its own budget line; abort cleanly on `BudgetExceeded`.

- [ ] Step 1: Run on 10 listings, check output. Step 2: run on all. Step 3: commit data + script `net: triage`.

---

### Task 12: Examiner accuracy test (evidence for the results slide)

**Files:** Create `backend/deadlang/eval/examiner_eval.py` · Output `results/examiner_eval.json`

Run both examiners on every image in `data/museum/museum_labels.csv` (one photo per call via `image_index=0` on a temporary fake listing, or call the examiner's internal per-image method directly). Report per mode: `n`, `accuracy_on_decisive` (correct / non-cannot_tell answers), `cannot_tell_rate`, `ivory_precision` (of photos called elephant_ivory, share truly ivory), `ivory_recall`, confusion matrix. Use `case_id="examiner_eval"`.

- [ ] Step 1: Run quick mode first (cheap), then thorough. Step 2: write JSON. Step 3: post the headline numbers in chat for Person D. Step 4: commit `net: examiner eval`.

## Self-check before you call it done

- `uv run pytest -m "not integration"` green; integration tests green with compose up.
- `TRANSPORT=local DISCOVERY=local` full case works; `TRANSPORT=agntcy DISCOVERY=agntcy` full case works (or the Task 3 decision is documented).
- `.usage.json` shows sane totals; nothing bypasses `llm.py` (`grep -r "anthropic" backend/deadlang | grep -v llm.py` returns nothing).
