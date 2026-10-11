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
  const btn = "press min-h-11 px-4 py-2.5 font-semibold disabled:opacity-40";
  return (
    <section className="flex flex-col gap-3 border border-line p-3" aria-label="Human review">
      <h3 className="font-semibold">Human review</h3>
      <p aria-live="polite">{STATUS_TEXT[s.status]}{s.approved_by && s.status !== "pending_review" ? ` · approved by ${s.approved_by}` : ""}</p>
      {s.status === "pending_review" && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-muted">Your name<input value={by} onChange={(e) => setBy(e.target.value)} className="mt-1 block min-h-11 w-56 border border-line bg-surface px-3 text-base text-ink" /></label>
          <button onClick={() => act("approve")} disabled={!by.trim()} className={`${btn} bg-ink text-surface hover:bg-cobalt`}>Approve</button>
        </div>
      )}
      {s.status === "approved" && <button onClick={() => act("submit")} className={`${btn} w-fit bg-ink text-surface hover:bg-cobalt`}>Submit report</button>}
      {simulated && <p className="mono bg-ink px-3 py-2 text-surface">Simulated: nothing is sent to any marketplace</p>}
      {err && <p role="alert" className="text-red">{err}</p>}
    </section>
  );
}
