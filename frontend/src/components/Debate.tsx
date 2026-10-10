"use client";
import { useEffect, useRef } from "react";
import { AGENTS, CAPABILITY_LABEL, STANCE_LABEL, prettyName } from "@/lib/agents";
import type { CaseState, FeedItem } from "@/lib/caseState";
import type { AgentName, Evidence } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { Icon } from "./Icon";

type Open = (id: string) => void;

function Avatar({ agent }: { agent: AgentName }) {
  const a = AGENTS[agent];
  return <span className={`flex size-8 shrink-0 items-center justify-center rounded-full font-semibold ${a.tint} ${a.text}`} aria-hidden>{a.label[0]}</span>;
}

const lower = (s: string) => s.replace(/^./, (c) => c.toLowerCase());

function Chips({ ids, state, onOpen }: { ids: string[]; state: CaseState; onOpen: Open }) {
  return <span className="ml-1.5 inline-flex flex-wrap gap-1">{ids.map((id) => <EvidenceChip key={id} evidence={state.evidence[id]} onOpen={onOpen} />)}</span>;
}

function Post({ item, state, onOpen }: { item: Extract<FeedItem, { kind: "post" }>; state: CaseState; onOpen: Open }) {
  const { post } = item;
  const a = AGENTS[post.agent];
  return (
    <div className="rise flex gap-3">
      <Avatar agent={post.agent} />
      <div className="min-w-0 flex-1">
        <p className="mb-1">
          <span className={`font-semibold ${a.text}`}>{a.label}</span>
          <span className="text-muted"> says {STANCE_LABEL[post.stance].toLowerCase()} · {Math.round(post.confidence * 100)}% sure{post.ready_to_close ? " · nothing more to add" : ""}</span>
        </p>
        <div className="flex flex-col gap-2.5 rounded-2xl rounded-tl-md border border-line bg-surface p-3.5 text-[0.95rem] leading-relaxed">
          {post.changed_because && (
            <p className={`rounded-lg px-3 py-2 font-medium ${a.tint} ${a.text}`}>
              Changed their mind because {lower(post.changed_because)}
              <Chips ids={post.changed_because_evidence} state={state} onOpen={onOpen} />
            </p>
          )}
          {post.claims.map((c, i) => <p key={i}>{c.text}<Chips ids={c.evidence_ids} state={state} onOpen={onOpen} /></p>)}
          {post.rebuttal && (
            <p className="text-muted">
              To {AGENTS[post.rebuttal.target_agent].label}: <span className="text-ink">{post.rebuttal.response}</span>
              <Chips ids={post.rebuttal.evidence_ids} state={state} onOpen={onOpen} />
            </p>
          )}
          {post.challenge && <p className="text-muted">Asks {AGENTS[post.challenge.target_agent].label}: <span className="text-ink">{post.challenge.question}</span></p>}
          {post.requests.map((r, i) => (
            <p key={i} className="flex items-start gap-1.5 text-muted">
              <Icon name={r.capability} size={14} className="mt-1 shrink-0" />
              <span>Wants a {CAPABILITY_LABEL[r.capability].toLowerCase()}: {lower(r.question)}</span>
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

function Finding({ ev, onOpen }: { ev: Evidence; onOpen: Open }) {
  return (
    <button onClick={() => onOpen(ev.id)} className="rise press ml-11 flex items-start gap-2.5 rounded-xl border border-dashed border-line px-3 py-2 text-left hover:border-ink">
      <Icon name={ev.capability} className="mt-0.5 shrink-0 text-muted" />
      <span>
        <span className="block">{ev.summary}</span>
        <span className="text-muted">
          {CAPABILITY_LABEL[ev.capability]} · {ev.produced_by === "code" ? "checked by code" : `AI reading, ${Math.round((ev.confidence ?? 0) * 100)}% sure`}
        </span>
      </span>
    </button>
  );
}

function Note({ children, tone = "plain" }: { children: React.ReactNode; tone?: "plain" | "bad" }) {
  return (
    <p className={`rise mx-auto max-w-[52ch] rounded-full px-4 py-1 text-center text-muted ${tone === "bad" ? "bg-red-tint text-red" : "bg-sunken"}`}>{children}</p>
  );
}

const clean = (s: string) => s.replaceAll("deadlang-", "");

function Item({ item, state, onOpen }: { item: FeedItem; state: CaseState; onOpen: Open }) {
  switch (item.kind) {
    case "round":
      return item.round === 1 ? null : <h3 className="rise display pt-3 text-center text-xl italic text-muted">Round {item.round}</h3>;
    case "evidence": {
      const ev = state.evidence[item.id];
      return ev.capability === "listing_snapshot" ? null : <Finding ev={ev} onOpen={onOpen} />;
    }
    case "selected":
      return <Note>{CAPABILITY_LABEL[item.selection.capability]}: {clean(item.selection.why)}</Note>;
    case "failed":
      return (
        <Note tone="bad">
          {prettyName(item.failure.specialist_name)} stopped responding ({item.failure.error}).{" "}
          {item.failure.fallback ? `Switched to ${prettyName(item.failure.fallback)}.` : "No fallback available."}
        </Note>
      );
    case "post":
      return <Post item={item} state={state} onOpen={onOpen} />;
    case "rejected":
      return (
        <div className="rise ml-11 rounded-xl bg-red-tint px-3 py-2 text-red">
          <span className="font-semibold">{AGENTS[item.agent].label}&rsquo;s claim was rejected: </span>
          <s>{item.claim_text}</s>
          <span className="block">{item.reasons.join("; ")}</span>
        </div>
      );
    case "removed":
      return <Note tone="bad">The seller removed this listing.{item.relisted_as ? " It has already reappeared under a new account." : ""}</Note>;
  }
}

export function Debate({ state, onOpen }: { state: CaseState; onOpen: Open }) {
  const end = useRef<HTMLDivElement>(null);
  const stuck = useRef(true);
  const last = state.rounds.at(-1);
  const composing = state.caseFile || !last ? [] : last.active.filter((ag) => !last.posts[ag]);

  // Follow the conversation unless the viewer scrolled up to read.
  useEffect(() => {
    if (stuck.current) end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [state.feed.length, composing.length, state.caseFile]);

  return (
    <div
      className="h-full overflow-y-auto"
      onScroll={(e) => {
        const el = e.currentTarget;
        stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
    >
      <div className="mx-auto flex max-w-[680px] flex-col gap-4 px-6 py-6">
        {state.feed.length === 0 && <p className="text-center text-muted">Gathering the first findings…</p>}
        {state.feed.map((item, i) => <Item key={i} item={item} state={state} onOpen={onOpen} />)}
        {composing.map((ag) => (
          <div key={ag} className="rise flex items-center gap-3">
            <Avatar agent={ag} />
            <span className={`typing flex gap-1 rounded-2xl border border-line bg-surface px-4 py-3 ${AGENTS[ag].text}`} role="status" aria-label={`${AGENTS[ag].label} is writing`}>
              <span /><span /><span />
            </span>
          </div>
        ))}
        <div ref={end} />
      </div>
    </div>
  );
}
