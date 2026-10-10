// Mirrors backend/deadlang/schemas.py (frozen contract, file 01 §3). Keep snake_case.

export type StatedMaterial = "bone" | "resin" | "tagua" | "wood" | "ivory_color" | "ivory_mentioned" | "unknown";
export type ItemType = "netsuke" | "figurine" | "jewelry" | "other";
export type ListingStatus = "active" | "removed" | "hidden";

export interface Listing {
  id: string;
  marketplace: string;
  seller_id: string;
  title: string;
  description: string;
  price_usd: number;
  category: string;
  stated_material: StatedMaterial;
  item_type: ItemType;
  size_cm: number | null;
  weight_g: number | null;
  ship_from: string;
  language: string;
  image_paths: string[];
  posted_at: string;
  source_url: string | null;
  is_reconstructed: boolean;
  reconstruction_source: string | null;
  status: ListingStatus;
  relist_of: string | null;
}

export interface Seller {
  id: string;
  name: string;
  location: string;
  joined: string;
  feedback_score: number | null;
}

export type Capability =
  | "listing_snapshot" | "price_check" | "seller_inventory" | "linked_sellers"
  | "legal_lookup" | "material_exam" | "translation" | "system_notice";
export type AgentName = "buyer" | "defender" | "caseload";
export type Requester = "intake" | AgentName | "system";

export interface Evidence {
  id: string;
  case_id: string;
  capability: Capability;
  summary: string;
  data: Record<string, unknown>;
  produced_by: "code" | "model";
  confidence: number | null;
  specialist_name: string;
  requested_by: Requester;
  created_at: string;
}

export interface SpecialistRequest {
  capability: Capability;
  question: string;
  reason: string;
  params: Record<string, unknown>;
}

export type Stance = "file" | "dismiss" | "need_more";

export interface Claim {
  text: string;
  evidence_ids: string[];
}

export interface Rebuttal {
  target_agent: AgentName;
  target_claim: string;
  response: string;
  evidence_ids: string[];
}

export interface Challenge {
  target_agent: AgentName;
  question: string;
}

export interface StancePost {
  agent: AgentName;
  round: number;
  stance: Stance;
  confidence: number;
  claims: Claim[];
  rebuttal: Rebuttal | null;
  requests: SpecialistRequest[];
  changed_because: string | null;
  changed_because_evidence: string[];
  challenge: Challenge | null;
  ready_to_close: boolean;
}

export type Outcome = "FILE" | "DISMISS" | "CONTESTED" | "WATCHLIST";
export type StopReason = "unanimous" | "ready_to_close" | "no_movement" | "max_rounds" | "budget";

export interface CaseFile {
  case_id: string;
  listing_id: string;
  seller_id: string;
  outcome: Outcome;
  rounds_used: number;
  stop_reason: StopReason;
  final_positions: StancePost[];
  evidence: Evidence[];
  legal_basis: string[];
  linked_seller_ids: string[];
  tip_draft: string | null;
  status: "awaiting_human_review" | "closed";
  created_at: string;
}

// ---- Events (file 01 §4.7) ----
export interface EventPayloads {
  "case.started": { listing: Listing; seller: Seller };
  "evidence.added": { evidence: Evidence };
  "specialist.selected": { capability: Capability; specialist_name: string; why: string; requested_by: Requester; candidates: string[] };
  "specialist.failed": { capability: Capability; specialist_name: string; error: string; fallback: string | null };
  "round.started": { round: number; active: AgentName[] };
  "stance.posted": { post: StancePost };
  "claim.rejected": { agent: AgentName; round: number; claim_text: string; reasons: string[] };
  "listing.removed": { listing_id: string; relisted_as: string | null };
  "case.ended": { case_file: CaseFile };
  "budget.exceeded": { detail: string };
}
export type EventType = keyof EventPayloads;

export type Event = {
  [T in EventType]: { seq: number; case_id: string; type: T; at: string; payload: EventPayloads[T] };
}[EventType];

export const EVENT_TYPES: EventType[] = [
  "case.started", "evidence.added", "specialist.selected", "specialist.failed", "round.started",
  "stance.posted", "claim.rejected", "listing.removed", "case.ended", "budget.exceeded",
];

// ---- REST shapes (file 01 §4.6) ----
export interface Triage {
  score: number;
  reason: string;
}
export interface ListingRow {
  listing: Listing;
  seller: Seller;
  triage: Triage | null;
}

// results/eval.json shape is not frozen yet; this is the UI's expectation (see public/stub/eval.json).
export type Condition = "listing_only" | "single_agent" | "three_agent";
export interface EvalCondition {
  caught: number;
  wrongly_flagged: number;
  sent_to_human: number;
  tokens_per_case: number;
  claims_rejected: number | null;
}
export interface EvalResults {
  n_cases: number;
  n_should_flag: number;
  n_should_clear: number;
  conditions: Record<Condition, EvalCondition>;
  examiner: { n: number; correct: number; accuracy: number } | null;
  example_cases: { label: string; replay: string }[];
  _stub?: boolean; // set only by public/stub/eval.json: placeholders, not results
}
