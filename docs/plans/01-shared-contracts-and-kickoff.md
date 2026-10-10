# Dead Language — Shared Contracts & Kickoff Plan

> Everyone reads this after `00-dead-language-design-spec.md`.
> This file freezes the interfaces between the four people. If you need to change anything in here, post in the team chat and get a yes from whoever consumes it before changing it.
> Steps use `- [ ]` checkboxes.

**Goal:** Let four people (and their coding agents) build in parallel for ~18 hours without blocking each other.
**Architecture:** Python backend (marketplace MCP server, specialists and deliberating agents as AGNTCY A2A agents over SLIM, a Facilitator inside a FastAPI server that streams events) + Next.js frontend that renders the event stream.
**Tech Stack:** Python 3.12, uv, FastAPI, agntcy-app-sdk 0.5.x, a2a-sdk 0.3.20, MCP Python SDK (FastMCP), anthropic, pydantic v2, imagehash, pytest; Docker Compose (SLIM, Directory, zot); Next.js + TypeScript + Tailwind + Recharts.

## Global Constraints

- Python **3.12** exactly for the backend (`requires-python = ">=3.12,<3.13"`).
- Every model call goes through `deadlang/llm.py` (`call_json` / `call_vision_json`). No direct `anthropic` client usage anywhere else.
- Spend caps (env, defaults): `DL_MAX_INPUT_TOKENS=6000000`, `DL_MAX_OUTPUT_TOKENS=600000` global; `DL_CASE_MAX_INPUT_TOKENS=300000`, `DL_CASE_MAX_OUTPUT_TOKENS=30000` per case. Max 1 retry on transient API errors. Never loop on failures.
- Models come from env: `DL_MODEL_STRONG=claude-sonnet-5-5`, `DL_MODEL_FAST=claude-haiku-4-5-20251001`.
- Ground truth (`data/labels.csv`) is **never** read by any agent, specialist, prompt, or the Facilitator. Only `deadlang/eval/*` and demo-curation scripts read it.
- Deliberating agents state facts only inside `claims`, each with ≥1 evidence ID (see spec §5).
- Copy rule: never use court, courtroom, trial, verdict, jury, judge (as role), prosecutor, defense lawyer, guilty — in code identifiers, prompts, UI, or slides.
- Agent names are exactly `buyer`, `defender`, `caseload` (lowercase in data, capitalized in UI).
- Outcomes are exactly `FILE`, `DISMISS`, `CONTESTED`, `WATCHLIST`.
- Max rounds `4`; max specialist calls `3` per round and `6` per case; max `2` requests per post.
- All times in data are ISO 8601 strings. All prices in USD floats.
- Commit small and often to `main` with prefixes `data:`, `net:`, `delib:`, `ui:`, `docs:`. Pull before you push. Do not reformat files you don't own.

---

## 1. Kickoff (all four people, first 45 minutes, together)

- [ ] **K1. Create the repo** (Person C drives the keyboard): GitHub repo `dead-language`, add all six plan files under `docs/plans/` and the spec under `docs/specs/`.
- [ ] **K2. Create the skeleton** exactly as in §2 (empty files with a one-line docstring are fine). Person C creates `backend/deadlang/schemas.py` with the full contents of §3 and commits it. Everyone pulls.
- [ ] **K3. Backend env:** `cd backend && uv init --python 3.12 && uv add agntcy-app-sdk "mcp[cli]" anthropic fastapi "uvicorn[standard]" sse-starlette pydantic imagehash pillow httpx python-dotenv && uv add --dev pytest pytest-asyncio`. Commit `pyproject.toml` and `uv.lock`.
- [ ] **K4. Frontend env** (Person D): `npx create-next-app@latest frontend --ts --tailwind --app --eslint --src-dir --no-import-alias`, then `cd frontend && npm i recharts`.
- [ ] **K5. Infra** (Person B): copy `services/docker/docker-compose.yaml` and its `configs/` folder from `github.com/agntcy/app-sdk` into `infra/`, delete the `nats`, `clickhouse-server`, `otel-collector`, `grafana` services, keep `slim`, `dir-api-server`, `zot`. `docker compose -f infra/docker-compose.yaml up -d`.
- [ ] **K6. `.env`** at repo root from `.env.example` (§5). Each person puts their own `ANTHROPIC_API_KEY` — **use one shared key only** so the spend cap is meaningful.
- [ ] **K7. Agree on the demo cases** (5 minutes): D1 network case, D2 tagua case, D3 removed-listing case. Person A owns their data, Person D owns their story.
- [ ] **K8. Split.** Each person opens their plan and starts at their Task 1.

## 2. Repository layout and ownership

```
dead-language/
  .env.example                         C
  Procfile                             B   (process list for `honcho start`)
  docs/specs/00-dead-language-design-spec.md
  docs/plans/01..05-*.md
  infra/docker-compose.yaml            B
  infra/configs/...                    B
  data/                                A   (committed; images may be large — keep each <300 KB)
    listings.jsonl                     A
    sellers.jsonl                      A
    labels.csv                         A   (ground truth; eval only)
    images/<listing_id>_<n>.jpg        A
    museum/<met_object_id>.jpg         A
    museum/museum_labels.csv           A
    reference/legal.json               A
    triage.json                        B   (precomputed suspicion scores for the browse page)
    raw/                               A   (raw eBay/Met pulls; gitignored)
  scripts/
    pull_ebay.py                       A
    pull_met.py                        A
    ingest_manual_csv.py               A
    build_dataset.py                   A
    compute_triage.py                  B
  backend/
    pyproject.toml, uv.lock            C
    deadlang/
      schemas.py                       C (frozen contract, §3)
      config.py                        B   (env loading, paths, model names, caps)
      llm.py                           B   (only path to the Anthropic API; spend cap)
      textparse.py                     A   (stated_material, item_type)
      marketplace/
        store.py                       A   (MarketplaceStore)
        server.py                      A   (FastMCP marketplace server)
        client.py                      A   (MarketplaceClient: MCP client + local fallback)
      specialists/
        base.py                        B   (Specialist protocol)
        price.py                       A
        network.py                     A   (seller_inventory + linked_sellers)
        legal.py                       A
        material.py                    B   (thorough + quick examiners)
        language.py                    B
        registry.py                    B   (builds all specialist instances)
      agntcy/
        cards.py                       B   (AgentCards for every agent)
        serve.py                       B   (run agents as A2A servers over SLIM)
        transport.py                   B   (AgentTransport: agntcy + local implementations)
        discovery.py                   B   (Directory push/search + local registry fallback)
      deliberation/
        prompts/buyer.md               C
        prompts/defender.md            C
        prompts/caseload.md            C
        prompts/shared_rules.md        C
        agents.py                      C   (DeliberatingAgent handler)
        validator.py                   C   (claim checks)
        rules.py                       C   (stopping + outcome functions)
        casefile.py                    C
        facilitator.py                 C   (runs a case end to end)
      evidence/board.py                C   (EvidenceBoard)
      api/
        server.py                      C   (FastAPI app, REST + SSE)
        events.py                      C   (EventBus + replay log writer)
      eval/
        baselines.py                   C
        run_eval.py                    C
        examiner_eval.py               B
    tests/                             each person tests their own modules
  fixtures/
    sample_case_events.jsonl           C (first version in kickoff, §6) → D builds UI against it
    replays/<case>.jsonl               C (recorded real runs)
  results/
    eval.json                          C
    examiner_eval.json                 B
  frontend/                            D
  pitch/                               D   (deck, script, Devpost text, diagram)
```

## 3. Data contract: `backend/deadlang/schemas.py` (frozen)

Create this file exactly. It is the contract between all people.

```python
"""Shared data contract for Dead Language. Change only with team agreement."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------------- Marketplace data ----------------
StatedMaterial = Literal["bone", "resin", "tagua", "wood", "ivory_color", "ivory_mentioned", "unknown"]
ItemType = Literal["netsuke", "figurine", "jewelry", "other"]
ListingStatus = Literal["active", "removed", "hidden"]

class Listing(BaseModel):
    id: str                       # "L0001"
    marketplace: str              # "ebay" | "reconstructed" | "manual"
    seller_id: str                # "S0001"
    title: str
    description: str
    price_usd: float
    category: str                 # free text, e.g. "Antiques > Asian Antiques > Netsuke"
    stated_material: StatedMaterial   # parsed by code (textparse.py), never by a model
    item_type: ItemType               # parsed by code
    size_cm: Optional[float] = None
    weight_g: Optional[float] = None
    ship_from: str                # "US-CA", "US-NY", "HK", "VN", ...
    language: str = "en"
    image_paths: list[str] = Field(default_factory=list)  # relative to data/, "images/L0001_0.jpg"
    posted_at: str
    source_url: Optional[str] = None
    is_reconstructed: bool = False
    reconstruction_source: Optional[str] = None
    status: ListingStatus = "active"
    relist_of: Optional[str] = None   # hidden relist listing points at the original

class Seller(BaseModel):
    id: str
    name: str
    location: str
    joined: str
    feedback_score: Optional[int] = None

class Label(BaseModel):           # ground truth: eval only
    listing_id: str
    truth: Literal["ivory", "legal_bone", "legal_resin", "tagua", "other_legal"]
    should_flag: bool
    notes: str = ""

# ---------------- Evidence ----------------
Capability = Literal["listing_snapshot", "price_check", "seller_inventory", "linked_sellers",
                     "legal_lookup", "material_exam", "translation", "system_notice"]
AgentName = Literal["buyer", "defender", "caseload"]
Requester = Literal["intake", "buyer", "defender", "caseload", "system"]

class EvidenceDraft(BaseModel):   # what a specialist returns; the board assigns the id
    capability: Capability
    summary: str                  # ONE plain-English sentence; every number in it also appears in `data`
    data: dict[str, Any]
    produced_by: Literal["code", "model"]
    confidence: Optional[float] = None    # model-produced only
    specialist_name: str          # AgentCard name of the producer

class Evidence(EvidenceDraft):
    id: str                       # "E0", "E1", ...
    case_id: str
    requested_by: Requester
    created_at: str = Field(default_factory=now_iso)

# ---------------- Specialist messages ----------------
class SpecialistRequest(BaseModel):   # inside a StancePost
    capability: Capability
    question: str
    reason: str
    params: dict[str, Any] = Field(default_factory=dict)   # e.g. {"image_index": 2}, {"seller_id": "S0007"}

class SpecialistCall(BaseModel):      # body sent to a specialist agent
    case_id: str
    listing_id: str
    capability: Capability
    question: str = ""
    params: dict[str, Any] = Field(default_factory=dict)

class SpecialistReply(BaseModel):
    ok: bool
    drafts: list[EvidenceDraft] = Field(default_factory=list)
    error: Optional[str] = None       # "listing_removed" | "no_images" | "timeout" | "budget" | free text

# ---------------- Deliberation ----------------
Stance = Literal["file", "dismiss", "need_more"]

class Claim(BaseModel):
    text: str
    evidence_ids: list[str]

class Rebuttal(BaseModel):
    target_agent: AgentName
    target_claim: str
    response: str
    evidence_ids: list[str] = Field(default_factory=list)

class Challenge(BaseModel):          # one question from one agent to a named peer
    target_agent: AgentName
    question: str

class PeerQuestion(BaseModel):       # a Challenge as delivered to its target
    asker: AgentName
    question: str

class StancePost(BaseModel):
    agent: AgentName
    round: int
    stance: Stance
    confidence: float = Field(ge=0.0, le=1.0)
    claims: list[Claim]
    rebuttal: Optional[Rebuttal] = None           # required from round 2
    requests: list[SpecialistRequest] = Field(default_factory=list)   # max 2
    changed_because: Optional[str] = None         # required if stance changed vs own previous
    changed_because_evidence: list[str] = Field(default_factory=list)
    challenge: Optional[Challenge] = None         # max 1; target must answer it (with cited claims) in its next post
    ready_to_close: bool = False                  # True = "I have nothing more to add"

class DeliberationTurn(BaseModel):    # body sent to a deliberating agent
    case_id: str
    round: int
    max_rounds: int
    evidence: list[Evidence]
    transcript: list[StancePost]       # validated posts from earlier rounds
    your_previous: Optional[StancePost] = None
    repair_feedback: Optional[list[str]] = None   # only on a repair call
    questions_for_you: list[PeerQuestion] = Field(default_factory=list)   # challenges from peers' last posts

Outcome = Literal["FILE", "DISMISS", "CONTESTED", "WATCHLIST"]

class CaseFile(BaseModel):
    case_id: str
    listing_id: str
    seller_id: str
    outcome: Outcome
    rounds_used: int
    stop_reason: Literal["unanimous", "ready_to_close", "no_movement", "max_rounds", "budget"]
    final_positions: list[StancePost]
    evidence: list[Evidence]
    legal_basis: list[str]
    linked_seller_ids: list[str]
    tip_draft: Optional[str] = None       # FILE and CONTESTED only; never auto-sent
    status: Literal["awaiting_human_review", "closed"] = "awaiting_human_review"
    created_at: str = Field(default_factory=now_iso)

# ---------------- UI events (SSE) ----------------
EventType = Literal["case.started", "evidence.added", "specialist.selected", "specialist.failed",
                    "round.started", "stance.posted", "claim.rejected", "listing.removed",
                    "case.ended", "budget.exceeded"]

class Event(BaseModel):
    seq: int
    case_id: str
    type: EventType
    at: str = Field(default_factory=now_iso)
    payload: dict[str, Any]
```

## 4. Interfaces between people (exact names)

### 4.1 Marketplace (A → B, C)

`deadlang/marketplace/client.py`:

```python
class MarketplaceClient(Protocol):
    async def get_listing(self, listing_id: str) -> Listing        # raises ListingRemoved
    async def get_listing_snapshot(self, listing_id: str) -> Listing   # any status; used only by intake
    async def get_seller(self, seller_id: str) -> Seller
    async def get_seller_inventory(self, seller_id: str) -> list[Listing]   # active + removed
    async def search(self, query: str, limit: int = 50) -> list[Listing]
    async def all_active(self) -> list[Listing]
    async def remove_listing(self, listing_id: str) -> str | None  # returns revealed relist id
    async def reset_demo(self) -> None
    def image_path(self, rel_path: str) -> Path                    # absolute path on disk

def get_marketplace_client() -> MarketplaceClient   # MCP client if MARKETPLACE_MODE=mcp, else LocalMarketplaceClient
class ListingRemoved(Exception): listing_id: str
```

MCP server tools (FastMCP, streamable HTTP at `http://localhost:8100/mcp`): `get_listing`, `get_listing_snapshot`, `get_seller`, `get_seller_inventory`, `search_listings`, `list_active`, `admin_remove_listing`, `admin_reset_demo`. Each returns JSON-serialized models; a removed listing returns `{"error": "listing_removed", "listing_id": ...}`.

### 4.2 Specialists (A and B → B, C)

`deadlang/specialists/base.py` (Person B writes it in their Task 1; Person A codes against it immediately):

```python
class Specialist(Protocol):
    name: str                 # AgentCard name, e.g. "deadlang-price-checker"
    capability: Capability
    tier: Literal["preferred", "fallback"]
    async def run(self, call: SpecialistCall) -> SpecialistReply
```

Specialist names (also the AgentCard names and SLIM identities `default/default/<name>`):

| name | capability | owner | tier |
|---|---|---|---|
| `deadlang-price-checker` | price_check | A | preferred |
| `deadlang-seller-inventory` | seller_inventory | A | preferred |
| `deadlang-linked-sellers` | linked_sellers | A | preferred |
| `deadlang-legal-table` | legal_lookup | A | preferred |
| `deadlang-examiner-thorough` | material_exam | B | preferred |
| `deadlang-examiner-quick` | material_exam | B | fallback |
| `deadlang-translator` | translation | B | preferred |

`deadlang/specialists/registry.py` → `def build_specialists(market: MarketplaceClient) -> list[Specialist]`.

### 4.3 Agent transport and discovery (B → C)

`deadlang/agntcy/transport.py`:

```python
class AgentTransport(Protocol):
    async def call_specialist(self, specialist_name: str, call: SpecialistCall, timeout: float = 45.0) -> SpecialistReply
    async def broadcast_turns(self, turns: dict[AgentName, DeliberationTurn], timeout: float = 90.0) -> dict[AgentName, StancePost | str]
    # value is a StancePost, or an error string if that agent failed/timed out
    async def call_agent(self, agent: AgentName, turn: DeliberationTurn, timeout: float = 90.0) -> StancePost | str   # used for repair calls

def get_transport() -> AgentTransport   # AgntcyTransport if TRANSPORT=agntcy, else LocalTransport
```

`deadlang/agntcy/discovery.py`:

```python
@dataclass
class Selection:
    specialist_name: str
    why: str                       # plain sentence shown in the UI
    candidates: list[str]

class Discovery(Protocol):
    async def register_all(self) -> None
    async def select(self, capability: Capability, exclude: set[str] = frozenset()) -> Selection | None
    async def mark_unhealthy(self, specialist_name: str) -> None
    def record_latency(self, specialist_name: str, ms: float) -> None   # transport calls this after every specialist call

def get_discovery() -> Discovery   # AgntcyDirectoryDiscovery if DISCOVERY=agntcy, else LocalDiscovery
```

Note: `broadcast_turns` sends each agent its own `DeliberationTurn` (they differ only in `your_previous` and `questions_for_you`). From round 2 the dict contains **only the triggered agents** (see spec §6), so it may have 0–3 keys; untriggered agents are simply absent and the Facilitator carries their previous post forward. With AGNTCY broadcast, Person B may send one shared payload containing all turns keyed by agent name; each agent picks its own. That is Person B's internal choice.

### 4.4 Deliberating agent handler (C → B)

`deadlang/deliberation/agents.py`:

```python
class DeliberatingAgent:
    def __init__(self, name: AgentName): ...
    async def handle(self, turn: DeliberationTurn) -> StancePost   # one model call via llm.call_json
```

Person B wraps `DeliberatingAgent.handle` and every `Specialist.run` as A2A servers. The A2A message body is the model's JSON (`model_dump_json()`), sent as a single text part; the reply is a single text part with the reply model's JSON.

### 4.5 LLM wrapper (B → everyone)

`deadlang/llm.py`:

```python
class BudgetExceeded(Exception): ...

async def call_json(*, model: str, system: str, user: str, schema_name: str,
                    schema: dict, case_id: str | None, max_tokens: int = 2000,
                    temperature: float = 0.0) -> dict
# Forces a single tool call named `schema_name` with input_schema `schema`; returns the tool input dict.

async def call_vision_json(*, model: str, system: str, user: str, image_paths: list[Path],
                           schema_name: str, schema: dict, case_id: str | None,
                           max_tokens: int = 1500, temperature: float = 0.0) -> dict

def usage_snapshot(case_id: str | None = None) -> dict   # {"input_tokens":..,"output_tokens":..,"calls":..}
```

Until Person B commits the real one (target: hour 2), others may use a stub with the same signature that returns canned dicts.

### 4.6 Facilitator and API (C → D)

REST (FastAPI on `http://localhost:8000`, CORS open to `http://localhost:3000`):

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /api/listings` | `?sort=triage` | `[{listing: Listing, seller: Seller, triage: {score: float, reason: str} | null}]` |
| `GET /api/listings/{id}` | – | `{listing, seller}` (any status) |
| `POST /api/cases` | `{"listing_id": "L0123"}` | `{"case_id": "C-0001"}` and starts the case in the background |
| `GET /api/cases` | – | `[{case_id, listing_id, outcome | null, started_at}]` |
| `GET /api/cases/{case_id}/events` | SSE stream | every `Event` for the case from seq 0, then live ones; ends after `case.ended` |
| `GET /api/cases/{case_id}/casefile` | – | `CaseFile` or 404 until ended |
| `POST /api/demo/remove-listing` | `{"listing_id": "L0123"}` | `{"removed": "L0123", "relisted_as": "L0456" | null}` |
| `POST /api/demo/reset` | – | `{"ok": true}` |
| `POST /api/demo/kill-specialist` | `{"name": "deadlang-examiner-thorough"}` | `{"ok": true}` (marks it unhealthy so the fallback path is exercised even without killing a process) |
| `GET /api/replays` | – | `["d1_network", "d2_tagua", ...]` |
| `GET /api/replays/{name}` | – | `Event[]` (recorded run) |
| `GET /api/eval` | – | contents of `results/eval.json` |
| `GET /api/images/{rel_path}` | – | image file from `data/` |

SSE format: `event: <Event.type>` and `data: <Event JSON>` per message.

### 4.7 Event payloads (C → D)

| type | payload |
|---|---|
| `case.started` | `{"listing": Listing, "seller": Seller}` |
| `evidence.added` | `{"evidence": Evidence}` |
| `specialist.selected` | `{"capability", "specialist_name", "why", "requested_by", "candidates": [str]}` |
| `specialist.failed` | `{"capability", "specialist_name", "error", "fallback": str | null}` |
| `round.started` | `{"round": int, "active": [AgentName]}` (agents called this round; round 1 is all three, later rounds only the triggered ones) |
| `stance.posted` | `{"post": StancePost}` (already validated; rejected claims removed) |
| `claim.rejected` | `{"agent", "round", "claim_text", "reasons": [str]}` |
| `listing.removed` | `{"listing_id", "relisted_as": str | null}` |
| `case.ended` | `{"case_file": CaseFile}` |
| `budget.exceeded` | `{"detail": str}` |

## 5. Ports, processes, env

Ports: SLIM `46357`, Directory gRPC `8888` (health `8889`), zot `5555`, marketplace MCP `8100`, API `8000`, frontend `3000`.

`.env.example`:

```
ANTHROPIC_API_KEY=
DL_MODEL_STRONG=claude-sonnet-5-5
DL_MODEL_FAST=claude-haiku-4-5-20251001
DL_MAX_INPUT_TOKENS=6000000
DL_MAX_OUTPUT_TOKENS=600000
DL_CASE_MAX_INPUT_TOKENS=300000
DL_CASE_MAX_OUTPUT_TOKENS=30000
DL_USAGE_FILE=.usage.json
DL_DATA_DIR=../data
MARKETPLACE_MODE=local          # local | mcp
MARKETPLACE_MCP_URL=http://localhost:8100/mcp
TRANSPORT=local                 # local | agntcy
DISCOVERY=local                 # local | agntcy
SLIM_ENDPOINT=http://localhost:46357
SLIM_SHARED_SECRET=deadlang-shared-secret-change-me-32chars-min
DIRECTORY_ADDRESS=127.0.0.1:8888
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

`Procfile` (Person B, run with `uvx honcho start`):

```
market: cd backend && uv run python -m deadlang.marketplace.server
specialists: cd backend && uv run python -m deadlang.agntcy.serve --group specialists
examiner: cd backend && uv run python -m deadlang.agntcy.serve --group examiner-thorough
agents: cd backend && uv run python -m deadlang.agntcy.serve --group deliberators
api: cd backend && uv run uvicorn deadlang.api.server:app --port 8000
web: cd frontend && npm run dev
```

In `TRANSPORT=local` mode only `market` (optional), `api` and `web` are needed.

**Rule:** when `TRANSPORT=agntcy`, set `MARKETPLACE_MODE=mcp` so every process sees the same removed/relisted state through the one marketplace server. In `TRANSPORT=local`, `MARKETPLACE_MODE=local` is fine because everything runs inside the API process.

## 6. Starter UI fixture (Person C writes in kickoff, Person D builds against it)

`fixtures/sample_case_events.jsonl` — one JSON `Event` per line. Minimum content (C fills realistic text):

1. `case.started` with a "bone" netsuke listing L0101 at $1,450, seller S0042.
2. `evidence.added` E0 listing_snapshot.
3. `specialist.selected` price_check → deadlang-price-checker, why "only price specialist registered".
4. `evidence.added` E1 price_check: summary "Comparable bone netsuke (n=38) have a median price of $95; this listing is 15.3x that."
5. `evidence.added` E2 seller_inventory, E3 linked_sellers (none yet), E4 legal_lookup, E5 material_exam (cannot_tell, photo 0).
6. `round.started` 1.
7. Three `stance.posted`: buyer file 0.7, defender dismiss 0.6 (claims citing E5 "examiner could not tell"), caseload need_more 0.5 with request linked_sellers.
8. `claim.rejected` for defender: "Bone netsuke often sell for $1,000" — reason "number 1000 not found in cited evidence E1".
9. `specialist.selected` material_exam → deadlang-examiner-thorough, why "preferred tier; healthy".
10. `evidence.added` E6 material_exam elephant_ivory 0.8 photo 2 "cross-hatched grain visible on base".
11. `round.started` 2, three `stance.posted` (defender changes to file citing E6; caseload file citing E7 linked sellers).
12. `case.ended` with outcome FILE and a short tip_draft.

## 7. Timeline (relative to hacking start; adjust to the real kickoff time)

| When | A — Data | B — Agent network | C — Deliberation | D — Product |
|---|---|---|---|---|
| 0:00–0:45 | Kickoff (all) | | | |
| 0:45–4:00 | eBay + Met pulls, dataset build, store | Infra up; AGNTCY spike; llm.py | prompts, validator, rules (unit tests with fake data) | UI shell on fixture; pitch outline |
| **4:00 checkpoint** | `listings.jsonl` ≥100 rows | **Go/no-go on AGNTCY broadcast + Directory** (else local transport + AGNTCY point-to-point only) | protocol runs end-to-end with stub specialists | case page renders fixture |
| 4:00–8:00 | code specialists + MCP server; reconstructed cases + networks | examiners, translator, wrappers, discovery | facilitator + API + SSE on real specialists | live SSE; browse page; deck draft |
| **8:00 checkpoint** | all specialists pass tests | full run in TRANSPORT=agntcy | D1–D3 run live end to end | full demo clickable |
| Sleep (stagger: at least one person awake per 2h is optional, not required) | | | | |
| next 4h | labels; museum set; demo data tuning | examiner eval; triage; kill/fallback demo | eval runner; replays recorded | results slide; script; rehearsal 1 |
| **Sun 10:30 AM** | **Feature freeze. Only bug fixes after this.** | | | |
| 10:30–12:30 | | | | rehearsals ×3; backup video; Devpost draft |
| **Sun 1:00 PM** | **Devpost submitted** (deadline 1:30) | | | |

## 8. Definition of done (whole project)

- `TRANSPORT=agntcy` run of D1, D2, D3 succeeds live, with events visible in the UI.
- `TRANSPORT=local` run of the same cases succeeds (fallback).
- Replays of D1–D3 exist in `fixtures/replays/` and play in the UI with the backend off.
- `results/eval.json` and `results/examiner_eval.json` exist and the numbers on the results slide match them.
- Devpost has: working demo video, architecture overview, technical implementation, results and lessons learned (Cisco's four requested items).
