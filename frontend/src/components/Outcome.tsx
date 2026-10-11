"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const cleared = cf?.outcome === "DISMISS";
  const heavy = cf?.outcome === "FILE" || cf?.outcome === "CONTESTED";
  const tone = !cf ? "bg-red-tint" : heavy ? "bg-ink text-surface" : cleared ? "bg-green-tint" : "bg-cobalt-tint";
  const heavyBtn = heavy ? "bg-surface text-ink hover:bg-cobalt-tint" : "bg-ink text-surface hover:bg-cobalt";
  return <div className={`shrink-0 border-b border-line px-4 py-2 sm:px-6 ${tone}`}>
    {cf ? <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <span className={`display ${heavy ? "text-2xl" : "text-xl"}`}>{OUTCOME_LABEL[cf.outcome]}</span>
      <span className={`min-w-0 flex-1 text-base ${heavy ? "text-surface/85" : "text-muted"}`}>{STOP_REASON_TEXT[cf.stop_reason]}</span>
      <button onClick={onOpenCaseFile} className={`press min-h-9 px-3 py-1 font-semibold ${heavyBtn}`}>Open case file</button>
    </div> : <span className="text-red">Spending limit reached: {state.budgetExceeded}</span>}
  </div>;
}
