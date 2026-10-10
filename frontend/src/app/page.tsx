"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ListingCard } from "@/components/ListingCard";
import { WildlifeSignal } from "@/components/WildlifeSignal";
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
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)] overflow-x-hidden">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:py-12">
        <section className="grid gap-6 border-b border-line pb-10 lg:grid-cols-[.78fr_1.22fr] lg:items-center lg:pb-12">
          <div>
            <p className="rule-label mb-5 text-cobalt-ink">Wildlife marketplace review</p>
            <h1 className="display max-w-md text-5xl sm:text-6xl">They can hide the word ivory. They can&apos;t hide the price.</h1>
            <p className="mt-5 max-w-md text-lg leading-relaxed text-muted">Three competing agents trace price, photographs, and language into evidence a human can inspect.</p>
          </div>
          <WildlifeSignal />
        </section>

        {golden && (
          <section className="grid gap-6 py-8 lg:grid-cols-[1.3fr_.7fr] lg:py-12">
            <button onClick={() => review(golden.listing.id)} disabled={busy !== null} className="press group relative overflow-hidden border border-line bg-surface text-left shadow-[var(--shadow)]">
              <Photo src={imageUrl(golden.listing.image_paths[0] ?? "")} label={golden.listing.title} caption="Photo unavailable offline" className="aspect-[16/9] w-full transition duration-500 group-hover:scale-[1.02] group-hover:brightness-75" />
              <span className="absolute left-0 top-0 border-b border-r border-line bg-bg/90 px-3 py-2 rule-label text-cobalt-ink">Case of record</span>
              <span className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-bg via-bg/80 to-transparent p-5 pt-16 text-lg font-medium">{golden.listing.title}</span>
            </button>
            <div className="flex flex-col justify-between border-y border-line py-5 lg:border-y-0 lg:border-r lg:pl-8">
              <div>
                <p className="rule-label text-muted">Listed at</p>
                <p className="display mt-2 text-5xl text-cobalt-ink">{usd(golden.listing.price_usd)}</p>
                <p className="mt-5 text-muted">Named <span className="text-ink">{golden.listing.stated_material.replaceAll("_", " ")}</span>. The price and wording make it worth a closer read.</p>
              </div>
              <div className="mt-8 flex items-center gap-4">
                <button onClick={() => review(golden.listing.id)} disabled={busy !== null} className="press bg-cobalt px-5 py-3 font-semibold text-bg hover:bg-cobalt-ink">
                  {busy === golden.listing.id ? "Opening…" : offline ? "Play case" : "Review listing"}
                </button>
                <span className="mono text-muted">{offline ? "Recorded playback" : "Live when available"}</span>
              </div>
            </div>
          </section>
        )}

        {others.length > 0 && (
          <section className="border-t border-line pt-7">
            <div className="mb-6 flex items-end justify-between gap-5">
              <h2 className="display text-3xl">Other listings</h2>
              {replays.length > 0 && <details className="relative"><summary className="press cursor-pointer list-none border border-line px-3 py-2 text-muted hover:border-cobalt hover:text-ink">Recorded cases</summary><ul className="glass absolute right-0 z-10 mt-2 w-60 border border-line p-1 shadow-[var(--shadow)]">{replays.map((r) => <li key={r}><Link href={`/replay/${r}`} className="block px-3 py-2 hover:bg-cobalt-tint">{r.replaceAll("_", " ")}</Link></li>)}</ul></details>}
            </div>
            <div className="grid gap-x-5 gap-y-9 sm:grid-cols-2 lg:grid-cols-4">{others.map((row) => <ListingCard key={row.listing.id} row={row} busy={busy === row.listing.id} onReview={review} />)}</div>
          </section>
        )}
      </div>
    </main>
  );
}
