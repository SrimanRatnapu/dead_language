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

const [GOLDEN, ...OTHER_CASES] = DEMO_CASES;

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
      <section className="mx-auto grid max-w-6xl grid-cols-[1.15fr_1fr] items-center gap-16 px-8 pb-16 pt-10">
        <div className="flex flex-col gap-6">
          <h1 className="display text-[clamp(3.25rem,6.2vw,5.75rem)]">
            A listing says <em>bone</em>.<br />The price says <em className="text-amber-ink">ivory</em>.
          </h1>
          <p className="max-w-[46ch] text-lg text-muted">
            Three agents argue over every suspicious listing, so honest sellers aren&rsquo;t flagged and real ivory isn&rsquo;t missed.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={() => review(GOLDEN.listingId)} disabled={busy !== null} className="press rounded-full bg-ink px-6 py-3 text-base font-medium text-bg">
              {busy === GOLDEN.listingId ? "Starting…" : "Watch the review"}
            </button>
            <Link href="/results" className="press rounded-full border border-line px-6 py-3 text-base font-medium hover:border-ink">See the results</Link>
          </div>
          <p className="text-muted">
            Also try:{" "}
            {OTHER_CASES.map((c, i) => (
              <span key={c.key}>
                {i > 0 && " · "}
                <button onClick={() => review(c.listingId, c.replay)} disabled={busy !== null} className="underline underline-offset-2 hover:text-ink">{c.label}</button>
              </span>
            ))}
          </p>
          {offline && <p className="text-muted">Offline: reviews play from recorded cases.</p>}
        </div>

        {golden && (
          <button onClick={() => review(golden.listing.id)} disabled={busy !== null} className="press group flex flex-col gap-3 text-left">
            <Photo
              src={imageUrl(golden.listing.image_paths[0] ?? "")}
              label={golden.listing.title}
              caption="Photo unavailable offline"
              className="aspect-[4/3] w-full rounded-2xl shadow-[var(--shadow)]"
            />
            <span className="display text-3xl">{golden.listing.title}</span>
            <span className="flex items-baseline gap-3 text-lg">
              <span className="font-semibold">{usd(golden.listing.price_usd)}</span>
              <span className="text-muted">listed as {golden.listing.stated_material.replaceAll("_", " ")}</span>
            </span>
          </button>
        )}
      </section>

      {others.length > 0 && (
        <section className="border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-8 py-8">
            <div className="mb-4 flex items-baseline justify-between">
              <h2 className="display text-2xl">More listings, most suspicious first</h2>
              {replays.length > 0 && (
                <details className="relative">
                  <summary className="cursor-pointer list-none text-muted hover:text-ink">Recorded cases</summary>
                  <ul className="glass absolute right-0 z-10 mt-2 w-56 rounded-xl border border-line p-1 shadow-[var(--shadow)]">
                    {replays.map((r) => (
                      <li key={r}><Link href={`/replay/${r}`} className="block rounded-lg px-3 py-1.5 hover:bg-sunken">{r.replaceAll("_", " ")}</Link></li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <div className="flex gap-5 overflow-x-auto pb-3">
              {others.map((row) => <ListingCard key={row.listing.id} row={row} busy={busy === row.listing.id} onReview={review} />)}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
