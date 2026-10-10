"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const cleared = cf?.outcome === "DISMISS";
  return <div className={`shrink-0 border-t border-line px-5 py-4 sm:px-8 ${cleared ? "bg-green-tint" : "bg-cobalt-tint"}`}>
    {cf ? <div className="mx-auto flex max-w-[760px] flex-wrap items-center gap-x-5 gap-y-2"><div><p className="rule-label">Review outcome</p><span className="land display text-4xl">{OUTCOME_LABEL[cf.outcome]}</span></div><span className="max-w-md text-muted">{STOP_REASON_TEXT[cf.stop_reason]}. A person reviews this before anything is sent.</span><button onClick={onOpenCaseFile} className="press ml-auto bg-ink px-4 py-2.5 font-semibold text-surface hover:bg-cobalt">Open case file</button></div> : <span>Spending limit reached: {state.budgetExceeded}</span>}
  </div>;
}
