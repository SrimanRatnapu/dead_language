"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ListingCard } from "@/components/ListingCard";
import { Photo } from "@/components/Photo";
import { usd } from "@/lib/agents";
import { imageUrl, startCase } from "@/lib/api";
import { DEMO_CASES } from "@/lib/demoCases";
import { loadListings, loadReplays } from "@/lib/stubs";
import type { ListingRow } from "@/lib/types";

const [GOLDEN] = DEMO_CASES;

export default function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<ListingRow[]>([]);
  const [replays, setReplays] = useState<string[]>([]);
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    loadListings().then(({ data, offline: off }) => { setRows(data); setOffline(off); }).catch(() => setOffline(true));
    loadReplays().then(({ data }) => setReplays(data)).catch(() => setReplays([]));
  }, []);

  // Live review when the backend is up; otherwise play the recorded case so the demo never stalls.
  async function review(listingId: string, replay?: string) {
    setBusy(listingId);
    try {
      const { case_id } = await startCase(listingId);
      router.push(`/case/${case_id}`);
    } catch {
      router.push(`/replay/${replay ?? GOLDEN.replay}`);
    }
  }

  const golden = rows.find((r) => r.listing.id === GOLDEN.listingId) ?? rows[0];
  const others = rows.filter((r) => r !== golden);

  return (
    <div className="h-[calc(100dvh-3rem)] overflow-y-auto">
      <main className="mx-auto max-w-6xl px-8 py-10">
        <div className="mb-7 flex items-end justify-between">
          <div>
            <h1 className="display text-4xl">Listings</h1>
            <p className="mt-1 text-muted">Choose one to review.</p>
          </div>
          <Link href="/results" className="press rounded-full border border-line px-4 py-2 font-medium hover:border-ink">Results</Link>
        </div>

        {golden && (
          <section className="mb-10 grid grid-cols-[minmax(0,1.2fr)_minmax(260px,0.8fr)] items-center gap-8 border-y border-line py-6">
            <button onClick={() => review(golden.listing.id)} disabled={busy !== null} className="press group overflow-hidden rounded-2xl text-left">
              <Photo
                src={imageUrl(golden.listing.image_paths[0] ?? "")}
                label={golden.listing.title}
                caption="Photo unavailable offline"
                className="aspect-[16/9] w-full group-hover:brightness-95"
              />
            </button>
            <div className="flex flex-col items-start gap-4">
              <span className="font-medium text-amber-ink">Start here</span>
              <h2 className="display text-4xl">{golden.listing.title}</h2>
              <p className="text-lg"><strong>{usd(golden.listing.price_usd)}</strong> <span className="text-muted">listed as {golden.listing.stated_material.replaceAll("_", " ")}</span></p>
              {golden.listing.is_reconstructed && <p className="text-muted">Reconstructed from a documented case.</p>}
              <button onClick={() => review(golden.listing.id)} disabled={busy !== null} className="press rounded-full bg-ink px-5 py-2.5 font-medium text-bg">
                {busy === golden.listing.id ? "Starting…" : offline ? "Play review" : "Start review"}
              </button>
            </div>
          </section>
        )}

        {others.length > 0 && (
          <section>
            <div className="mb-4 flex items-baseline justify-between">
              <h2 className="display text-2xl">More listings</h2>
              {replays.length > 0 && (
                <details className="relative">
                  <summary className="cursor-pointer list-none font-medium text-muted hover:text-ink">Replays</summary>
                  <ul className="glass absolute right-0 z-10 mt-2 w-56 rounded-xl border border-line p-1 shadow-[var(--shadow)]">
                    {replays.map((r) => (
                      <li key={r}><Link href={`/replay/${r}`} className="block rounded-lg px-3 py-1.5 hover:bg-sunken">{r.replaceAll("_", " ")}</Link></li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <div className="grid grid-cols-4 gap-x-5 gap-y-8">
              {others.map((row) => <ListingCard key={row.listing.id} row={row} busy={busy === row.listing.id} onReview={review} />)}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
