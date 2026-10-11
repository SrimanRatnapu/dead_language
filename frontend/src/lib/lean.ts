import type { Evidence } from "./types";

// Which way one finding points. A reading of the evidence data for display only; the outcome comes from the agents and the published rule.
export type Lean = "concern" | "unclear" | "lawful";
export const LEAN_LABEL: Record<Lean, string> = { concern: "Raises concern", unclear: "Unclear", lawful: "Looks lawful" };
export const LEAN_STYLE: Record<Lean, string> = { concern: "bg-red-tint text-red", unclear: "bg-sunken text-muted", lawful: "bg-green-tint text-green" };
export const LEAN_BAR: Record<Lean, string> = { concern: "bg-red", unclear: "bg-line", lawful: "bg-green" };

const num = (v: unknown) => (typeof v === "number" ? v : 0);
const len = (v: unknown) => (Array.isArray(v) ? v.length : 0);

export function leanOf(e: Evidence): Lean | null {
  const d = e.data;
  switch (e.capability) {
    case "price_check":
      return d.weak_comparison ? "unclear" : num(d.ratio_to_median) >= 3 ? "concern" : num(d.ratio_to_median) <= 1.5 ? "lawful" : "unclear";
    case "seller_inventory":
      return num(d.n_same_material) >= 3 ? "concern" : num(d.n_listings) <= 2 ? "lawful" : "unclear";
    case "linked_sellers":
      return len(d.linked_sellers) + len(d.shared_phrases) + len(d.matched_image_pairs) > 0 ? "concern" : "lawful";
    case "material_exam": {
      const m = typeof d.material === "string" ? d.material : typeof d.overall === "string" ? d.overall : "cannot_tell";
      return m === "cannot_tell" ? "unclear" : /ivory|elephant|mammoth|tusk|walrus/.test(m) && !/not_ivory|non_ivory/.test(m) ? "concern" : "lawful";
    }
    default:
      return null; // legal_lookup, translation: context, not a lean
  }
}

export function leanCounts(evidence: Evidence[]): Record<Lean, number> {
  const c: Record<Lean, number> = { concern: 0, unclear: 0, lawful: 0 };
  for (const e of evidence) { const l = leanOf(e); if (l) c[l]++; }
  return c;
}
