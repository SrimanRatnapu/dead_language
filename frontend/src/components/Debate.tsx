"use client";
import { AGENT_ORDER, AGENTS, CAPABILITY_LABEL, STANCE_LABEL } from "@/lib/agents";
import type { CaseState, Failure, Round, Selection } from "@/lib/caseState";
import type { AgentName, Evidence, StancePost } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { Icon } from "./Icon";

type Open = (id: string) => void;
function Chips({ ids, state, onOpen }: { ids: string[]; state: CaseState; onOpen: Open }) {
  return <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">{ids.map((id) => <EvidenceChip key={id} evidence={state.evidence[id]} onOpen={onOpen} />)}</span>;
}
function EvidenceTile({ evidence, onOpen }: { evidence: Evidence; onOpen: Open }) {
  return <button onClick={() => onOpen(evidence.id)} className="evidence-tile press text-left">
    <span className="flex items-center justify-between gap-3"><span className="mono text-cobalt-ink">{evidence.id} · {CAPABILITY_LABEL[evidence.capability]}</span>{evidence.confidence !== null && <span className="mono text-muted">{Math.round(evidence.confidence * 100)}%</span>}</span>
    <span className="mt-2 block leading-snug">{evidence.summary}</span>
  </button>;
}
function Position({ agent, post, state, onOpen }: { agent: AgentName; post: StancePost | undefined; state: CaseState; onOpen: Open }) {
  const agentMeta = AGENTS[agent];
  if (!post) return <article className="position-empty"><span className={`font-semibold ${agentMeta.text}`}>{agentMeta.label}</span><span>Awaiting evidence</span></article>;
  return <article className="position-card" style={{ "--agent": agentMeta.cssVar } as React.CSSProperties}>
    <header className="flex items-center justify-between gap-3">
      <span className={`font-semibold ${agentMeta.text}`}>{agentMeta.label}</span>
      <span className="mono text-muted">{STANCE_LABEL[post.stance]} · {Math.round(post.confidence * 100)}%</span>
    </header>
    <div className="mt-4 space-y-3">
      {post.claims.map((claim, index) => <p key={index} className="leading-relaxed">{claim.text}<Chips ids={claim.evidence_ids} state={state} onOpen={onOpen} /></p>)}
      {post.changed_because && <p className="position-detail">Changed: {post.changed_because}<Chips ids={post.changed_because_evidence} state={state} onOpen={onOpen} /></p>}
      {post.rebuttal && <p className="position-detail">To {AGENTS[post.rebuttal.target_agent].label}: {post.rebuttal.response}<Chips ids={post.rebuttal.evidence_ids} state={state} onOpen={onOpen} /></p>}
      {post.challenge && <p className="position-detail">Asks {AGENTS[post.challenge.target_agent].label}: {post.challenge.question}</p>}
      {post.requests.map((request, index) => <p key={index} className="position-request"><Icon name={request.capability} size={14} />Requesting {CAPABILITY_LABEL[request.capability].toLowerCase()}</p>)}
    </div>
  </article>;
}
function RoundView({ round, state, onOpen }: { round: Round; state: CaseState; onOpen: Open }) {
  return <section className="deliberation-round">
    <div className="round-line"><span>Round {round.round}</span><i /></div>
    <div className="grid gap-3 md:grid-cols-3">{AGENT_ORDER.map((agent) => <Position key={agent} agent={agent} post={round.posts[agent]} state={state} onOpen={onOpen} />)}</div>
  </section>;
}
function ProcessNote({ selection }: { selection: Selection }) {
  return <span className="process-note"><Icon name={selection.capability} size={14} />{selection.why}</span>;
}
function FailureNote({ failure }: { failure: Failure }) {
  return <span className="process-note process-note--failure">{CAPABILITY_LABEL[failure.capability]} unavailable{failure.fallback ? ` · trying ${failure.fallback.replace("deadlang-", "")}` : ""}</span>;
}
export function Debate({ state, onOpen }: { state: CaseState; onOpen: Open }) {
  const evidence = state.evidenceOrder.map((id) => state.evidence[id]).filter((item): item is Evidence => Boolean(item) && item.capability !== "listing_snapshot");
  const active = state.caseFile ? [] : state.rounds.at(-1)?.active ?? [];
  const rejected = state.rounds.flatMap((round) => round.rejected);
  return <div className="h-full overflow-y-auto"><div className="mx-auto flex max-w-[1040px] flex-col gap-8 px-5 py-6 sm:px-8">
    <section aria-label="Evidence board">
      <div className="evidence-heading"><h2 className="display text-3xl">Evidence board</h2><span>{evidence.length} findings</span></div>
      {evidence.length ? <div className="evidence-field">{evidence.map((item) => <EvidenceTile key={item.id} evidence={item} onOpen={onOpen} />)}</div> : <p className="text-muted">Building the evidence board.</p>}
    </section>
    {(state.selections.length > 0 || state.failures.length > 0 || state.removed) && <div className="process-strip" aria-label="Process updates">{state.selections.map((selection, index) => <ProcessNote key={`${selection.capability}-${index}`} selection={selection} />)}{state.failures.map((failure, index) => <FailureNote key={`${failure.capability}-${index}`} failure={failure} />)}{state.removed && <span className="process-note process-note--failure">Listing removed{state.removed.relisted_as ? ` · relisted as ${state.removed.relisted_as}` : ""}</span>}</div>}
    <section aria-label="Agent positions">
      <div className="evidence-heading"><h2 className="display text-3xl">Positions</h2>{active.length > 0 && <span className="typing text-cobalt-ink" role="status">{active.map((agent) => AGENTS[agent].label).join(" · ")} reviewing</span>}</div>
      {state.rounds.length ? <div className="space-y-7">{state.rounds.map((round) => <RoundView key={round.round} round={round} state={state} onOpen={onOpen} />)}</div> : <p className="text-muted">The agents will speak after intake completes.</p>}
      {rejected.length > 0 && <div className="mt-5 space-y-2">{rejected.map((item, index) => <p key={index} className="excluded-claim">Excluded claim: <s>{item.claim_text}</s></p>)}</div>}
    </section>
  </div></div>;
}
