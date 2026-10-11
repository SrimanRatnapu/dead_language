"use client";
import { CAPABILITY_LABEL, prettyName } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { Capability } from "@/lib/types";
import { Icon } from "./Icon";

const CAPS: Capability[] = ["price_check", "seller_inventory", "linked_sellers", "legal_lookup", "material_exam"];

// Stage one: the helpers examine the listing. Nothing here involves the agents.
export function Examination({ state, ready, onSend, onOpen }: { state: CaseState; ready: boolean; onSend: () => void; onOpen: (id: string) => void }) {
  const caps = state.listing && state.listing.language !== "en" ? [...CAPS, "translation" as Capability] : CAPS;
  const rows = caps.map((cap) => {
    const ev = [...state.evidenceOrder].reverse().map((id) => state.evidence[id]).find((e) => e?.capability === cap);
    const sel = [...state.selections].reverse().find((s) => s.capability === cap);
    const fail = state.failures.find((f) => f.capability === cap);
    return { cap, ev, sel, fail };
  });
  const done = rows.filter((r) => r.ev).length;

  return (
    <div className="mx-auto flex max-w-[640px] flex-col gap-6 px-5 py-8 sm:px-8">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Examining the listing</h2>
        <p className="mt-1 text-muted">Specialist helpers check price, seller, law and photos. Each finding is marked on the listing as it arrives.</p>
      </div>

      <ol className="divide-y divide-line border-y border-line">
        {rows.map(({ cap, ev, sel, fail }) => (
          <li key={cap} className="grid grid-cols-[1.5rem_1fr_auto] items-start gap-x-4 py-4">
            <Icon name={cap} size={18} className={ev ? "mt-0.5 text-cobalt-ink" : "mt-0.5 text-muted"} />
            <div className="min-w-0">
              <p className="font-semibold">{CAPABILITY_LABEL[cap]}{sel && <span className="ml-2 text-sm font-normal text-muted">{prettyName(sel.specialist_name)}</span>}</p>
              {ev ? <button onClick={() => onOpen(ev.id)} className="press rise mt-1 text-left text-muted [text-wrap:pretty] hover:text-ink">{ev.summary}</button>
                : fail ? <p className="mt-1 text-red">{prettyName(fail.specialist_name)} did not answer{fail.fallback ? `. Trying ${prettyName(fail.fallback)}.` : ""}</p>
                : <p className="mt-1 text-muted">Working on it…</p>}
            </div>
            <div className="pt-0.5 text-right">
              {ev ? (ev.produced_by === "model" && ev.confidence !== null ? <span className="mono text-muted">{Math.round(ev.confidence * 100)}% sure</span> : <Icon name="check" size={16} className="text-green" />)
                : <span className="typing flex gap-1 text-muted" role="status" aria-label="In progress"><span /><span /><span /></span>}
            </div>
          </li>
        ))}
      </ol>

      <div className="sticky bottom-0 -mx-5 flex items-center justify-between gap-4 border-t border-line bg-surface/95 px-5 py-3 sm:-mx-8 sm:px-8">
        <p className="text-muted" aria-live="polite">{ready ? "Examination complete." : `${done} of ${rows.length} done`}</p>
        <button onClick={onSend} disabled={!ready} className="press min-h-11 bg-ink px-5 py-2.5 font-semibold text-surface enabled:hover:bg-cobalt disabled:opacity-40">Hand findings to the agents →</button>
      </div>
    </div>
  );
}
