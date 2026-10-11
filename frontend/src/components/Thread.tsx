"use client";
import { useEffect, useRef, useState } from "react";
import { AGENTS, CAPABILITY_LABEL, prettyName } from "@/lib/agents";
import type { CaseState, Failure, Selection } from "@/lib/caseState";
import type { AgentName, Capability, Evidence, Stance, StancePost } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { Icon } from "./Icon";
import { StancePill } from "./Seats";

type Open = (id: string) => void;
type Row = { kind: "evidence"; evidence: Evidence } | { kind: "failed"; failure: Failure } | { kind: "route"; selection: Selection };
type Wake = { kind: "start" } | { kind: "heard"; by: AgentName[] } | { kind: "asked"; by: AgentName } | { kind: "rebutted"; by: AgentName } | { kind: "evidence"; caps: Capability[] };
type Block =
  | { kind: "facts"; rows: Row[] }
  | { kind: "post"; post: StancePost; prev: Stance | null; wake: Wake[] }
  | { kind: "removed"; relisted_as: string | null };

// The feed is arrival order. Fold consecutive fact-finding into one block, and remember each agent's earlier stance.
function toBlocks(state: CaseState): Block[] {
  const blocks: Block[] = [];
  const last = new Map<AgentName, Stance>();
  // What has landed since each agent last spoke: this is what wakes them, there is no turn order.
  const pending = new Map<AgentName, Wake[]>();
  const wakeFor = (a: AgentName) => pending.get(a) ?? [];
  const evidenceSince = new Map<AgentName, Capability[]>();
  for (const item of state.feed) {
    const tail = blocks.at(-1);
    const fact: Row | null = item.kind === "evidence" && state.evidence[item.id]?.capability !== "listing_snapshot" ? { kind: "evidence", evidence: state.evidence[item.id] }
      : item.kind === "failed" ? { kind: "failed", failure: item.failure }
      : item.kind === "selected" ? { kind: "route", selection: item.selection } : null;
    if (item.kind === "evidence" && state.evidence[item.id]) { for (const ag of Object.keys(AGENTS) as AgentName[]) evidenceSince.set(ag, [...(evidenceSince.get(ag) ?? []), state.evidence[item.id].capability]); }
    if (fact) {
      if (tail?.kind === "facts") tail.rows.push(fact); else blocks.push({ kind: "facts", rows: [fact] });
    } else if (item.kind === "post") {
      const p = item.post;
      const wake: Wake[] = [...wakeFor(p.agent)];
      const caps = [...new Set(evidenceSince.get(p.agent) ?? [])];
      const heard = blocks.flatMap((x) => (x.kind === "post" && x.post.round === p.round ? [x.post.agent] : []));
      if (heard.length) wake.unshift({ kind: "heard", by: heard });
      else if (!last.has(p.agent)) wake.unshift({ kind: "start" });
      else if (caps.length) wake.push({ kind: "evidence", caps });
      blocks.push({ kind: "post", post: p, prev: last.get(p.agent) ?? null, wake });
      last.set(p.agent, p.stance);
      pending.delete(p.agent);
      evidenceSince.set(p.agent, []);
      if (p.challenge) pending.set(p.challenge.target_agent, [...wakeFor(p.challenge.target_agent), { kind: "asked", by: p.agent }]);
      if (p.rebuttal) pending.set(p.rebuttal.target_agent, [...wakeFor(p.rebuttal.target_agent), { kind: "rebutted", by: p.agent }]);
    } else if (item.kind === "removed") {
      blocks.push({ kind: "removed", relisted_as: item.relisted_as });
    }
  }
  return blocks;
}

function WakeLine({ wake }: { wake: Wake[] }) {
  if (wake.length === 0) return null;
  const who = (a: AgentName) => <b className={AGENTS[a].text}>{AGENTS[a].label}</b>;
  const parts = wake.map((w, i) => w.kind === "start" ? <span key={i}>first look at the case</span>
    : w.kind === "heard" ? <span key={i}>read {w.by.map((a, j) => <span key={a}>{j > 0 && " and "}{who(a)}</span>)} first</span>
    : w.kind === "asked" ? <span key={i}>was asked a question by {who(w.by)}</span>
    : w.kind === "rebutted" ? <span key={i}>was pushed back on by {who(w.by)}</span>
    : <span key={i}>new {w.caps.map((c) => CAPABILITY_LABEL[c].toLowerCase()).join(" + ")} on the board</span>);
  return <p className="mb-2 flex flex-wrap items-center gap-x-1.5 text-sm text-muted">{parts.map((n, i) => <span key={i}>{i > 0 && " · "}{n}</span>)}</p>;
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
      <summary className="press flex min-h-11 cursor-pointer list-none items-center gap-3 py-2 text-base text-muted hover:text-ink">
        <span className="rotate-0 transition-transform duration-200 group-open:rotate-90"><Icon name="chevron" size={14} /></span>
        <span className="font-medium text-ink">{asked ? <><span className={asked.text}>{asked.label}</span> asked for {CAPABILITY_LABEL[caps[0]]?.toLowerCase() ?? "evidence"}</> : "Fact-finding"}</span>
                <span className="ml-auto flex gap-1.5 group-open:hidden" aria-hidden>{caps.map((c) => <Icon key={c} name={c} size={14} />)}</span>
      </summary>
      <ul className="pb-2">
        {rows.map((row, i) => row.kind === "route"
          ? <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-3 pb-1 text-base text-muted" title={row.selection.why}>
                            <span>{CAPABILITY_LABEL[row.selection.capability]}</span><span aria-hidden>→</span>
              <span className="font-semibold text-ink">{prettyName(row.selection.specialist_name)}</span>
            </li>
          : row.kind === "failed"
          ? <li key={i} className="py-1 text-base font-medium text-red">✕ {prettyName(row.failure.specialist_name)} did not respond{row.failure.fallback ? <> · switching to <b>{prettyName(row.failure.fallback)}</b></> : " · no backup available"}</li>
          : <li key={row.evidence.id}>
              <button onClick={() => onOpen(row.evidence.id)} className="press grid min-h-11 w-full grid-cols-[1.25rem_6.5rem_1fr] items-start gap-3 py-2 text-left hover:bg-cobalt-tint/60">
                <Icon name={row.evidence.capability} size={16} className="mt-0.5 text-cobalt-ink" />
                <span className="truncate text-base font-semibold">{CAPABILITY_LABEL[row.evidence.capability]}</span>
                <span className="line-clamp-2 text-base leading-snug">{row.evidence.summary}{row.evidence.produced_by === "model" && <span className="mono ml-2 text-muted">AI{row.evidence.confidence !== null ? ` · ${Math.round(row.evidence.confidence * 100)}%` : ""}</span>}</span>
              </button>
            </li>)}
      </ul>
    </details>
  );
}

function Message({ post, prev, wake, state, onOpen }: { post: StancePost; prev: Stance | null; wake: Wake[]; state: CaseState; onOpen: Open }) {
  const a = AGENTS[post.agent];
  const rejected = state.rounds.find((r) => r.round === post.round)?.rejected.filter((r) => r.agent === post.agent) ?? [];
  // New posts carry an in-character `take`; older recordings fall back to the first claim as the headline.
  const head = post.take ? undefined : post.claims[0];
  const rest = post.take ? post.claims : post.claims.slice(1);
  const detail = rest.length + (post.rebuttal ? 1 : 0) + (rejected.length ? 1 : 0);
  return (
    <article className={`rise relative border border-line bg-surface/80 px-4 py-3.5 ${prev && prev !== post.stance ? "flash" : ""}`} style={{ boxShadow: `inset 3px 0 0 ${a.cssVar}` }}>
      <WakeLine wake={wake} />
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className={`text-sm font-semibold ${a.text}`}>{a.label}</span>
        {prev && prev !== post.stance && <><StancePill stance={prev} className="opacity-60" /><span className="text-muted" aria-label="changed to">→</span></>}
        <StancePill stance={post.stance} />
        <span className="mono text-muted">{Math.round(post.confidence * 100)}%</span>
        {post.ready_to_close && <span className="mono text-muted">· ready to close</span>}
      </header>
      {post.changed_because && <p className="mt-2.5 border-l-2 border-amber bg-amber-tint px-3 py-2 text-base leading-snug"><span className="font-semibold">Changed my mind: </span>{post.changed_because}</p>}
      {(post.take || head) && <p className="mt-2.5 text-base leading-snug [text-wrap:pretty]">{post.take || head?.text}</p>}
      {post.challenge && <p className="mt-2.5 text-base leading-snug"><span className={`font-semibold ${AGENTS[post.challenge.target_agent].text}`}>Asks {AGENTS[post.challenge.target_agent].label}: </span>{post.challenge.question}</p>}
      {post.requests.length > 0 && <p className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-base text-cobalt-ink">{post.requests.map((r, i) => <span key={i} className="inline-flex items-center gap-1.5"><Icon name={r.capability} size={14} />Asked for {CAPABILITY_LABEL[r.capability].toLowerCase()}</span>)}</p>}
      {detail > 0 && <details className="group mt-2.5 border-t border-line pt-1">
        <summary className="press flex min-h-9 cursor-pointer list-none items-center gap-2 text-base text-muted hover:text-ink"><span className="transition-transform duration-200 group-open:rotate-90"><Icon name="chevron" size={14} /></span>Reasoning and evidence{rejected.length > 0 && <span className="text-red"> · {rejected.length} removed</span>}</summary>
        <div className="space-y-2.5 pb-1 pt-1.5 text-base leading-snug">
          {post.changed_because && <p className="text-muted">Changed because<Chips ids={post.changed_because_evidence} state={state} onOpen={onOpen} /></p>}
                    {post.rebuttal && <p className="text-muted"><span className={`font-semibold ${AGENTS[post.rebuttal.target_agent].text}`}>↩ {AGENTS[post.rebuttal.target_agent].label}: </span>{post.rebuttal.response}<Chips ids={post.rebuttal.evidence_ids} state={state} onOpen={onOpen} /></p>}
          {rest.length > 0 && <ul className="space-y-2">{rest.map((c, i) => <li key={i}>{c.text}<Chips ids={c.evidence_ids} state={state} onOpen={onOpen} /></li>)}</ul>}
          {rejected.length > 0 && <ul className="space-y-1.5 text-red">{rejected.map((r, i) => <li key={i}><s>{r.claim_text}</s><br /><span className="text-muted">Removed by the checker: {r.reasons.join(" · ")}</span></li>)}</ul>}
        </div>
      </details>}
    </article>
  );
}

function Pending({ children }: { children: React.ReactNode }) {
  return <p className="rise flex items-center gap-2.5 text-base text-muted" role="status"><span className="typing flex gap-1"><span /><span /><span /></span>{children}</p>;
}

export function Thread({ state, onOpen }: { state: CaseState; onOpen: Open }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const blocks = toBlocks(state);
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const waiting = finished ? [] : (lastRound?.active ?? []).filter((a) => lastRound?.posts[a] === undefined).slice(0, 1);  // one speaks at a time
  const key = `${blocks.length}:${waiting.join()}`;

  // Newest first. Stay glued to the top while the reader is there; stop when they scroll down.
  useEffect(() => { const el = ref.current; if (el && pinned) el.scrollTop = 0; }, [key, pinned]);
  const onScroll = () => { const el = ref.current; if (el) setPinned(el.scrollTop < 96); };
  const lastPost = blocks.findLastIndex((b) => b.kind === "post");
  const shown = blocks.map((b, i) => ({ b, i })).reverse();

  return (
    <div ref={ref} onScroll={onScroll} className="relative lg:h-full lg:overflow-y-auto">
      <div className="mx-auto flex max-w-[760px] flex-col gap-4 px-5 py-6 sm:px-8">
        {waiting.map((a) => <Pending key={a}>{AGENTS[a].label} is writing a reply</Pending>)}
        {shown.map(({ b, i }) => b.kind === "facts" ? <Facts key={i} rows={b.rows} open={i > lastPost || b.rows.length <= 2} onOpen={onOpen} />
          : b.kind === "post" ? <Message key={i} post={b.post} prev={b.prev} wake={b.wake} state={state} onOpen={onOpen} />
          : <p key={i} className="rise border-l-2 border-red pl-4 text-base text-red">Seller removed the listing{b.relisted_as ? ` · relisted as ${b.relisted_as}` : ""}. The review continues from the saved snapshot.</p>)}
        {blocks.length === 0 && !finished && <Pending>Gathering facts</Pending>}
      </div>
      {!pinned && <div className="pointer-events-none sticky bottom-4 flex justify-center"><button onClick={() => { setPinned(true); ref.current?.scrollTo({ top: 0, behavior: "smooth" }); }} className="press pointer-events-auto min-h-11 rounded-full bg-ink px-4 text-base font-semibold text-surface shadow-[var(--shadow)]">↑ Newest</button></div>}
    </div>
  );
}
