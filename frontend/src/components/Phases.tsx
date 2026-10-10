"use client";
import { CAPABILITY_LABEL, prettyName } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Icon } from "./Icon";

type Open = (id: string) => void;

// Two phases the judge can see apart: helpers gather facts, then the agents argue.
export function Phases({ state, onOpen }: { state: CaseState; onOpen: Open }) {
  const ended = state.caseFile !== null || state.budgetExceeded !== null;
  const talking = state.rounds.length > 0;
  const step = ended ? 3 : talking ? 2 : 1;
  const steps = ["Gather facts", "Agents discuss", "Outcome"];
  const exam = [...state.evidenceOrder].map((id) => state.evidence[id]).filter((e) => e?.capability === "material_exam").at(-1);
  const sel = [...state.selections].reverse().find((s) => s.capability === "material_exam");
  const fail = state.failures.find((f) => f.capability === "material_exam");
  const facts = state.evidenceOrder.length;

  return (
    <div className="border-b border-line px-5 py-3 sm:px-8">
      <ol className="flex items-center gap-2" aria-label="Review progress">
        {steps.map((s, i) => {
          const done = step > i + 1, on = step === i + 1;
          return (
            <li key={s} className="flex flex-1 items-center gap-2" aria-current={on ? "step" : undefined}>
              <span className={`grid size-6 shrink-0 place-items-center rounded-full text-sm font-semibold transition-colors duration-500 ${done ? "bg-ink text-surface" : on ? "bg-cobalt text-white" : "bg-sunken text-muted"}`}>{done ? <Icon name="check" size={12} /> : i + 1}</span>
              <span className={`text-sm ${on ? "font-semibold text-ink" : "text-muted"}`}>{s}</span>
              {i < 2 && <span className="relative h-px flex-1 bg-line"><span className="absolute inset-y-0 left-0 bg-ink transition-[width] duration-700 ease-out" style={{ width: done ? "100%" : on ? "50%" : "0%" }} /></span>}
            </li>
          );
        })}
      </ol>

      {step <= 1 && !exam && <p className="mt-2 text-sm text-muted">{facts > 0 ? `${facts} facts on the shared board. Waiting for the photo exam…` : "Looking up price, seller history and law…"}</p>}
      {exam && (
        <button onClick={() => onOpen(exam.id)} className="press rise mt-3 grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 border border-line bg-surface/70 p-3 text-left hover:border-ink">
          <Icon name="material_exam" size={20} />
          <span className="min-w-0">
            <span className="block text-sm font-semibold">{CAPABILITY_LABEL.material_exam}{sel ? ` · ${prettyName(sel.specialist_name)}` : ""}</span>
            <span className="block text-sm text-muted [text-wrap:pretty]">{exam.summary}</span>
            {fail && <span className="mt-1 block text-sm text-amber-ink">{prettyName(fail.specialist_name)} did not answer{fail.fallback ? `, switched to ${prettyName(fail.fallback)}` : ""}.</span>}
          </span>
          <span className="text-right"><span className="display block text-2xl">{Math.round((exam.confidence ?? 0) * 100)}%</span><span className="text-sm text-muted">sure</span></span>
        </button>
      )}
    </div>
  );
}
