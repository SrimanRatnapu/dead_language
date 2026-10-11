"use client";
import { AGENT_ORDER, AGENTS, CAPABILITY_LABEL, STANCE_LABEL, STANCE_STYLE, prettyName } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import type { AgentName, Stance, StancePost } from "@/lib/types";
import { Icon } from "./Icon";

export function StancePill({ stance, className = "" }: { stance: Stance; className?: string }) {
  return <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-none px-2 py-0.5 text-base font-semibold ${STANCE_STYLE[stance]} ${className}`}>{STANCE_LABEL[stance]}</span>;
}

const STANCE_BAR: Record<Stance, string> = { file: "bg-cobalt", dismiss: "bg-green", need_more: "bg-line" };

function derive(state: CaseState) {
  const finished = state.caseFile !== null || state.budgetExceeded !== null;
  const lastRound = state.rounds.at(-1);
  const history = (agent: AgentName) => state.rounds.flatMap((r) => (r.posts[agent] ? [r.posts[agent]] : []));
  const latest = AGENT_ORDER.flatMap((a) => history(a).at(-1) ?? []);
  const order = lastRound?.active ?? [];
  const thinking = finished ? null : order.find((a) => lastRound?.posts[a] === undefined) ?? null;
  return { finished, lastRound, history, latest, thinking };
}

// The one status line for the whole conversation: where the three positions stand right now.
export function Standing({ state }: { state: CaseState }) {
  const { finished, lastRound, latest, thinking } = derive(state);
  const counts = new Map<Stance, number>();
  latest.forEach((p: StancePost) => counts.set(p.stance, (counts.get(p.stance) ?? 0) + 1));
  const words = latest.length === 0 ? "Nobody has spoken yet"
    : counts.size === 1 && latest.length === 3 ? `All three say ${STANCE_LABEL[latest[0].stance].toLowerCase()}`
    : [...counts].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${STANCE_LABEL[s].toLowerCase()}`).join(" · ");
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-5 py-3 sm:px-8" aria-live="polite">
      <div className="flex h-2 w-28 shrink-0 gap-0.5" aria-hidden>
        {(["file", "need_more", "dismiss"] as Stance[]).map((s) => (counts.get(s) ?? 0) > 0 && <span key={s} className={`${STANCE_BAR[s]} transition-[flex-grow] duration-500`} style={{ flexGrow: counts.get(s) }} />)}
        {latest.length === 0 && <span className="grow bg-line" />}
      </div>
      <p className="font-semibold">{words}</p>
      <p className="ml-auto text-muted">{finished ? "Review finished" : thinking ? <><b className={AGENTS[thinking].text}>{AGENTS[thinking].label}</b> is thinking</> : null}</p>
    </div>
  );
}

// Left rail: the three agents, then any specialist an agent calls in during the discussion.
export function AgentRail({ state, onOpen }: { state: CaseState; onOpen: (id: string) => void }) {
  const { history, thinking } = derive(state);
  const callIns = state.selections.filter((s) => s.requested_by in AGENTS).map((s) => {
    const at = Date.parse(s.at);
    const ev = state.evidenceOrder.map((id) => state.evidence[id]).find((e) => e.capability === s.capability && Date.parse(e.created_at) >= at);
    const fail = state.failures.find((f) => f.capability === s.capability && Date.parse(f.at) >= at);
    return { s, ev, fail };
  });
  return (
    <ul className="flex flex-col p-2" aria-label="Agents">
      {AGENT_ORDER.map((agent) => {
        const a = AGENTS[agent];
        const now = history(agent).at(-1);
        const busy = thinking === agent;
        return (
          <li key={agent} title={a.goal} className={`border-b p-3 transition-colors duration-300 ${busy ? "border-ink" : "border-line"}`}>
            <div className="flex items-center gap-3">
              <span className={`grid size-9 shrink-0 place-items-center font-semibold ${a.tint} ${a.text}`}>{a.label[0]}</span>
              <div className="min-w-0">
                <p className={`truncate font-semibold leading-tight ${a.text}`}>{a.label}</p>
                <div className="mt-1 flex min-h-6 items-center gap-2">
                  {busy ? <span className="typing flex gap-1 text-muted" role="status" aria-label={`${a.label} is thinking`}><span /><span /><span /></span>
                    : now?.abstained ? <span className="text-muted">Sat out</span>
                    : now ? <><StancePill stance={now.stance} /><span className="mono text-muted">{Math.round(now.confidence * 100)}%</span></>
                    : <span className="text-muted">Listening</span>}
                </div>
              </div>
            </div>
          </li>
        );
      })}
      {callIns.map(({ s, ev, fail }, i) => {
        const by = AGENTS[s.requested_by as AgentName];
        const working = !ev && !fail;
        return (
          <li key={i} className={`rise border-b p-3 transition-colors duration-300 ${working ? "border-ink" : "border-line"}`}>
            <div className="flex items-center gap-3">
              <span className="grid size-9 shrink-0 place-items-center bg-cobalt-tint text-cobalt-ink"><Icon name={s.capability} size={18} /></span>
              <div className="min-w-0">
                <p className="truncate font-semibold leading-tight text-cobalt-ink">{CAPABILITY_LABEL[s.capability]}</p>
                <div className="mt-1 flex min-h-6 items-center gap-2 text-muted">
                  {working ? <span className="typing flex gap-1" role="status" aria-label="Working"><span /><span /><span /></span>
                    : fail ? <span className="text-red">Did not answer</span> : null}
                  <span>{working || fail ? "· " : ""}for <b className={by.text}>{by.label}</b></span>
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
