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
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <h1 className="display text-4xl sm:text-5xl">Replays</h1>
        <p className="mt-3 max-w-xl text-base text-muted">Recorded reviews. Watch how the agents worked a past listing, step by step. No live service needed.</p>
        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          {names.map((n) => {
            const c = demoCaseForReplay(n)!;
            const l = listings[c.listingId];
            return (
              <Link key={n} href={`/replay/${n}`} className="press group grid grid-cols-[8rem_1fr] border border-line bg-surface hover:border-cobalt">
                <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={c.label} className="h-full min-h-32 w-full" />
                <span className="flex flex-col p-4">
                  <span className="text-lg font-semibold tracking-tight">{c.label}</span>
                  <span className="mt-1 text-base leading-snug text-muted">{c.blurb}</span>
                  <span className="mt-auto pt-3 font-semibold text-cobalt-ink">Watch replay →</span>
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </main>
  );
}
