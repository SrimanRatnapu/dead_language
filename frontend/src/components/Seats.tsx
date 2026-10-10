"use client";
import { AGENT_ORDER, AGENTS, STANCE_LABEL, STANCE_STYLE } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { AgentName, Stance, StancePost } from "@/lib/types";

export function StancePill({ stance, className = "" }: { stance: Stance; className?: string }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[0.75rem] font-semibold ${STANCE_STYLE[stance]} ${className}`}>{STANCE_LABEL[stance]}</span>;
}

const DOT: Record<Stance, string> = { file: "bg-cobalt", dismiss: "bg-green", need_more: "bg-line" };

// "All three: File" / "2 File · 1 Dismiss" - the one line a judge reads before anything else.
function readout(latest: StancePost[]): string {
  if (latest.length === 0) return "Waiting for the first positions";
  const counts = new Map<Stance, number>();
  latest.forEach((p) => counts.set(p.stance, (counts.get(p.stance) ?? 0) + 1));
  if (counts.size === 1 && latest.length === 3) return `All three: ${STANCE_LABEL[latest[0].stance]}`;
  return [...counts].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${STANCE_LABEL[s]}`).join(" · ");
}

export function Seats({ state }: { state: CaseState }) {
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const history = (agent: AgentName) => state.rounds.flatMap((r) => (r.posts[agent] ? [r.posts[agent]] : []));
  const latest = AGENT_ORDER.flatMap((a) => history(a).at(-1) ?? []);
  return (
    <div className="px-5 pt-4 pb-5 sm:px-8">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="rule-label">{lastRound ? `Round ${lastRound.round}` : "Positions"}</h2>
        <p className="text-[0.82rem] font-medium" aria-live="polite">{readout(latest)}</p>
      </div>
      <div className="grid grid-cols-3 gap-px bg-line">
        {AGENT_ORDER.map((agent) => {
          const a = AGENTS[agent];
          const posts = history(agent);
          const now = posts.at(-1);
          const thinking = !finished && !!lastRound?.active.includes(agent) && lastRound.posts[agent] === undefined;
          return (
            <div key={agent} title={a.goal} className="bg-surface px-3 py-3 sm:px-4">
              <div className="flex items-center justify-between gap-2">
                <span className={`truncate text-sm font-semibold ${a.text}`}>{a.label}</span>
                <span className="flex gap-1" aria-hidden>{posts.map((p) => <i key={p.round} className={`size-1.5 rounded-full ${DOT[p.stance]}`} />)}</span>
              </div>
              <div className="mt-2 flex h-6 items-center gap-2">
                {thinking ? <span className="typing flex gap-1 text-muted" role="status" aria-label={`${a.label} is reviewing`}><span /><span /><span /></span>
                  : now ? <><StancePill stance={now.stance} /><span className="mono text-muted">{Math.round(now.confidence * 100)}%</span></>
                  : <span className="text-muted">Not yet</span>}
              </div>
              <div className="mt-2.5 h-1 bg-sunken" aria-hidden>
                <div className="h-full origin-left transition-[width] duration-500 ease-out" style={{ width: `${(now?.confidence ?? 0) * 100}%`, background: a.cssVar }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
