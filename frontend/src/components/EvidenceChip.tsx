"use client";

// Every claim shows its chips; clicking opens the raw evidence.
export function EvidenceChip({ id, onOpen, missing }: { id: string; onOpen: (id: string) => void; missing?: boolean }) {
  return (
    <button
      onClick={() => onOpen(id)}
      title={missing ? "Evidence not loaded yet" : `Open ${id}`}
      className={`mono press rounded border px-1.5 py-px font-medium hover:border-ink ${
        missing ? "border-dashed border-line text-muted" : "border-line bg-sunken text-ink"
      }`}
    >
      {id}
    </button>
  );
}
