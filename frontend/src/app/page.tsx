"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ListingRow, LISTING_GRID } from "@/components/ListingRow";
import { startCase } from "@/lib/api";
import { DEMO_CASES } from "@/lib/demoCases";
import { loadListings, loadReplays } from "@/lib/stubs";
import type { ListingRow as Row } from "@/lib/types";

export default function BrowsePage() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [replays, setReplays] = useState<string[]>([]);
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadListings().then(({ data, offline: off }) => {
      setRows([...data].sort((a, b) => (b.triage?.score ?? -1) - (a.triage?.score ?? -1)));
      setOffline(off);
    }).catch(() => setRows([]));
    loadReplays().then(({ data }) => setReplays(data)).catch(() => setReplays([]));
  }, []);

  async function review(listingId: string) {
    setBusy(listingId);
    setError(null);
    try {
      const { case_id } = await startCase(listingId);
      router.push(`/case/${case_id}`);
    } catch {
      setError("Could not start a review — the backend is not reachable. Open a replay instead.");
      setBusy(null);
    }
  }

  return (
    <div className="flex h-[calc(100dvh-3rem)] flex-col">
      {offline && <p className="bg-sunken px-5 py-1.5 text-muted">Backend offline — replays only. Listings shown are sample data.</p>}

      <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
        <h1 className="display mr-2 text-xl">Prepared cases</h1>
        {DEMO_CASES.map((d) => (
          <button key={d.key} onClick={() => review(d.listingId)} disabled={busy !== null} className="press rounded-md border border-line bg-surface px-3 py-1.5 hover:border-ink">
            <span className="mono mr-1.5 text-muted">{d.key}</span>{d.label}
          </button>
        ))}
        <details className="relative ml-auto">
          <summary className="press cursor-pointer list-none rounded-md border border-line bg-surface px-3 py-1.5 hover:border-ink">Replays</summary>
          <ul className="glass absolute right-0 z-10 mt-1 w-56 rounded-lg border border-line p-1 shadow-[var(--shadow)]">
            {replays.map((r) => (
              <li key={r}><Link href={`/replay/${r}`} className="mono block rounded px-2 py-1.5 hover:bg-sunken">{r}</Link></li>
            ))}
            {replays.length === 0 && <li className="px-2 py-1.5 text-muted">No replays found</li>}
          </ul>
        </details>
      </div>
      {error && <p role="alert" className="bg-red-tint px-5 py-1.5 text-red">{error}</p>}

      <div className={`${LISTING_GRID} border-b border-line px-5 py-2 text-muted`}>
        <span /><span>Listing</span><span>Price</span><span>Stated</span><span>Seller</span><span>Triage</span><span />
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {rows === null && <li className="p-5 text-muted">Loading listings…</li>}
        {rows?.length === 0 && <li className="p-5 text-muted">No listings available.</li>}
        {rows?.map((row) => <ListingRow key={row.listing.id} row={row} busy={busy === row.listing.id} onReview={review} />)}
      </ul>
    </div>
  );
}
