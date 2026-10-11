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
  return <div className={`rise w-full min-w-0 px-5 py-4 ${tone}`}>
    {cf ? <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <span className={`display min-w-0 ${heavy ? "text-2xl" : "text-xl"}`}>{OUTCOME_LABEL[cf.outcome]}</span>
        <button onClick={onOpenCaseFile} className={`press min-h-9 shrink-0 px-3 py-1 font-semibold ${heavyBtn}`}>Open case file</button>
      </div>
      <p className={`text-base [text-wrap:pretty] ${heavy ? "text-surface/85" : "text-muted"}`}>{STOP_REASON_TEXT[cf.stop_reason]}</p>
    </div> : <span className="text-red">Spending limit reached: {state.budgetExceeded}</span>}
  </div>;
}
