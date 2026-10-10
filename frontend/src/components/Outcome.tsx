"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

// The rarest moment gets the most motion: the outcome word lands once.
export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const cleared = cf?.outcome === "DISMISS";
  return (
    <div className={`flex shrink-0 items-center gap-6 border-t border-line px-6 py-4 ${cleared ? "bg-green-tint" : "bg-surface"}`}>
      {cf ? (
        <>
          <span className="land display text-5xl">{OUTCOME_LABEL[cf.outcome]}</span>
          <span className="rise text-muted">
            {STOP_REASON_TEXT[cf.stop_reason]}, after {cf.rounds_used} {cf.rounds_used === 1 ? "round" : "rounds"}.
            <br />A person reviews this before anything is sent.
          </span>
          <button onClick={onOpenCaseFile} className="press ml-auto rounded-full bg-ink px-5 py-2.5 font-medium text-bg">Open case file</button>
        </>
      ) : (
        <span>Spending limit reached: {state.budgetExceeded}</span>
      )}
    </div>
  );
}
