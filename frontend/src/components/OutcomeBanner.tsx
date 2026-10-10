"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

// Green only for "cleared" (DISMISS). Everything else stays neutral.
export function OutcomeBanner({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;

  const tone = cf?.outcome === "DISMISS" ? "bg-green-tint" : "bg-sunken";
  return (
    <div className={`rise flex h-14 shrink-0 items-center gap-4 border-t border-line px-5 ${tone}`}>
      {cf ? (
        <>
          <span className="display text-2xl">{OUTCOME_LABEL[cf.outcome]}</span>
          <span>
            {STOP_REASON_TEXT[cf.stop_reason]} after {cf.rounds_used} {cf.rounds_used === 1 ? "round" : "rounds"}.
          </span>
          <button onClick={onOpenCaseFile} className="press ml-auto rounded-md bg-ink px-3 py-1.5 font-medium text-bg">
            Open case file
          </button>
        </>
      ) : (
        <span>Budget limit reached: {state.budgetExceeded}</span>
      )}
    </div>
  );
}
