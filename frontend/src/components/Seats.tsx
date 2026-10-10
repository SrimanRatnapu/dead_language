"use client";
import { AGENT_ORDER, AGENTS, STANCE_LABEL, STANCE_STYLE } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { AgentName, Stance, StancePost } from "@/lib/types";

export function StancePill({ stance, className = "" }: { stance: Stance; className?: string }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[0.75rem] font-semibold ${STANCE_STYLE[stance]} ${className}`}>{STANCE_LABEL[stance]}</span>;
}

const RING: Record<Stance, string> = { file: "var(--cobalt)", dismiss: "var(--green)", need_more: "var(--line)" };
const CIRC = 2 * Math.PI * 27;
const COL = { buyer: 50, defender: 150, caseload: 250 } as const;

// Every agent-to-agent question or rebuttal so far, oldest first.
function exchanges(state: CaseState) {
  const out: { from: AgentName; to: AgentName; kind: "ask" | "rebut" }[] = [];
  for (const item of state.feed) {
    if (item.kind !== "post") continue;
    const p = item.post;
    if (p.challenge) out.push({ from: p.agent, to: p.challenge.target_agent, kind: "ask" });
    if (p.rebuttal) out.push({ from: p.agent, to: p.rebuttal.target_agent, kind: "rebut" });
  }
  return out;
}

function readout(latest: StancePost[]): string {
  if (latest.length === 0) return "Nobody has spoken yet";
  const counts = new Map<Stance, number>();
  latest.forEach((p) => counts.set(p.stance, (counts.get(p.stance) ?? 0) + 1));
  if (counts.size === 1 && latest.length === 3) return `All three say ${STANCE_LABEL[latest[0].stance].toLowerCase()}`;
  return [...counts].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${STANCE_LABEL[s].toLowerCase()}`).join(" · ");
}

export function Seats({ state }: { state: CaseState }) {
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const history = (agent: AgentName) => state.rounds.flatMap((r) => (r.posts[agent] ? [r.posts[agent]] : []));
  const latest = AGENT_ORDER.flatMap((a) => history(a).at(-1) ?? []);
  const links = exchanges(state).slice(-5);
  const ev = state.evidenceOrder.map((id) => state.evidence[id]).filter(Boolean);
  const helpers = new Set(state.selections.map((s) => s.specialist_name)).size;

  return (
    <div className="px-5 pt-4 pb-5 sm:px-8">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="rule-label">Open floor · no chair</h2>
        <p className="text-[0.82rem] font-medium" aria-live="polite">{readout(latest)}</p>
      </div>

      <div className="relative">
        <svg viewBox="0 0 300 64" preserveAspectRatio="none" className="pointer-events-none absolute inset-x-0 top-0 h-16 w-full overflow-visible" aria-hidden>
          {links.map((l, i) => {
            const a = COL[l.from], b = COL[l.to], d = Math.abs(a - b) / 100;
            const fresh = i >= links.length - 2;
            return <path key={`${i}${l.from}${l.to}${l.kind}`} d={`M${a} 60 Q${(a + b) / 2} ${60 - 66 * d} ${b} 60`} fill="none" stroke={AGENTS[l.from].cssVar}
              strokeWidth={fresh ? 2 : 1.25} strokeDasharray={l.kind === "ask" ? "2 5" : "7 4"} strokeLinecap="round" opacity={fresh ? 1 : 0.3}
              vectorEffect="non-scaling-stroke" className={fresh ? "flow" : ""} style={{ animationDirection: a < b ? "normal" : "reverse" }} />;
          })}
        </svg>

        <div className="grid grid-cols-3 pt-14">
          {AGENT_ORDER.map((agent) => {
            const a = AGENTS[agent];
            const now = history(agent).at(-1);
            const awake = !finished && !!lastRound?.active.includes(agent) && lastRound.posts[agent] === undefined;
            const conf = now?.confidence ?? 0;
            return (
              <div key={agent} title={a.goal} className="flex flex-col items-center text-center">
                <div className="relative grid size-[68px] place-items-center">
                  {awake && <span className="halo absolute inset-1 rounded-full" style={{ background: a.cssVar }} />}
                  <svg viewBox="0 0 68 68" className="absolute inset-0 -rotate-90" aria-hidden>
                    <circle cx="34" cy="34" r="27" fill="none" stroke="var(--sunken)" strokeWidth="4" />
                    <circle cx="34" cy="34" r="27" fill="none" stroke={now ? RING[now.stance] : "var(--line)"} strokeWidth="4" strokeLinecap="round"
                      strokeDasharray={`${conf * CIRC} ${CIRC}`} className="transition-[stroke-dasharray,stroke] duration-700 ease-out" />
                  </svg>
                  <span className={`relative grid size-12 place-items-center rounded-full text-lg font-semibold ${a.tint} ${a.text}`}>{a.label[0]}</span>
                </div>
                <span className={`mt-1.5 text-sm font-semibold ${a.text}`}>{a.label}</span>
                <span className="mt-0.5 flex h-6 items-center gap-1.5">
                  {awake ? <span className="typing flex gap-1 text-muted" role="status" aria-label={`${a.label} was woken`}><span /><span /><span /></span>
                    : now ? <><StancePill stance={now.stance} /><span className="mono text-muted">{Math.round(conf * 100)}%</span></>
                    : <span className="text-[0.8rem] text-muted">asleep</span>}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 border border-line bg-surface/70 px-3 py-2" aria-label="Shared evidence board">
        <span className="rule-label shrink-0">Shared board</span>
        <span className="flex min-w-0 flex-1 flex-wrap gap-1" aria-hidden>
          {ev.map((e) => <i key={e.id} className="rise size-2.5 rounded-[3px]" style={{ background: e.requested_by in AGENTS ? AGENTS[e.requested_by as AgentName].cssVar : "var(--ink)", opacity: e.requested_by in AGENTS ? 1 : 0.28 }} />)}
        </span>
        <span className="mono shrink-0 text-muted">{ev.length} facts · {helpers} helpers</span>
      </div>
    </div>
  );
}
