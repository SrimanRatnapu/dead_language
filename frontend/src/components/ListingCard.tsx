"use client";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { ListingRow } from "@/lib/types";
import { Photo } from "./Photo";

export function ListingCard({ row, busy, onReview }: { row: ListingRow; busy: boolean; onReview: (id: string) => void }) {
  const { listing, triage } = row;
  return (
    <button
      onClick={() => onReview(listing.id)}
      disabled={busy}
      className="press group flex w-60 shrink-0 flex-col gap-2 text-left"
    >
      <Photo src={imageUrl(listing.image_paths[0] ?? "")} label={listing.title} className="aspect-[4/3] w-full rounded-xl group-hover:brightness-95" />
      <span className="line-clamp-2 font-medium leading-snug">{listing.title}</span>
      <span className="flex items-baseline gap-2">
        <span className="font-semibold">{usd(listing.price_usd)}</span>
        <span className="text-muted">{busy ? "Starting…" : `listed as ${listing.stated_material.replaceAll("_", " ")}`}</span>
      </span>
      {triage && <span className="line-clamp-2 text-muted">{triage.reason}</span>}
    </button>
  );
}
