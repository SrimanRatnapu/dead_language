"use client";
import { useEffect, useState } from "react";
import { getStrike, postStrike } from "@/lib/api";
import type { Strike } from "@/lib/types";

const STATUS_TEXT = {
  none: "No review needed",
  pending_review: "Waiting for review",
  approved: "Approved",
  submitted_simulated: "Submitted (simulated)",
  observed_removed: "Listing removed",
} as const;

/** Human gate for FILE/CONTESTED cases. Renders nothing for cases the backend does not know (replays). */
export function StrikeReview({ caseId }: { caseId: string }) {
  const [s, setS] = useState<Strike | null>(null);
  const [by, setBy] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getStrike(caseId).then(setS).catch(() => setS(null)); }, [caseId]);
  if (!s || s.status === "none") return null;

  async function act(action: "approve" | "submit") {
    setErr(null);
    try { setS(await postStrike(caseId, action, by)); } catch { setErr("That did not go through. Check the name and try again."); }
  }
  const simulated = s.status === "submitted_simulated" || s.status === "observed_removed";
  const btn = "press min-h-9 px-3 py-1 font-semibold disabled:opacity-40";
  return (
    <section className="flex flex-wrap items-center gap-x-3 gap-y-2 text-base" aria-label="Human review">
      <h3 className="font-semibold">Human review</h3>
      <p aria-live="polite" className="text-muted">{STATUS_TEXT[s.status]}{s.approved_by && s.status !== "pending_review" ? ` · approved by ${s.approved_by}` : ""}</p>
      {s.status === "pending_review" && <>
        <input value={by} onChange={(e) => setBy(e.target.value)} placeholder="Your name" aria-label="Your name" className="min-h-9 w-40 border border-line bg-surface px-2 text-ink" />
        <button onClick={() => act("approve")} disabled={!by.trim()} className={`${btn} bg-ink text-surface hover:bg-cobalt`}>Approve</button>
      </>}
      {s.status === "approved" && <button onClick={() => act("submit")} className={`${btn} bg-ink text-surface hover:bg-cobalt`}>Submit report</button>}
      {err && <p role="alert" className="w-full text-red">{err}</p>}
    </section>
  );
}
