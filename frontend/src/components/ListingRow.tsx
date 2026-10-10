"use client";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { ListingRow as Row } from "@/lib/types";
import { Photo } from "./Photo";

export const LISTING_GRID = "grid grid-cols-[56px_minmax(0,2.4fr)_90px_110px_minmax(0,1.2fr)_minmax(0,2fr)_96px] items-center gap-4";

export function ListingRow({ row, busy, onReview }: { row: Row; busy: boolean; onReview: (id: string) => void }) {
  const { listing, seller, triage } = row;
  return (
    <li className={`${LISTING_GRID} border-b border-line px-5 py-3 hover:bg-surface`}>
      {listing.image_paths[0]
        ? <Photo src={imageUrl(listing.image_paths[0])} label={listing.id} className="size-14 rounded-md" />
        : <div className="size-14 rounded-md bg-sunken" />}
      <div className="min-w-0">
        <p className="truncate font-medium">{listing.title}</p>
        <p className="flex items-center gap-2 text-muted">
          <span className="mono">{listing.id}</span>
          {listing.is_reconstructed && <span className="truncate rounded bg-sunken px-1.5">Reconstructed from a documented case</span>}
        </p>
      </div>
      <span className="font-semibold">{usd(listing.price_usd)}</span>
      <span className="text-muted">{listing.stated_material.replaceAll("_", " ")}</span>
      <span className="truncate">{seller.name}</span>
      {triage ? (
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-sunken" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={triage.score} aria-label="Triage score">
              <div className="h-full bg-ink" style={{ width: `${triage.score * 100}%` }} />
            </div>
            <span className="mono">{triage.score.toFixed(2)}</span>
          </div>
          <p className="truncate text-muted" title={triage.reason}>{triage.reason}</p>
        </div>
      ) : <span className="text-muted">Not scored</span>}
      <button
        onClick={() => onReview(listing.id)}
        disabled={busy}
        className="press rounded-md bg-ink px-3 py-1.5 font-medium text-bg"
      >
        {busy ? "Starting…" : "Review"}
      </button>
    </li>
  );
}
