"use client";
import { CAPABILITY_LABEL } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Icon } from "./Icon";

export function EvidenceBoard({ state, onOpen }: { state: CaseState; onOpen: (id: string) => void }) {
  return (
    <ol className="flex flex-col gap-2">
      {state.evidenceOrder.map((id) => {
        const ev = state.evidence[id];
        return (
          // key by id: a new item mounts once, so the flash plays once
          <li key={id} className="flash rounded-lg border border-line bg-surface">
            <button onClick={() => onOpen(id)} className="press flex w-full gap-3 p-3 text-left">
              <Icon name={ev.capability} className="mt-0.5 shrink-0 text-muted" />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="mono font-semibold">{id}</span>
                  <span className="font-medium">{CAPABILITY_LABEL[ev.capability]}</span>
                  <span className="mono rounded bg-sunken px-1.5 text-muted">
                    {ev.produced_by === "code" ? "code" : `AI · conf ${ev.confidence ?? "n/a"}`}
                  </span>
                </span>
                <span>{ev.summary}</span>
                <span className="text-muted">Requested by {ev.requested_by}</span>
              </span>
            </button>
          </li>
        );
      })}
      {state.evidenceOrder.length === 0 && <li className="text-muted">No evidence yet.</li>}
    </ol>
  );
}
