"use client";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { ListingRow } from "@/lib/types";
import { Photo } from "./Photo";

export function ListingCard({ row, busy, onReview }: { row: ListingRow; busy: boolean; onReview: (id: string) => void }) {
  const { listing, triage } = row;
  return (
    <button onClick={() => onReview(listing.id)} disabled={busy} className="press group min-w-0 text-left">
      <div className="relative overflow-hidden border border-line bg-surface">
        <Photo src={imageUrl(listing.image_paths[0] ?? "")} label={listing.title} className="aspect-[4/3] w-full transition duration-500 group-hover:scale-[1.04] group-hover:brightness-75" />
        <span className="absolute bottom-0 right-0 bg-bg/90 px-2 py-1 mono text-cobalt-ink">{listing.id}</span>
      </div>
      <div className="border-x border-b border-line p-3">
        <span className="line-clamp-2 font-semibold leading-snug">{listing.title}</span>
        <span className="mt-3 flex items-baseline justify-between gap-2"><span className="text-lg font-semibold tracking-tight">{usd(listing.price_usd)}</span><span className="mono text-muted">{busy ? "OPENING" : listing.stated_material.replaceAll("_", " ")}</span></span>
        {triage && <span className="mt-2 block line-clamp-2 text-sm leading-snug text-muted">{triage.reason}</span>}
      </div>
    </button>
  );
}
