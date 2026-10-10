"use client";
import { AGENT_ORDER, AGENTS, STANCE_LABEL, STANCE_STYLE } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { AgentName, Stance, StancePost } from "@/lib/types";

export function StancePill({ stance, className = "" }: { stance: Stance; className?: string }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-base font-semibold ${STANCE_STYLE[stance]} ${className}`}>{STANCE_LABEL[stance]}</span>;
}

const RING: Record<Stance, string> = { file: "var(--cobalt)", dismiss: "var(--green)", need_more: "var(--line)" };
const CIRC = 2 * Math.PI * 27;
// Round table: three corners of a triangle. Arrows exist only where one agent really addressed another.
const W = 400, H = 280, R = 48;
const POS: Record<AgentName, { x: number; y: number }> = { buyer: { x: 64, y: 58 }, defender: { x: 336, y: 58 }, caseload: { x: 200, y: 214 } };
const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

type Link = { from: AgentName; to: AgentName; kind: "ask" | "rebut" | "read"; text: string };

// Real exchanges so far, oldest first.
function exchanges(state: CaseState): Link[] {
  const out: Link[] = [];
  for (const item of state.feed) {
    if (item.kind !== "post") continue;
    const p = item.post;
    if (p.challenge) out.push({ from: p.agent, to: p.challenge.target_agent, kind: "ask", text: p.challenge.question });
    if (p.rebuttal) out.push({ from: p.agent, to: p.rebuttal.target_agent, kind: "rebut", text: p.rebuttal.response });
  }
  return out;
}

function Arrow({ l, fresh, labeled }: { l: Link; fresh: boolean; labeled: boolean }) {
  const a = POS[l.from], b = POS[l.to];
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len;
  const off = 9;                                             // keep opposite directions side by side
  const sx = a.x + ux * R + -uy * off, sy = a.y + uy * R + ux * off, ex = b.x - ux * R + -uy * off, ey = b.y - uy * R + ux * off;
  const mx = (sx + ex) / 2, my = (sy + ey) / 2;
  const color = AGENTS[l.from].cssVar;
  return (
    <g>
      <line x1={sx} y1={sy} x2={ex} y2={ey} stroke={color} strokeWidth={fresh ? 2.5 : 1.5} strokeLinecap="round"
        strokeDasharray={l.kind === "ask" ? "3 6" : l.kind === "read" ? "2 5" : undefined} opacity={fresh ? 1 : 0.3} markerEnd={`url(#h-${l.from})`} className={fresh ? "flow" : ""} />
      {labeled && <foreignObject x={mx - 78} y={my - 15} width={156} height={30} className="overflow-visible">
        <div className="rise mx-auto w-fit max-w-[156px] truncate rounded-full border border-line bg-surface px-2.5 py-1 text-sm font-medium shadow-[var(--shadow)]" style={{ color }}>
          {l.kind === "read" ? "reading…" : `${l.kind === "ask" ? "asks" : "pushes back"}: ${cut(l.text, 22)}`}
        </div>
      </foreignObject>}
    </g>
  );
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
  const ev = state.evidenceOrder.map((id) => state.evidence[id]).filter(Boolean);
  const helpers = new Set(state.selections.map((s) => s.specialist_name)).size;
  // Agents speak one at a time and each reads what was said before it, so only the first one still waiting is thinking.
  const order = lastRound?.active ?? [];
  const thinking = finished ? null : order.find((a) => lastRound?.posts[a] === undefined) ?? null;
  const reading = thinking ? order.slice(0, order.indexOf(thinking)).at(-1) ?? null : null;
  const exch = exchanges(state).slice(-4);
  const links: Link[] = [...exch, ...(thinking && reading ? [{ from: reading, to: thinking, kind: "read" as const, text: "" }] : [])];

  return (
    <div className="px-5 pt-4 pb-4 sm:px-8">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="rule-label">The three agents</h2>
        <p className="text-base font-medium" aria-live="polite">{readout(latest)}</p>
      </div>

      <div className="relative mx-auto w-full max-w-[460px]" style={{ aspectRatio: `${W} / ${H}` }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 size-full overflow-visible" aria-hidden>
          <defs>{AGENT_ORDER.map((a) => <marker key={a} id={`h-${a}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill={AGENTS[a].cssVar} /></marker>)}</defs>
          {links.map((l, i) => <Arrow key={`${i}${l.from}${l.to}${l.kind}`} l={l} fresh={i >= links.length - 1} labeled={i >= links.length - 1} />)}
        </svg>
        {AGENT_ORDER.map((agent) => {
          const a = AGENTS[agent];
          const now = history(agent).at(-1);
          const isThinking = thinking === agent;
          const conf = now?.confidence ?? 0;
          return (
            <div key={agent} title={a.goal} className="absolute flex w-28 -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center" style={{ left: `${(POS[agent].x / W) * 100}%`, top: `${(POS[agent].y / H) * 100}%` }}>
              <div className="relative grid size-[68px] place-items-center">
                {isThinking && <span className="halo absolute inset-1 rounded-full" style={{ background: a.cssVar }} />}
                <svg viewBox="0 0 68 68" className="absolute inset-0 -rotate-90" aria-hidden>
                  <circle cx="34" cy="34" r="27" fill="none" stroke="var(--sunken)" strokeWidth="4" />
                  <circle cx="34" cy="34" r="27" fill="none" stroke={now ? RING[now.stance] : "var(--line)"} strokeWidth="4" strokeLinecap="round"
                    strokeDasharray={`${conf * CIRC} ${CIRC}`} className="transition-[stroke-dasharray,stroke] duration-700 ease-out" />
                </svg>
                <span className={`relative grid size-12 place-items-center rounded-full text-lg font-semibold ${a.tint} ${a.text}`}>{a.label[0]}</span>
              </div>
              <span className={`mt-1 text-sm font-semibold ${a.text}`}>{a.label}</span>
              <span className="mt-0.5 flex h-6 items-center gap-1.5">
                {isThinking ? <span className="typing flex gap-1 text-muted" role="status" aria-label={`${a.label} is thinking`}><span /><span /><span /></span>
                  : now ? <><StancePill stance={now.stance} /><span className="mono text-muted">{Math.round(conf * 100)}%</span></>
                  : <span className="text-sm text-muted">listening</span>}
              </span>
            </div>
          );
        })}
      </div>
      <p className="mt-1 min-h-5 text-center text-sm text-muted" aria-live="polite">
        {thinking ? (reading ? <><b className={AGENTS[reading].text}>{AGENTS[reading].label}</b> just spoke. <b className={AGENTS[thinking].text}>{AGENTS[thinking].label}</b> is reading it and the shared evidence.</> : <><b className={AGENTS[thinking].text}>{AGENTS[thinking].label}</b> is reading the shared evidence.</>)
          : finished ? "Discussion finished." : state.rounds.length ? "Waiting for a reason to speak again." : ""}
      </p>

      <div className="mt-3 flex items-center gap-3 border border-line bg-surface/70 px-3 py-2" aria-label="Shared evidence board">
        <span className="rule-label shrink-0">Shared evidence</span>
        <span className="flex min-w-0 flex-1 flex-wrap gap-1" aria-hidden>
          {ev.map((e) => <i key={e.id} className="rise size-2.5 rounded-[3px]" style={{ background: e.requested_by in AGENTS ? AGENTS[e.requested_by as AgentName].cssVar : "var(--ink)", opacity: e.requested_by in AGENTS ? 1 : 0.28 }} />)}
        </span>
        <span className="mono shrink-0 text-muted">{ev.length} facts · {helpers} helpers</span>
      </div>
    </div>
  );
}
