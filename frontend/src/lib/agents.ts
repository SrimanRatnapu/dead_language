import type { AgentName, Capability, Outcome, Stance, StopReason } from "./types";

// Fixed across UI, slides and diagram. Class strings are literal so Tailwind sees them.
export const AGENTS: Record<AgentName, { label: string; goal: string; text: string; tint: string; dot: string; ring: string; cssVar: string }> = {
  buyer: { label: "Buyer", goal: "Reads like a buyer", text: "text-amber-ink", tint: "bg-amber-tint", dot: "bg-amber", ring: "border-amber", cssVar: "var(--amber)" },
  defender: { label: "Defender", goal: "Defends the seller", text: "text-teal-ink", tint: "bg-teal-tint", dot: "bg-teal", ring: "border-teal", cssVar: "var(--teal)" },
  caseload: { label: "Caseload", goal: "Guards investigator time", text: "text-violet-ink", tint: "bg-violet-tint", dot: "bg-violet", ring: "border-violet", cssVar: "var(--violet)" },
};
export const AGENT_ORDER: AgentName[] = ["buyer", "defender", "caseload"];

export const STANCE_LABEL: Record<Stance, string> = { file: "File", dismiss: "Dismiss", need_more: "Needs more" };

export const CAPABILITY_LABEL: Record<Capability, string> = {
  listing_snapshot: "Listing snapshot",
  price_check: "Price check",
  seller_inventory: "Seller inventory",
  linked_sellers: "Linked sellers",
  legal_lookup: "Legal basis",
  material_exam: "Photo exam",
  translation: "Translation",
  system_notice: "System notice",
};

export const OUTCOME_LABEL: Record<Outcome, string> = {
  FILE: "File it",
  DISMISS: "Dismiss",
  CONTESTED: "Needs a person",
  WATCHLIST: "Keep watching",
};

export const STOP_REASON_TEXT: Record<StopReason, string> = {
  unanimous: "All three agreed",
  ready_to_close: "All three said they had nothing more to add",
  no_movement: "Positions stopped moving",
  max_rounds: "Reached the round limit",
  budget: "Budget limit reached",
};

// "deadlang-examiner-thorough" -> "examiner thorough"
export const prettyName = (n: string) => n.replace(/^deadlang-/, "").replaceAll("-", " ");

export const usd = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
