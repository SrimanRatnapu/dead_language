"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Photo } from "@/components/Photo";
import { imageUrl } from "@/lib/api";
import { DEMO_CASES, demoCaseForReplay } from "@/lib/demoCases";
import { loadListings, loadReplays } from "@/lib/stubs";
import type { Listing } from "@/lib/types";

export default function Replays() {
  const [names, setNames] = useState<string[]>(DEMO_CASES.map((c) => c.replay));
  const [listings, setListings] = useState<Record<string, Listing>>({});
  useEffect(() => {
    loadReplays().then(({ data }) => setNames(data.filter((n) => demoCaseForReplay(n)))).catch(() => {});
    loadListings().then(({ data }) => setListings(Object.fromEntries(data.map((r) => [r.listing.id, r.listing])))).catch(() => {});
  }, []);
  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-5xl px-5 py-6 sm:px-8">
        <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line pb-3"><h1 className="text-xl font-semibold tracking-tight">Replays</h1><p className="text-sm text-muted">Recorded reviews. No live service needed.</p></header>
        <ul className="divide-y divide-line border-b border-line">
          {names.map((n) => {
            const c = demoCaseForReplay(n)!;
            const l = listings[c.listingId];
            return (
              <li key={n}>
                <Link href={`/replay/${n}`} className="press group grid min-h-16 grid-cols-[3.5rem_1fr_auto] items-center gap-4 py-3 hover:bg-surface/70">
                  <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={c.label} className="size-14 w-full" />
                  <span className="min-w-0"><span className="block font-semibold">{c.label}</span><span className="block truncate text-sm text-muted">{c.blurb}</span></span>
                  <span className="text-sm font-semibold text-cobalt-ink group-hover:underline">Open →</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </main>
  );
}
