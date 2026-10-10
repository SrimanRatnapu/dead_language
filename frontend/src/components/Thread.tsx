"use client";
import { useEffect, useRef, useState } from "react";
import { AGENTS, CAPABILITY_LABEL, prettyName } from "@/lib/agents";
import type { CaseState, Failure, Selection } from "@/lib/caseState";
import type { AgentName, Evidence, Stance, StancePost } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { Icon } from "./Icon";
import { StancePill } from "./Seats";

type Open = (id: string) => void;
type Row = { kind: "evidence"; evidence: Evidence } | { kind: "failed"; failure: Failure } | { kind: "route"; selection: Selection };
type Block =
  | { kind: "facts"; rows: Row[] }
  | { kind: "round"; round: number; active: AgentName[] }
  | { kind: "post"; post: StancePost; prev: Stance | null }
  | { kind: "removed"; relisted_as: string | null };

// The feed is arrival order. Fold consecutive fact-finding into one block, and remember each agent's earlier stance.
function toBlocks(state: CaseState): Block[] {
  const blocks: Block[] = [];
  const last = new Map<AgentName, Stance>();
  for (const item of state.feed) {
    const tail = blocks.at(-1);
    const fact: Row | null = item.kind === "evidence" && state.evidence[item.id]?.capability !== "listing_snapshot" ? { kind: "evidence", evidence: state.evidence[item.id] }
      : item.kind === "failed" ? { kind: "failed", failure: item.failure }
      : item.kind === "selected" ? { kind: "route", selection: item.selection } : null;
    if (fact) {
      if (tail?.kind === "facts") tail.rows.push(fact); else blocks.push({ kind: "facts", rows: [fact] });
    } else if (item.kind === "round") {
      blocks.push({ kind: "round", round: item.round, active: state.rounds.find((r) => r.round === item.round)?.active ?? [] });
    } else if (item.kind === "post") {
      blocks.push({ kind: "post", post: item.post, prev: last.get(item.post.agent) ?? null });
      last.set(item.post.agent, item.post.stance);
    } else if (item.kind === "removed") {
      blocks.push({ kind: "removed", relisted_as: item.relisted_as });
    }
  }
  return blocks;
}

function Chips({ ids, state, onOpen }: { ids: string[]; state: CaseState; onOpen: Open }) {
  return <>{ids.map((id) => <span key={id} className="ml-1 inline-block"><EvidenceChip evidence={state.evidence[id]} onOpen={onOpen} /></span>)}</>;
}

function Facts({ rows, open, onOpen }: { rows: Row[]; open: boolean; onOpen: Open }) {
  const first = rows.find((r): r is Extract<Row, { kind: "route" }> => r.kind === "route");
  const by = first?.selection.requested_by;
  const asked = by && by in AGENTS ? AGENTS[by as AgentName] : null;
  const caps = [...new Set(rows.flatMap((r) => (r.kind === "route" ? [r.selection.capability] : [])))];
  const facts = rows.filter((r) => r.kind === "evidence").length;
  return (
    <details open={open} className="group rise border-y border-line">
      <summary className="press flex min-h-11 cursor-pointer list-none items-center gap-3 py-2 text-[0.82rem] text-muted hover:text-ink">
        <span className="rotate-0 transition-transform duration-200 group-open:rotate-90"><Icon name="chevron" size={14} /></span>
        <span className="font-medium text-ink">{asked ? <><span className={asked.text}>{asked.label}</span> asked for {CAPABILITY_LABEL[caps[0]]?.toLowerCase() ?? "evidence"}</> : "Fact-finding"}</span>
        <span className="mono">{caps.length} {caps.length === 1 ? "lookup" : "lookups"} · {facts} {facts === 1 ? "fact" : "facts"}</span>
        <span className="ml-auto flex gap-1.5 group-open:hidden" aria-hidden>{caps.map((c) => <Icon key={c} name={c} size={14} />)}</span>
      </summary>
      <ul className="pb-2">
        {rows.map((row, i) => row.kind === "route"
          ? <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-3 pb-1 text-[0.8rem] text-muted" title={row.selection.why}>
              <span className="rule-label">Helper found</span>
              <span>{CAPABILITY_LABEL[row.selection.capability]}</span><span aria-hidden>→</span>
              <span className="font-semibold text-ink">{prettyName(row.selection.specialist_name)}</span>
              <span className="mono">{row.selection.candidates.length > 1 ? `best of ${row.selection.candidates.length}: ${row.selection.candidates.map(prettyName).join(" / ")}` : "only match"}</span>
            </li>
          : row.kind === "failed"
          ? <li key={i} className="py-1 text-[0.8rem] font-medium text-red">✕ {prettyName(row.failure.specialist_name)} did not respond{row.failure.fallback ? <> · switching to <b>{prettyName(row.failure.fallback)}</b></> : " · no backup available"}</li>
          : <li key={row.evidence.id}>
              <button onClick={() => onOpen(row.evidence.id)} className="press grid min-h-11 w-full grid-cols-[1.25rem_6.5rem_1fr] items-start gap-3 py-2 text-left hover:bg-cobalt-tint/60">
                <Icon name={row.evidence.capability} size={16} className="mt-0.5 text-cobalt-ink" />
                <span className="truncate text-[0.82rem] font-semibold">{CAPABILITY_LABEL[row.evidence.capability]}</span>
                <span className="line-clamp-2 text-[0.85rem] leading-snug">{row.evidence.summary}{row.evidence.produced_by === "model" && <span className="mono ml-2 text-muted">AI{row.evidence.confidence !== null ? ` · ${Math.round(row.evidence.confidence * 100)}%` : ""}</span>}</span>
              </button>
            </li>)}
      </ul>
    </details>
  );
}

function Message({ post, prev, state, onOpen }: { post: StancePost; prev: Stance | null; state: CaseState; onOpen: Open }) {
  const a = AGENTS[post.agent];
  const [all, setAll] = useState(false);
  const [showRejected, setShowRejected] = useState(false);
  const rejected = state.rounds.find((r) => r.round === post.round)?.rejected.filter((r) => r.agent === post.agent) ?? [];
  const claims = all ? post.claims : post.claims.slice(0, 2);
  return (
    <article className="rise border-l-2 pl-4" style={{ borderColor: a.cssVar }}>
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className={`text-sm font-semibold ${a.text}`}>{a.label}</span>
        {prev && prev !== post.stance && <><StancePill stance={prev} className="opacity-60" /><span className="text-muted" aria-label="changed to">→</span></>}
        <StancePill stance={post.stance} />
        <span className="mono text-muted">{Math.round(post.confidence * 100)}%</span>
        {post.ready_to_close && <span className="mono text-muted">· ready to close</span>}
      </header>
      {post.changed_because && <p className="mt-2.5 bg-sunken px-3 py-2 text-[0.85rem] leading-snug"><span className="font-semibold">Changed my mind: </span>{post.changed_because}<Chips ids={post.changed_because_evidence} state={state} onOpen={onOpen} /></p>}
      {post.rebuttal && <p className="mt-2.5 text-[0.85rem] leading-snug text-muted"><span className={`font-semibold ${AGENTS[post.rebuttal.target_agent].text}`}>↩ {AGENTS[post.rebuttal.target_agent].label}: </span>{post.rebuttal.response}<Chips ids={post.rebuttal.evidence_ids} state={state} onOpen={onOpen} /></p>}
      {claims.length > 0 && <ul className="mt-2.5 space-y-2">{claims.map((c, i) => <li key={i} className="text-[0.9rem] leading-snug">{c.text}<Chips ids={c.evidence_ids} state={state} onOpen={onOpen} /></li>)}</ul>}
      {post.claims.length > 2 && <button onClick={() => setAll(!all)} className="press mt-1.5 min-h-8 text-[0.8rem] font-medium text-cobalt-ink hover:underline">{all ? "Show less" : `Show ${post.claims.length - 2} more`}</button>}
      {post.challenge && <p className="mt-2.5 text-[0.85rem] leading-snug"><span className={`font-semibold ${AGENTS[post.challenge.target_agent].text}`}>? {AGENTS[post.challenge.target_agent].label}: </span>{post.challenge.question}</p>}
      {post.requests.length > 0 && <p className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.8rem] text-cobalt-ink">{post.requests.map((r, i) => <span key={i} className="inline-flex items-center gap-1.5"><Icon name={r.capability} size={14} />Asked for {CAPABILITY_LABEL[r.capability].toLowerCase()}</span>)}</p>}
      {rejected.length > 0 && <div className="mt-2.5 text-[0.8rem] text-red">
        <button onClick={() => setShowRejected(!showRejected)} className="press min-h-8 text-left font-medium hover:underline" aria-expanded={showRejected}>{rejected.length} {rejected.length === 1 ? "claim" : "claims"} removed by the checker {showRejected ? "▾" : "▸"}</button>
        {showRejected && <ul className="mt-1 space-y-1.5">{rejected.map((r, i) => <li key={i}><s>{r.claim_text}</s><br /><span className="text-muted">{r.reasons.join(" · ")}</span></li>)}</ul>}
      </div>}
    </article>
  );
}

function Pending({ children }: { children: React.ReactNode }) {
  return <p className="rise flex items-center gap-2.5 text-[0.85rem] text-muted" role="status"><span className="typing flex gap-1"><span /><span /><span /></span>{children}</p>;
}

export function Thread({ state, onOpen }: { state: CaseState; onOpen: Open }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const blocks = toBlocks(state);
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const waiting = finished ? [] : (lastRound?.active ?? []).filter((a) => lastRound?.posts[a] === undefined);
  const key = `${blocks.length}:${waiting.join()}`;

  // Follow the stream while the reader is at the bottom; stop the moment they scroll up.
  useEffect(() => { const el = ref.current; if (el && pinned) el.scrollTop = el.scrollHeight; }, [key, pinned]);
  const onScroll = () => { const el = ref.current; if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 96); };
  const lastPost = blocks.findLastIndex((b) => b.kind === "post");

  return (
    <div ref={ref} onScroll={onScroll} className="relative lg:h-full lg:overflow-y-auto">
      <div className="mx-auto flex max-w-[760px] flex-col gap-6 px-5 py-6 sm:px-8">
        {blocks.map((b, i) => b.kind === "facts" ? <Facts key={i} rows={b.rows} open={i > lastPost || b.rows.length <= 2} onOpen={onOpen} />
          : b.kind === "round" ? <div key={i} className="rise mt-2 flex items-center gap-3"><span className="rule-label">Round {b.round}</span><i className="h-px flex-1 bg-line" />{b.active.length > 0 && b.active.length < 3 && <span className="mono text-muted">{b.active.map((a) => AGENTS[a].label).join(" · ")}</span>}</div>
          : b.kind === "post" ? <Message key={i} post={b.post} prev={b.prev} state={state} onOpen={onOpen} />
          : <p key={i} className="rise border-l-2 border-red pl-4 text-[0.85rem] text-red">Seller removed the listing{b.relisted_as ? ` · relisted as ${b.relisted_as}` : ""}. The review continues from the saved snapshot.</p>)}
        {blocks.length === 0 && !finished && <Pending>Gathering facts</Pending>}
        {waiting.map((a) => <Pending key={a}>{AGENTS[a].label} is reviewing</Pending>)}
      </div>
      {!pinned && <div className="pointer-events-none sticky bottom-4 flex justify-center"><button onClick={() => setPinned(true)} className="press pointer-events-auto min-h-11 rounded-full bg-ink px-4 text-[0.82rem] font-semibold text-surface shadow-[var(--shadow)]">↓ Latest</button></div>}
    </div>
  );
}
