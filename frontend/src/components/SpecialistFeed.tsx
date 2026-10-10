import { CAPABILITY_LABEL } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Icon } from "./Icon";

// Dynamic discovery and fallback, in plain sentences.
export function SpecialistFeed({ state }: { state: CaseState }) {
  const items = [
    ...state.selections.map((s) => ({ kind: "selected" as const, at: s.at, s })),
    ...state.failures.map((f) => ({ kind: "failed" as const, at: f.at, f })),
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  if (items.length === 0) return <p className="text-muted">No specialists called yet.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((it, i) =>
        it.kind === "selected" ? (
          <li key={i} className="rise flex gap-2">
            <Icon name={it.s.capability} className="mt-0.5 shrink-0 text-muted" />
            <span><span className="font-medium">{CAPABILITY_LABEL[it.s.capability]}:</span> {it.s.why}</span>
          </li>
        ) : (
          <li key={i} className="rise flex gap-2 rounded-lg bg-sunken p-2">
            <Icon name="system_notice" className="mt-0.5 shrink-0 text-red" />
            <span>
              <span className="mono">{it.f.specialist_name}</span> failed ({it.f.error}).
              {it.f.fallback ? <> Switched to <span className="mono">{it.f.fallback}</span>.</> : " No fallback available."}
            </span>
          </li>
        ),
      )}
    </ul>
  );
}
