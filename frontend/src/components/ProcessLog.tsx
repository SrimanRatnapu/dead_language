"use client";
import { AGENTS, CAPABILITY_LABEL, OUTCOME_LABEL, STANCE_LABEL, STOP_REASON_TEXT, prettyName } from "@/lib/agents";
import type { CaseState, FeedItem } from "@/lib/caseState";
import { Drawer } from "./Drawer";

type Line = { tag: string; tone: string; text: string; detail?: string };

function line(item: FeedItem, state: CaseState): Line {
  switch (item.kind) {
    case "round": {
      const active = state.rounds.find((r) => r.round === item.round)?.active ?? [];
      return { tag: "round", tone: "text-cobalt-ink", text: `Round ${item.round} opens`, detail: active.length ? `Called: ${active.map((a) => AGENTS[a].label).join(", ")}` : undefined };
    }
    case "selected":
      return { tag: "route", tone: "text-muted", text: `${CAPABILITY_LABEL[item.selection.capability]} → ${prettyName(item.selection.specialist_name)}`, detail: `${item.selection.why} Asked by ${item.selection.requested_by}.` };
    case "failed":
      return { tag: "fail", tone: "text-red", text: `${prettyName(item.failure.specialist_name)} did not answer (${item.failure.error})`, detail: item.failure.fallback ? `Falling back to ${prettyName(item.failure.fallback)}.` : undefined };
    case "evidence": {
      const e = state.evidence[item.id];
      return { tag: item.id, tone: "text-ink", text: `${CAPABILITY_LABEL[e.capability]} added by ${prettyName(e.specialist_name)} (${e.produced_by === "code" ? "code" : "AI reading"})`, detail: e.summary };
    }
    case "post": {
      const p = item.post;
      const asks = p.requests.map((r) => CAPABILITY_LABEL[r.capability].toLowerCase()).join(", ");
      return { tag: "post", tone: AGENTS[p.agent].text, text: `${AGENTS[p.agent].label}: ${STANCE_LABEL[p.stance]} at ${Math.round(p.confidence * 100)}%, ${p.claims.length} checked claim${p.claims.length === 1 ? "" : "s"}`, detail: [p.changed_because && "Changed position.", asks && `Asks for ${asks}.`, p.ready_to_close && "Ready to close."].filter(Boolean).join(" ") || undefined };
    }
    case "rejected":
      return { tag: "check", tone: "text-red", text: `Claim by ${AGENTS[item.agent].label} removed by the claim check`, detail: `“${item.claim_text}” — ${item.reasons.join("; ")}` };
    case "removed":
      return { tag: "alert", tone: "text-red", text: "Seller removed the listing; review continues from the saved snapshot", detail: item.relisted_as ? `A new listing ${item.relisted_as} appeared afterwards.` : undefined };
  }
}

// The run as it happened, one line per pipeline event.
export function ProcessLog({ state, open, onClose }: { state: CaseState; open: boolean; onClose: () => void }) {
  const lines = state.feed.map((item) => line(item, state));
  const cf = state.caseFile;
  return (
    <Drawer open={open} title="Process log" onClose={onClose}>
      <p className="mb-4 text-muted">Every step the pipeline took, in order. Specialists report facts, the claim check runs in code, and a fixed rule sets the outcome.</p>
      <ol className="border-t border-line">
        {lines.map((l, i) => (
          <li key={i} className="grid grid-cols-[2.2rem_3.4rem_1fr] gap-x-2 border-b border-line py-2.5">
            <span className="mono pt-0.5 text-muted">{String(i + 1).padStart(2, "0")}</span>
            <span className={`mono pt-0.5 uppercase ${l.tone}`}>{l.tag}</span>
            <span><span className="font-medium">{l.text}</span>{l.detail && <span className="mt-0.5 block text-[.82rem] leading-snug text-muted">{l.detail}</span>}</span>
          </li>
        ))}
        {cf && (
          <li className="grid grid-cols-[2.2rem_3.4rem_1fr] gap-x-2 bg-cobalt-tint py-2.5">
            <span className="mono pt-0.5 text-muted">{String(lines.length + 1).padStart(2, "0")}</span>
            <span className="mono pt-0.5 uppercase text-cobalt-ink">rule</span>
            <span><span className="font-semibold">Outcome: {OUTCOME_LABEL[cf.outcome]}</span><span className="mt-0.5 block text-[.82rem] text-muted">{STOP_REASON_TEXT[cf.stop_reason]} after {cf.rounds_used} round{cf.rounds_used === 1 ? "" : "s"}. Nothing is sent without a person.</span></span>
          </li>
        )}
      </ol>
      {lines.length === 0 && <p className="mt-4 text-muted">Waiting for the first event.</p>}
    </Drawer>
  );
}
