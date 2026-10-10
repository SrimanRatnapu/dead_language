"use client";
import { AGENTS, CAPABILITY_LABEL, STANCE_LABEL } from "@/lib/agents";
import type { Round } from "@/lib/caseState";
import type { AgentName, StancePost } from "@/lib/types";
import { EvidenceChip } from "./EvidenceChip";
import { StanceMark } from "./StanceMark";

interface Props {
  agent: AgentName;
  round: Round;
  known: Record<string, unknown>;
  onOpen: (id: string) => void;
  roundOpen: boolean; // true while this is the latest round and the case hasn't ended
}

function Chips({ ids, known, onOpen }: { ids: string[]; known: Record<string, unknown>; onOpen: (id: string) => void }) {
  return (
    <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => <EvidenceChip key={id} id={id} onOpen={onOpen} missing={!(id in known)} />)}
    </span>
  );
}

export function PostCard({ agent, round, known, onOpen, roundOpen }: Props) {
  const a = AGENTS[agent];
  const post: StancePost | undefined = round.posts[agent];
  const called = round.active.length === 0 || round.active.includes(agent);
  const rejected = round.rejected.filter((r) => r.agent === agent);

  if (!called && !post) {
    return (
      <div className="rounded-lg border border-dashed border-line p-3 text-muted opacity-70">
        <span className={`font-semibold ${a.text}`}>{a.label}</span>
        <p>Not called — nothing new for them</p>
      </div>
    );
  }

  return (
    <article className={`rise flex flex-col gap-2.5 rounded-lg border bg-surface p-3 ${post ? a.ring : "border-line"}`}>
      <header className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <span className={`size-2 rounded-full ${a.dot}`} />
          <span className={`font-semibold ${a.text}`}>{a.label}</span>
        </span>
        {post && (
          <span className="flex items-center gap-2">
            <span className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 font-medium ${a.tint} ${a.text}`}>
              <StanceMark stance={post.stance} size={8} />
              {STANCE_LABEL[post.stance]}
              <span className="mono">{post.confidence.toFixed(2)}</span>
            </span>
          </span>
        )}
      </header>

      {post?.ready_to_close && <p className="w-fit rounded bg-sunken px-1.5 text-muted">Ready to close</p>}

      {!post && <p className="text-muted">{roundOpen ? "Reading the evidence…" : "No post this round."}</p>}

      {post?.changed_because && (
        <p className={`rounded-md p-2 font-medium ${a.tint} ${a.text}`}>
          Changed position because {post.changed_because.replace(/^./, (c) => c.toLowerCase())}
          <Chips ids={post.changed_because_evidence} known={known} onOpen={onOpen} />
        </p>
      )}

      {post?.claims.map((c, i) => (
        <p key={i}>{c.text}<Chips ids={c.evidence_ids} known={known} onOpen={onOpen} /></p>
      ))}

      {rejected.map((r, i) => (
        <p key={i} className="rounded-md bg-red-tint p-2 text-red">
          <s>{r.claim_text}</s>
          <span className="mt-0.5 block no-underline">Rejected: {r.reasons.join("; ")}</span>
        </p>
      ))}

      {post?.rebuttal && (
        <p className="text-muted">
          Answering {AGENTS[post.rebuttal.target_agent].label}: <span className="text-ink">{post.rebuttal.response}</span>
          <Chips ids={post.rebuttal.evidence_ids} known={known} onOpen={onOpen} />
        </p>
      )}
      {post?.challenge && (
        <p className="text-muted">Asks {AGENTS[post.challenge.target_agent].label}: <span className="text-ink">{post.challenge.question}</span></p>
      )}
      {post?.requests.map((r, i) => (
        <p key={i} className="text-muted">
          Asked for: <span className="text-ink">{CAPABILITY_LABEL[r.capability]} — {r.question}</span>, because {r.reason.replace(/^./, (c) => c.toLowerCase())}
        </p>
      ))}
    </article>
  );
}
