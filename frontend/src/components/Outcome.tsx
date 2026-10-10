"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const cleared = cf?.outcome === "DISMISS";
  const heavy = cf?.outcome === "FILE" || cf?.outcome === "CONTESTED";
  const tone = !cf ? "bg-red-tint" : heavy ? "bg-ink text-surface" : cleared ? "bg-green-tint" : "bg-cobalt-tint";
  return <div className={`sticky bottom-0 z-10 shrink-0 border-t border-line px-5 py-5 lg:static sm:px-8 ${tone}`}>
    {cf ? <div className="mx-auto flex max-w-[760px] flex-wrap items-center gap-x-5 gap-y-3"><div><p className="rule-label">Review outcome</p><span className={`land display ${heavy ? "text-5xl" : "text-4xl"}`}>{OUTCOME_LABEL[cf.outcome]}</span></div><div className="flex max-w-md flex-col gap-2"><span className={heavy ? "text-surface/85" : "text-muted"}>{STOP_REASON_TEXT[cf.stop_reason]}.</span><span className={`mono inline-flex w-fit items-center border px-2 py-1 ${heavy ? "border-surface/60 text-surface" : "border-line text-ink"}`}>Not sent · pending human review</span></div><button onClick={onOpenCaseFile} className={`press ml-auto min-h-11 px-4 py-2.5 font-semibold ${heavy ? "bg-surface text-ink hover:bg-cobalt-tint" : "bg-ink text-surface hover:bg-cobalt"}`}>Open case file</button></div> : <p role="alert" className="mx-auto max-w-[760px] font-medium text-red"><span className="font-semibold">Spending limit reached.</span> The review stopped at {state.budgetExceeded}. Positions shown are the last validated ones; nothing was sent.</p>}
  </div>;
}
