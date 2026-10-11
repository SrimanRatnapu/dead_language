"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Photo } from "@/components/Photo";
import { usd } from "@/lib/agents";
import { getListing, imageUrl, startCase } from "@/lib/api";
import { demoCaseForListing } from "@/lib/demoCases";
import { loadListings } from "@/lib/stubs";
import type { Listing, Seller } from "@/lib/types";

export default function Page() {
  return <Suspense><ListingPage /></Suspense>;
}

function ListingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<{ listing: Listing; seller: Seller | null } | null | undefined>(undefined);
  const [photo, setPhoto] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    getListing(id).then(setData).catch(async () => {
      // Backend off: fall back to the exported listings.
      const row = (await loadListings().catch(() => ({ data: [] }))).data.find((r) => r.listing.id === id);
      setData(row ? { listing: row.listing, seller: row.seller ?? null } : null);
    });
  }, [id]);

  async function run() {
    setBusy(true);
    setNote(null);
    try {
      const { case_id } = await startCase(id);
      router.push(`/case/${case_id}`);
    } catch {
      const prepared = demoCaseForListing(id);
      if (prepared) return router.push(`/replay/${prepared.replay}`);
      setBusy(false);
      setNote("The review service is offline, so this listing can't be run right now.");
    }
  }

  if (data === undefined) return <main className="p-8 text-muted">Loading…</main>;
  if (data === null) return <main className="p-8"><p>Listing not found.</p><Link href="/" className="text-cobalt-ink underline">Cases</Link></main>;
  const { listing, seller } = data;
  return (
    <main className="shell-grid min-h-[calc(100dvh-3.5rem)]">
      <div className="mx-auto max-w-5xl px-5 py-6 sm:px-8">
        <Link href="/" className="press -ml-2 inline-flex min-h-11 items-center px-2 text-muted hover:text-cobalt-ink">← Cases</Link>
        <div className="mt-2 grid gap-8 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <Photo src={imageUrl(listing.image_paths[photo] ?? "")} label={listing.title} caption="Photo unavailable" className="aspect-[4/3] w-full border border-line" />
            {listing.image_paths.length > 1 && <div className="mt-3 flex gap-2">{listing.image_paths.map((p, i) => (
              <button key={p} onClick={() => setPhoto(i)} aria-label={`Photo ${i + 1}`} className={`press w-20 overflow-hidden border-2 ${i === photo ? "border-cobalt" : "border-transparent"}`}>
                <Photo src={imageUrl(p)} label={`Photo ${i + 1}`} className="aspect-square w-full" />
              </button>))}</div>}
          </div>
          <div className="flex flex-col">
            <h1 className="display text-3xl sm:text-4xl">{listing.title}</h1>
            <p className="mt-4 text-3xl font-semibold tracking-tight text-cobalt-ink">{usd(listing.price_usd)}</p>
            <p className="mt-5 text-base leading-relaxed">{listing.description}</p>
            <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 border-t border-line pt-5 text-base">
              <dt className="text-muted">Described as</dt><dd>{listing.stated_material.replaceAll("_", " ")}</dd>
              <dt className="text-muted">Ships from</dt><dd>{listing.ship_from}</dd>
              {seller && <><dt className="text-muted">Seller</dt><dd>{seller.name}{seller.location ? `, ${seller.location}` : ""}</dd></>}
            </dl>
            <div className="mt-8">
              <button onClick={run} disabled={busy} className="press min-h-12 bg-cobalt px-6 py-3 text-base font-semibold text-bg hover:bg-cobalt-ink">{busy ? "Starting…" : "Run review"}</button>
              {note && <p role="status" className="mt-4 border-l-2 border-amber bg-amber-tint px-3 py-2 text-amber-ink">{note}</p>}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
