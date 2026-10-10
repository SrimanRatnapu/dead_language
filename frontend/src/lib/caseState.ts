import type {
  AgentName, CaseFile, Capability, Evidence, Event, Listing, Requester, Seller, StancePost,
} from "./types";

export interface Round {
  round: number;
  active: AgentName[];
  posts: Partial<Record<AgentName, StancePost>>;
  rejected: { agent: AgentName; claim_text: string; reasons: string[] }[];
}

export interface Selection {
  capability: Capability;
  specialist_name: string;
  why: string;
  requested_by: Requester;
  at: string;
}

export interface Failure {
  capability: Capability;
  specialist_name: string;
  error: string;
  fallback: string | null;
  at: string;
}

export interface CaseState {
  listing: Listing | null;
  seller: Seller | null;
  evidence: Record<string, Evidence>;
  evidenceOrder: string[];
  rounds: Round[];
  selections: Selection[];
  failures: Failure[];
  removed: { listing_id: string; relisted_as: string | null } | null;
  caseFile: CaseFile | null;
  budgetExceeded: string | null;
  lastSeq: number;
}

export const initialCaseState: CaseState = {
  listing: null,
  seller: null,
  evidence: {},
  evidenceOrder: [],
  rounds: [],
  selections: [],
  failures: [],
  removed: null,
  caseFile: null,
  budgetExceeded: null,
  lastSeq: -1,
};

// Posts and rejections can arrive before/without a round.started; create the round on demand.
function withRound(rounds: Round[], n: number, fn: (r: Round) => Round): Round[] {
  const i = rounds.findIndex((r) => r.round === n);
  if (i < 0) return [...rounds, fn({ round: n, active: [], posts: {}, rejected: [] })];
  return rounds.map((r, j) => (j === i ? fn(r) : r));
}

export function reduce(state: CaseState, e: Event): CaseState {
  if (e.seq <= state.lastSeq) return state;
  const next = { ...state, lastSeq: e.seq };
  switch (e.type) {
    case "case.started":
      return { ...next, listing: e.payload.listing, seller: e.payload.seller };
    case "evidence.added": {
      const ev = e.payload.evidence;
      const seen = ev.id in state.evidence;
      return {
        ...next,
        evidence: { ...state.evidence, [ev.id]: ev },
        evidenceOrder: seen ? state.evidenceOrder : [...state.evidenceOrder, ev.id],
      };
    }
    case "specialist.selected": {
      const { capability, specialist_name, why, requested_by } = e.payload;
      return { ...next, selections: [...state.selections, { capability, specialist_name, why, requested_by, at: e.at }] };
    }
    case "specialist.failed":
      return { ...next, failures: [...state.failures, { ...e.payload, at: e.at }] };
    case "round.started":
      return {
        ...next,
        rounds: withRound(state.rounds, e.payload.round, (r) => ({ ...r, active: e.payload.active })),
      };
    case "stance.posted": {
      const post = e.payload.post;
      return { ...next, rounds: withRound(state.rounds, post.round, (r) => ({ ...r, posts: { ...r.posts, [post.agent]: post } })) };
    }
    case "claim.rejected": {
      const { agent, round, claim_text, reasons } = e.payload;
      return { ...next, rounds: withRound(state.rounds, round, (r) => ({ ...r, rejected: [...r.rejected, { agent, claim_text, reasons }] })) };
    }
    case "listing.removed":
      return {
        ...next,
        removed: { listing_id: e.payload.listing_id, relisted_as: e.payload.relisted_as },
        listing: state.listing ? { ...state.listing, status: "removed" } : null,
      };
    case "case.ended":
      return { ...next, caseFile: e.payload.case_file };
    case "budget.exceeded":
      return { ...next, budgetExceeded: e.payload.detail };
  }
}
