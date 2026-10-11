"use client";
import { CAPABILITY_LABEL } from "@/lib/agents";
import type { Evidence } from "@/lib/types";

// Every claim shows what it rests on; click opens the raw evidence. Named by what it is, not by id.
export function EvidenceChip({ evidence, onOpen }: { evidence: Evidence | undefined; onOpen: (id: string) => void }) {
  if (!evidence) return <span title="Evidence still loading" className="border border-dashed border-line px-2 text-muted">Loading evidence…</span>;
  return (
    <button
      onClick={() => onOpen(evidence.id)}
      className="press tent align-middle pointer-coarse:min-h-11 hover:brightness-95"
    >
      {evidence.id}<span className="font-sans font-medium">{CAPABILITY_LABEL[evidence.capability]}</span>
    </button>
  );
}
