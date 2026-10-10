"use client";
import { AGENT_ORDER, AGENTS, STANCE_LABEL } from "@/lib/agents";
import type { Round } from "@/lib/caseState";
import type { AgentName, StancePost } from "@/lib/types";

// 0 = Dismiss end, 1 = File end. Confidence pushes a stance further toward its end.
function position(p: StancePost): number {
  const dir = p.stance === "file" ? 1 : p.stance === "dismiss" ? -1 : 0;
  return 0.5 + (dir * p.confidence) / 2;
}

function history(rounds: Round[], agent: AgentName): StancePost[] {
  return rounds.flatMap((r) => (r.posts[agent] ? [r.posts[agent]] : []));
}

export function Balance({ rounds }: { rounds: Round[] }) {
  return (
    <div className="flex flex-col gap-2 px-6 py-4">
      <div className="grid grid-cols-[88px_1fr_120px] items-end gap-4 text-muted">
        <span />
        <div className="flex justify-between font-medium"><span>Dismiss</span><span>File</span></div>
        <span />
      </div>
      {AGENT_ORDER.map((agent) => {
        const posts = history(rounds, agent);
        const now = posts.at(-1);
        const before = posts.at(-2);
        const a = AGENTS[agent];
        return (
          <div key={agent} className="grid grid-cols-[88px_1fr_120px] items-center gap-4">
            <span className={`font-semibold ${a.text}`}>{a.label}</span>
            <div className="relative h-6">
              <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
              <div className="absolute left-1/2 top-1/2 h-3 w-px -translate-y-1/2 bg-line" />
              {before && (
                <span
                  className={`marker absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-bg ${a.ring}`}
                  style={{ left: `${position(before) * 100}%` }}
                  aria-hidden
                />
              )}
              <span
                className={`marker absolute top-1/2 size-5 -translate-x-1/2 -translate-y-1/2 rounded-full ${a.dot} ${now ? "opacity-100" : "opacity-30"}`}
                style={{ left: `${(now ? position(now) : 0.5) * 100}%` }}
                aria-label={now ? `${a.label}: ${STANCE_LABEL[now.stance]}` : `${a.label}: not decided`}
              />
            </div>
            <span className="text-muted">
              {now ? <><span className="font-medium text-ink">{STANCE_LABEL[now.stance]}</span> · {Math.round(now.confidence * 100)}% sure</> : "Reading…"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
