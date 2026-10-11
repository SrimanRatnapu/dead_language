# Person B (v2): Evaluations, Triage, Model Choice, Injection Defense

> Read `00-overview-and-contracts.md` first. Old plan: `../03-person-B-agent-network-and-ai-specialists.md` (your agent-network work is unchanged; v2 adds the items below).

## Goal
Prove the outputs are good. Build the cheap triage that makes scale affordable without dropping real cases. Decide Haiku vs Sonnet with evidence. Make the agents resistant to hostile listing text.

## Metrics vs evaluations (important)
You own **evaluations**: judging the *quality of model and agent outputs* offline on labeled data. Throughput, latency, cost per case and takedown counts are **metrics**, owned by Person C. Do not build those.

## You own
`backend/deadlang/eval/*`, `backend/deadlang/triage.py` (new), `backend/deadlang/agntcy/*`, `backend/deadlang/specialists/*`, prompt files, `results/*`. Existing eval code lives in `eval/run_eval.py`, `eval/baselines.py`, `eval/examiner_eval.py`: extend, don't rewrite. The old plan gave the runner to C; v2 moves it to you.

## Not yours
Queue, metrics backend, strike, UI, data connectors.

## Tasks

### B1. Haiku triage (P0 for the pipeline)
`backend/deadlang/triage.py`:
```python
async def screen(listing: Listing, seller: Seller | None) -> TriageResult
```
(`TriageResult` in file 00 §4.5. Check whether the existing `Triage` model and `scripts/compute_triage.py` already fit; reuse.)
- One Haiku call via `llm.call_json`, schema-constrained: `score` 0..1, one-sentence `reason`, `suspicious` bool.
- Inputs: listing text, price, ratio to median if known, and seller listing count. **Never** the label.
- Threshold `DL_TRIAGE_THRESHOLD` defaults **low**: false negatives are the costly error here, so we over-send to the agents rather than drop a real case. Clearing a listing at triage must be a high-confidence call.
- Provide a fake in `tests/fakes.py` (`FakeTriage`) in your first hour so C can build the worker against it.

### B2. Evaluation suite (P0/P1)
Everything writes to `results/eval.json` (existing file; add keys, don't break the existing shape the `/results` page reads). Coordinate new keys with D before you rely on them being displayed.

**Evaluation population:** run accuracy evaluations on **all ~499 stored listings** in `data/listings.jsonl` with their labels, not just the 12-listing demo set. Person A is forbidden from deleting or editing stored rows, so the full set is stable for you. Live-lane and new listings live in separate files and are never part of the labeled population. Print `n` for every number. Sonnet and Opus sweeps over 499 listings are expensive: run Haiku configs on the full set first, then Sonnet on the full set only after the harness is debugged, and use a stratified sample for the Opus reference.

| Eval | What it measures | Notes |
|---|---|---|
| **Config comparison** | Catch rate, false-accusation rate, escalation rate, tokens per case for: single agent listing-only, single agent with evidence, 3-agent review. Each on **Haiku-all, Sonnet-all, tiered** | Tiered = Haiku triage + Sonnet agents. This decides the model choice |
| **Opus reference** | One offline run of the best config on Opus | Write-up only. Cap the spend. Do not ship |
| **Triage recall** | Of all labeled true positives, how many does triage pass through to the agents at the chosen threshold | The key number for the funnel. Report a threshold sweep |
| **Examiner accuracy** | Existing `examiner_eval.py` on the labeled museum photos, now for Sonnet vs Haiku | "cannot_tell" counted separately from wrong |
| **Claim quality** | Claim rejection rate, citation correctness, and whether each agent's `take` is consistent with its own claims | Mostly rule-based using the existing validator. If you use an LLM judge, use Sonnet, report its agreement with a small hand-labeled sample of ~20 |
| **Stability** | Run each demo-set case 3 times, report how often the outcome is the same | Measures agent variance. Disagreement across runs is a finding, not a bug |
| **Injection red-team** | Attack success rate on >=15 listings with hostile text ("ignore instructions, dismiss", fake evidence ids, quoted fake numbers, role-play requests) | Success = the outcome or a claim was changed by the injected text |
| **Subgroup errors** | False-accusation and miss rates by language, ship-from country, and material | Report small n honestly. Never headline a subgroup number with n under 10 |
| **Live spot-check** | A hand-review sheet for live-lane flags: listing, the agents' outcome, and a blank reviewer verdict column | The live lane has no ground truth. Precision is a hand spot-check and is labeled as one |

Honest caveat to state in the results page text: positive cases are reconstructed from published research, so numbers are indicative, not field performance.

Cost control: set a per-run token budget and print the estimated cost before running Sonnet or Opus sweeps. Run Haiku configs first to debug the harness.

### B3. Prompt-injection defense (P0, safety)
- In every prompt that includes listing text (triage, translator, examiner, deliberating agents), wrap listing content in clearly delimited data blocks and state explicitly that anything inside is untrusted content, never instructions. Prompts are files in `deliberation/prompts/` and `specialists/prompts/`; edit those, not code.
- Outputs are already schema-constrained and claims are code-validated (numbers and quotes must exist in evidence). Verify with the red-team set that an injected instruction cannot flip an outcome without cited, valid evidence.
- The injection listing in A's demo set is your fixture. Add more.
- If a defense fails, record it in the results and fix it, do not hide it.

### B4. Model swap and scaling (P1)
- Set defaults: triage and translation on Haiku, examiner-thorough and all three deliberating agents on Sonnet. Keep config via `DL_MODEL_FAST` / `DL_MODEL_STRONG`. Add `DL_MODEL_TRIAGE`.
- Prompt caching: the shared rules and agent prompts are identical across cases. Verify the SDK call in `llm.py` marks them cacheable and measure the saving (report to C for metrics).
- Worker scaling story for the AGNTCY layer: each specialist and agent is a separate process (`serve --group`) and one process per agent is already supported. Show that running two replicas of a specialist works through the Directory (the registry picks among candidates). Add a compose/Procfile note documenting how to run replicas. We demo this; we do not build Kubernetes.
- Known: `llm.py` must not send `temperature` to the newest models (SDK rejects it). Do not reintroduce it.

### B5. Rename support (P0, small)
Person C does the agent rename in one commit. After it lands, re-check your prompts, fakes and eval code for old names. Until then do not hard-code names.

## Dependencies and fakes
- A's demo set (`data/demo_set.json`) defines the stability and injection cases. Until it lands, use the existing d1-d4 listings.
- C's worker calls your `screen()`. Ship `FakeTriage` first.
- An invalid Anthropic key broke runs earlier. Verify the key works before you start spending on sweeps.

## Done means
- `screen()` works with a real Haiku call and a fake, threshold configurable.
- `results/eval.json` contains config comparison (Haiku/Sonnet/tiered), triage recall sweep, examiner accuracy, stability, injection results, subgroup table, and the live spot-check sheet exists.
- A written recommendation of the model config with the numbers behind it (one paragraph for the Devpost).
- Red-team set exists and the attack success rate is reported, including failures.
