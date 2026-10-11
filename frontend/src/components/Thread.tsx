"use client";
import { useEffect, useRef, useState } from "react";
import { AGENTS, CAPABILITY_LABEL } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { StancePost } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { Icon } from "./Icon";
import { StancePill } from "./Seats";

type Open = (id: string) => void;
type Block = { kind: "post"; post: StancePost } | { kind: "result"; id: string } | { kind: "removed"; relisted_as: string | null };

// What the agents and the seller said, plus the answer to any specialist an agent called in.
function toBlocks(state: CaseState): Block[] {
  return state.feed.flatMap((item): Block[] => item.kind === "post" ? [{ kind: "post", post: item.post }]
    : item.kind === "evidence" && state.evidence[item.id]?.requested_by in AGENTS ? [{ kind: "result", id: item.id }]
    : item.kind === "removed" ? [{ kind: "removed", relisted_as: item.relisted_as }] : []);
}

function Chips({ ids, state, onOpen }: { ids: string[]; state: CaseState; onOpen: Open }) {
  return <>{ids.map((id) => <span key={id} className="ml-1 inline-block"><EvidenceChip evidence={state.evidence[id]} onOpen={onOpen} /></span>)}</>;
}

function Message({ post, state, onOpen }: { post: StancePost; state: CaseState; onOpen: Open }) {
  const a = AGENTS[post.agent];
  const rejected = state.rounds.find((r) => r.round === post.round)?.rejected.filter((r) => r.agent === post.agent) ?? [];
  // New posts carry an in-character `take`; older recordings fall back to the first claim as the headline.
  const head = post.take || post.claims[0]?.text;
  const rest = post.take ? post.claims : post.claims.slice(1);
  const detail = rest.length + (post.rebuttal ? 1 : 0) + (rejected.length ? 1 : 0) + (post.changed_because ? 1 : 0);
  return (
    <article className="rise grid grid-cols-[2.25rem_1fr] gap-x-3">
      <span className={`grid size-9 place-items-center font-semibold ${a.tint} ${a.text}`} aria-hidden>{a.label[0]}</span>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center gap-x-2.5">
          <span className={`font-semibold ${a.text}`}>{a.label}</span>
          {post.abstained ? <span className="text-muted">Sat out</span> : <><StancePill stance={post.stance} /><span className="mono text-muted">{Math.round(post.confidence * 100)}%</span></>}
        </header>
        {head && <p className="mt-1.5 text-lg leading-snug [text-wrap:pretty]">{head}</p>}
        {post.challenge && <p className="mt-2 text-lg leading-snug [text-wrap:pretty]"><span className={`font-semibold ${AGENTS[post.challenge.target_agent].text}`}>{AGENTS[post.challenge.target_agent].label}, </span>{post.challenge.question}</p>}
        {detail > 0 && <details className="group mt-2">
          <summary className="press flex min-h-9 cursor-pointer list-none items-center gap-2 text-muted hover:text-ink"><span className="transition-transform duration-200 group-open:rotate-90"><Icon name="chevron" size={14} /></span>Evidence and reasoning{rejected.length > 0 && <span className="text-red"> · {rejected.length} removed</span>}</summary>
          <div className="space-y-2.5 pb-1 pt-1.5 leading-snug">
            {post.changed_because && <p><span className="font-semibold">Changed position: </span>{post.changed_because}<Chips ids={post.changed_because_evidence} state={state} onOpen={onOpen} /></p>}
            {post.rebuttal && <p className="text-muted"><span className={`font-semibold ${AGENTS[post.rebuttal.target_agent].text}`}>{AGENTS[post.rebuttal.target_agent].label}: </span>{post.rebuttal.response}<Chips ids={post.rebuttal.evidence_ids} state={state} onOpen={onOpen} /></p>}
            {rest.length > 0 && <ul className="space-y-2">{rest.map((c, i) => <li key={i}>{c.text}<Chips ids={c.evidence_ids} state={state} onOpen={onOpen} /></li>)}</ul>}
            {rejected.length > 0 && <ul className="space-y-1.5 text-red">{rejected.map((r, i) => <li key={i}><s>{r.claim_text}</s><br /><span className="text-muted">Removed by the checker: {r.reasons.join(" · ")}</span></li>)}</ul>}
          </div>
        </details>}
      </div>
    </article>
  );
}

function Result({ id, state }: { id: string; state: CaseState }) {
  const ev = state.evidence[id];
  const by = AGENTS[ev.requested_by as keyof typeof AGENTS];
  return (
    <article className="rise grid grid-cols-[2.25rem_1fr] gap-x-3">
      <span className="grid size-9 place-items-center bg-cobalt-tint text-cobalt-ink" aria-hidden><Icon name={ev.capability} size={18} /></span>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="font-semibold text-cobalt-ink">{CAPABILITY_LABEL[ev.capability]} specialist</span>
          <span className="inline-flex items-center gap-1.5 text-muted"><span className={`grid size-5 place-items-center text-sm font-semibold ${by.tint} ${by.text}`} aria-hidden>{by.label[0]}</span>Asked by {by.label}</span>
        </header>
        <p className="mt-1.5 text-lg leading-snug [text-wrap:pretty]">{ev.summary}</p>
      </div>
    </article>
  );
}

function Pending({ children }: { children: React.ReactNode }) {
  return <p className="rise flex items-center gap-2.5 text-base text-muted" role="status"><span className="typing flex gap-1"><span /><span /><span /></span>{children}</p>;
}

export function Thread({ state, onOpen, children }: { state: CaseState; onOpen: Open; children?: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const blocks = toBlocks(state);
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const waiting = finished ? [] : (lastRound?.active ?? []).filter((a) => lastRound?.posts[a] === undefined).slice(0, 1);  // one speaks at a time
  const key = `${blocks.length}:${waiting.join()}:${finished}`;

  // Newest at the bottom, verdict last. Stay glued to the bottom while the reader is there; stop when they scroll up.
  useEffect(() => { const el = ref.current; if (el && pinned) el.scrollTop = el.scrollHeight; }, [key, pinned]);
  const onScroll = () => { const el = ref.current; if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 96); };

  return (
    <div ref={ref} onScroll={onScroll} className="relative h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[720px] flex-col gap-5 px-6 py-5">
        {blocks.map((b, i) => b.kind === "post" ? <Message key={i} post={b.post} state={state} onOpen={onOpen} />
          : b.kind === "result" ? <Result key={i} id={b.id} state={state} />
          : <p key={i} className="rise bg-red-tint px-4 py-2 text-red">Seller removed the listing{b.relisted_as ? ` · relisted as ${b.relisted_as}` : ""}. The review continues from the saved snapshot.</p>)}
        {blocks.length === 0 && !finished && <Pending>The agents are reading the evidence</Pending>}
        {waiting.map((a) => <Pending key={a}>{AGENTS[a].label} is thinking</Pending>)}
        {children}
      </div>
      {!pinned && <div className="pointer-events-none sticky bottom-4 flex justify-center"><button onClick={() => { setPinned(true); ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" }); }} className="press pointer-events-auto min-h-11 rounded-none bg-ink px-4 text-base font-semibold text-surface shadow-[var(--shadow)]">↓ Newest</button></div>}
    </div>
  );
}
