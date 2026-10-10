"use client";
import { CAPABILITY_LABEL } from "@/lib/agents";
import type { Evidence } from "@/lib/types";
import { Icon } from "./Icon";

// Every claim shows what it rests on; click opens the raw evidence. Named by what it is, not by id.
export function EvidenceChip({ evidence, onOpen }: { evidence: Evidence | undefined; onOpen: (id: string) => void }) {
  if (!evidence) return <span title="Evidence still loading" className="rounded-full border border-dashed border-line px-2 text-muted">Loading evidence…</span>;
  return (
    <button
      onClick={() => onOpen(evidence.id)}
      className="press inline-flex items-center gap-1 rounded-full border border-line bg-sunken px-2 py-px align-middle text-[0.8rem] font-medium hover:border-ink"
    >
      <Icon name={evidence.capability} size={12} />
      {CAPABILITY_LABEL[evidence.capability]}
    </button>
  );
}
