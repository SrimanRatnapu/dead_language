"use client";
import { OUTCOME_LABEL, STOP_REASON_TEXT } from "@/lib/agents";
import { Icon, type IconName } from "./Icon";
import type { CaseState } from "@/lib/caseState";

// Bar colour and icon per outcome (same icons as the desk rows).
const LOOK: Record<string, { icon: IconName; bar: string; text: string }> = {
  FILE: { icon: "flag", bar: "bg-red-tint", text: "text-red" },
  CONTESTED: { icon: "contested", bar: "bg-amber-tint", text: "text-amber-ink" },
  WATCHLIST: { icon: "clock", bar: "bg-cobalt-tint", text: "text-cobalt-ink" },
  DISMISS: { icon: "check", bar: "bg-green-tint", text: "text-green" },
};

export function Outcome({ state, onOpenCaseFile }: { state: CaseState; onOpenCaseFile: () => void }) {
  const cf = state.caseFile;
  if (!cf && !state.budgetExceeded) return null;
  const look = cf ? LOOK[cf.outcome] : null;
  return <div className={`rise w-full min-w-0 px-5 py-4 ${look?.bar ?? "bg-red-tint"}`}>
    {cf && look ? <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <span className={`display flex min-w-0 items-center gap-3 text-2xl ${look.text}`}><Icon name={look.icon} size={26} />{OUTCOME_LABEL[cf.outcome]}</span>
        <button onClick={onOpenCaseFile} className="press min-h-9 shrink-0 bg-ink px-3 py-1 font-semibold text-surface hover:bg-cobalt">Open case file</button>
      </div>
      {cf.stop_reason !== "max_rounds" && <p className="text-base text-muted [text-wrap:pretty]">{STOP_REASON_TEXT[cf.stop_reason]}</p>}
    </div> : <span className="text-red">Spending limit reached: {state.budgetExceeded}</span>}
  </div>;
}
