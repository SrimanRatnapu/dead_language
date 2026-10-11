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
    take: str = ""                                # 1-2 sentences, first person, in character; shown as the headline in the UI. Not fact-checked, so no figures.
    abstained: bool = False                       # Caseload sat out because there are no other cases to compare; set by the Facilitator, never by a model; excluded from the outcome rule

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
