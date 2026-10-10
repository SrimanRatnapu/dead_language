"use client";
import { useEffect, useRef } from "react";
import { AGENT_ORDER } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { PostCard } from "./PostCard";

export function RoundTimeline({ state, onOpen }: { state: CaseState; onOpen: (id: string) => void }) {
  const end = useRef<HTMLDivElement>(null);
  const stuck = useRef(true);
  const posts = state.rounds.reduce((n, r) => n + Object.keys(r.posts).length + r.rejected.length, 0);

  // Follow the newest post unless the viewer scrolled up to read.
  useEffect(() => {
    if (stuck.current) end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [posts, state.rounds.length]);

  return (
    <div
      className="h-full overflow-y-auto p-4"
      onScroll={(e) => {
        const el = e.currentTarget;
        stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      }}
    >
      {state.rounds.length === 0 && <p className="text-muted">Gathering first evidence…</p>}
      <div className="flex flex-col gap-6">
        {state.rounds.map((round, i) => (
          <section key={round.round} className="flex flex-col gap-2">
            <h2 className="display text-lg">Round {round.round}</h2>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] items-start gap-3">
              {AGENT_ORDER.map((agent) => (
                <PostCard
                  key={agent}
                  agent={agent}
                  round={round}
                  known={state.evidence}
                  onOpen={onOpen}
                  roundOpen={i === state.rounds.length - 1 && !state.caseFile}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      <div ref={end} />
    </div>
  );
}
