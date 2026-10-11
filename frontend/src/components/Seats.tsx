"use client";
import { AGENT_ORDER, AGENTS, STANCE_LABEL, STANCE_STYLE } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { AgentName, Stance, StancePost } from "@/lib/types";

export function StancePill({ stance, className = "" }: { stance: Stance; className?: string }) {
  return <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-base font-semibold ${STANCE_STYLE[stance]} ${className}`}>{STANCE_LABEL[stance]}</span>;
}

function readout(latest: StancePost[]): string {
  if (latest.length === 0) return "Nobody has spoken yet";
  const counts = new Map<Stance, number>();
  latest.forEach((p) => counts.set(p.stance, (counts.get(p.stance) ?? 0) + 1));
  if (counts.size === 1 && latest.length === 3) return `All three say ${STANCE_LABEL[latest[0].stance].toLowerCase()}`;
  return [...counts].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${STANCE_LABEL[s].toLowerCase()}`).join(" · ");
}

const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

// Three agents side by side. The one line underneath says, in words, who is reacting to whom.
export function Seats({ state }: { state: CaseState }) {
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const history = (agent: AgentName) => state.rounds.flatMap((r) => (r.posts[agent] ? [r.posts[agent]] : []));
  const latest = AGENT_ORDER.flatMap((a) => history(a).at(-1) ?? []);
  const order = lastRound?.active ?? [];
  const thinking = finished ? null : order.find((a) => lastRound?.posts[a] === undefined) ?? null;
  const reading = thinking ? order.slice(0, order.indexOf(thinking)).at(-1) ?? null : null;
  const lastPost = state.feed.findLast((f) => f.kind === "post");
  const p = lastPost && lastPost.kind === "post" ? lastPost.post : null;
  const who = (n: AgentName) => <b className={AGENTS[n].text}>{AGENTS[n].label}</b>;

  let note: React.ReactNode = "";
  if (thinking) note = reading ? <>{who(thinking)} is reading what {who(reading)} said.</> : <>{who(thinking)} is reading the evidence.</>;
    else if (p?.challenge) note = <>{who(p.agent)} asked {who(p.challenge.target_agent)}: “{cut(p.challenge.question, 70)}”</>;
  else if (p?.rebuttal) note = <>{who(p.agent)} answered {who(p.rebuttal.target_agent)}.</>;

  return (
    <div className="px-4 py-3 sm:px-6">
      <div className="grid grid-cols-3 gap-2">
        {AGENT_ORDER.map((agent) => {
          const a = AGENTS[agent];
          const now = history(agent).at(-1);
          const busy = thinking === agent;
          return (
            <div key={agent} title={a.goal} className={`relative border bg-surface px-2 py-2 transition-colors sm:px-3 duration-300 ${busy ? "border-ink" : "border-line"}`}>
              <div className="flex min-w-0 items-center gap-2.5"><span className={`grid size-8 shrink-0 place-items-center rounded-full font-semibold ${a.tint} ${a.text}`}>{a.label[0]}</span>
              <div className="min-w-0"><p className={`truncate font-semibold leading-tight ${a.text}`}>{a.label}</p>
              <div className="mt-0.5 flex min-h-6 flex-wrap items-center gap-x-2">
                {busy ? <span className="typing flex gap-1 text-muted" role="status" aria-label={`${a.label} is thinking`}><span /><span /><span /></span>
                  : now ? <><StancePill stance={now.stance} /><span className="mono text-muted">{Math.round(now.confidence * 100)}%</span></>
                  : <span className="text-muted">listening</span>}
              </div></div></div>
            </div>
          );
        })}
      </div>
      <p key={state.feed.length} className="rise mt-2 text-base font-medium empty:hidden text-ink [text-wrap:pretty]" aria-live="polite">{note}</p>
    </div>
  );
}
