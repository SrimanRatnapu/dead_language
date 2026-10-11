"use client";
import { CAPABILITY_LABEL, prettyName } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { LEAN_BAR, LEAN_LABEL, LEAN_STYLE, leanCounts, leanOf, type Lean } from "@/lib/lean";
import type { Capability } from "@/lib/types";
import { Icon } from "./Icon";

const WORKING: Partial<Record<Capability, string>> = {
  price_check: "Comparing the price with similar listings",
  seller_inventory: "Looking through the seller's other listings",
  linked_sellers: "Looking for sellers who share wording or photos",
  legal_lookup: "Finding the law that applies",
  material_exam: "Studying the photos",
  translation: "Translating the listing",
};

// Page two: the specialists work one after another. Each card appears when its specialist starts, then fills in.
export function Examination({ state, ready, onBack, onSend, onOpen }: { state: CaseState; ready: boolean; onBack: () => void; onSend: () => void; onOpen: (id: string) => void }) {
  const caps = [...new Set([...state.selections.map((s) => s.capability), ...state.failures.map((f) => f.capability)])]
    .filter((c) => c !== "listing_snapshot" && c !== "system_notice");
  const cards = caps.map((cap) => ({
    cap,
    ev: [...state.evidenceOrder].reverse().map((id) => state.evidence[id]).find((e) => e?.capability === cap),
    fail: state.failures.find((f) => f.capability === cap),
  }));
  const found = cards.flatMap((c) => c.ev ?? []);
  const counts = leanCounts(found);
  const scored = counts.concern + counts.unclear + counts.lawful;
  const top: Lean | null = scored === 0 ? null : counts.concern > counts.lawful ? "concern" : counts.lawful > counts.concern ? "lawful" : "unclear";
  const done = cards.filter((c) => c.ev || c.fail).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[620px] flex-col gap-4 px-5 py-4 sm:px-8">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">What the specialists found</h2>
            <div className="mt-4" aria-label="Which way the findings point">
              <div className="flex h-2 gap-0.5" aria-hidden>
                {(["concern", "unclear", "lawful"] as Lean[]).map((l) => counts[l] > 0 && <span key={l} className={`${LEAN_BAR[l]} transition-[flex-grow] duration-500`} style={{ flexGrow: counts[l] }} />)}
                {scored === 0 && <span className="grow bg-line" />}
              </div>
              <p className="mt-2 text-base" aria-live="polite">
                {top ? <><b className={top === "concern" ? "text-red" : top === "lawful" ? "text-green" : ""}>{top === "concern" ? "Leaning toward concern" : top === "lawful" ? "Leaning lawful" : "Mixed so far"}</b>
                  <span className="text-muted"> · {counts.concern} raise concern, {counts.unclear} unclear, {counts.lawful} look lawful</span></>
                  : <span className="text-muted">Nothing in yet</span>}
              </p>
            </div>
          </div>

          <ol className="flex flex-col divide-y divide-line border-t border-line">
            {cards.map(({ cap, ev, fail }, i) => {
              const lean = ev ? leanOf(ev) : null;
              return (
                <li key={cap} className="rise py-3" style={{ animationDelay: `${i * 90}ms` }}>
                  <div className="flex items-center justify-between gap-3">
                    <p className="flex min-w-0 items-center gap-2 font-semibold"><Icon name={cap} size={16} className={ev ? "text-cobalt-ink" : "text-muted"} />{CAPABILITY_LABEL[cap]}</p>
                    {lean ? <span className={`px-2 py-0.5 text-base font-semibold ${LEAN_STYLE[lean]}`}>{LEAN_LABEL[lean]}</span>
                      : !ev && !fail ? <span className="typing flex gap-1 text-muted" role="status" aria-label="In progress"><span /><span /><span /></span> : null}
                  </div>
                  <div className="mt-1 [text-wrap:pretty]">
                    {ev ? <p className="rise leading-snug">{ev.summary}</p>
                      : fail ? <p className="text-red">{prettyName(fail.specialist_name)} did not answer{fail.error === "budget" ? " (token cap reached)" : ""}{fail.fallback ? `. Trying ${prettyName(fail.fallback)}.` : ""}</p>
                      : <p className="text-muted">{WORKING[cap] ?? "Working"}…</p>}
                  </div>
                </li>
              );
            })}
            {cards.length === 0 && <li className="flex items-center gap-2.5 text-muted" role="status"><span className="typing flex gap-1"><span /><span /><span /></span>Starting the specialists</li>}
          </ol>
        </div>
      </div>

      <div className="flex shrink-0 items-center justify-between gap-4 bg-surface px-5 py-2 sm:px-8">
        <button onClick={onBack} className="press -ml-3 min-h-11 px-3 py-2.5 font-semibold text-muted hover:text-ink">← Read the listing</button>
        <div className="flex items-center gap-4">
          {!ready && <p className="hidden whitespace-nowrap text-muted sm:block" aria-live="polite">{done} of {Math.max(cards.length, 5)} done</p>}
          <button onClick={onSend} disabled={!ready} className="press min-h-11 bg-ink px-5 py-2.5 font-semibold text-surface enabled:hover:bg-cobalt disabled:opacity-40">Go to the agents →</button>
        </div>
      </div>
    </div>
  );
}
