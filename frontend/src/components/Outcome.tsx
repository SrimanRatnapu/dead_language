"use client";
import { AGENTS, OUTCOME_LABEL, STANCE_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";

export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const cleared = cf?.outcome === "DISMISS";
  const heavy = cf?.outcome === "FILE" || cf?.outcome === "CONTESTED";
  const tone = !cf ? "bg-red-tint" : heavy ? "bg-ink text-surface" : cleared ? "bg-green-tint" : "bg-cobalt-tint";
  const heavyBtn = heavy ? "bg-surface text-ink hover:bg-cobalt-tint" : "bg-ink text-surface hover:bg-cobalt";
  return <div className={`shrink-0 border-b border-line px-5 py-5 sm:px-8 ${tone}`}>
    {cf ? <div className="mx-auto flex max-w-[760px] flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2" aria-label="How the outcome was set">
        {cf.final_positions.map((p) => <span key={p.agent} className={`inline-flex items-center gap-2 border px-2.5 py-1 text-[0.82rem] ${heavy ? "border-surface/40" : "border-line bg-surface/70"}`}><i className="size-2 rounded-full" style={{ background: AGENTS[p.agent].cssVar }} /><b>{AGENTS[p.agent].label}</b> {STANCE_LABEL[p.stance].toLowerCase()}</span>)}
        <span aria-hidden>→</span>
        <span className={`display ${heavy ? "text-4xl" : "text-3xl"}`}>{OUTCOME_LABEL[cf.outcome]}</span>
      </div>
      <p className={heavy ? "text-surface/85" : "text-muted"}>No one decided this. A published rule read the three final positions. {STOP_REASON_TEXT[cf.stop_reason]}. Nothing is sent without a person.</p>
      <button onClick={onOpenCaseFile} className={`press min-h-11 w-fit px-4 py-2.5 font-semibold ${heavyBtn}`}>Open case file</button>
    </div> : <span className="text-red">Spending limit reached: {state.budgetExceeded}</span>}
  </div>;
}
