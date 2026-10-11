"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Photo } from "@/components/Photo";
import { imageUrl } from "@/lib/api";
import { DEMO_CASES } from "@/lib/demoCases";
import { loadListings } from "@/lib/stubs";
import type { Listing } from "@/lib/types";

const OUTCOMES = [
  { name: "File", tone: "text-red", rule: "All three agents say file.", ask: "You approve it before anything is sent." },
  { name: "Contested", tone: "text-amber-ink", rule: "One says file, another says dismiss.", ask: "You decide, with each side's best argument." },
  { name: "Watchlist", tone: "text-cobalt-ink", rule: "Something is open; no file-versus-dismiss split.", ask: "Stays listed until something changes." },
  { name: "Dismiss", tone: "text-green", rule: "All three say it looks legal.", ask: "Cleared and logged." },
];

const EXAMPLE = DEMO_CASES[0];

export default function Landing() {
  const [l, setL] = useState<Listing | null>(null);
  useEffect(() => { loadListings().then(({ data }) => setL(data.find((r) => r.listing.id === EXAMPLE.listingId)?.listing ?? null)).catch(() => setL(null)); }, []);
  return (
    <main className="h-[calc(100dvh-3.5rem)] overflow-y-auto">
      <section className="mx-auto grid max-w-7xl items-center gap-12 px-5 py-14 sm:px-8 lg:min-h-[calc(100dvh-3.5rem-9rem)] lg:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-7">
          <h1 className="serif max-w-[16ch] text-[clamp(2.75rem,6vw,5.25rem)] font-extrabold leading-[0.98] tracking-[-0.035em] [text-wrap:balance]">
            They can hide the word ivory. They can&rsquo;t hide the price.
          </h1>
          <p className="max-w-[44ch] text-lg text-muted">Three agents with opposing goals review each flagged listing. A person approves anything that gets filed.</p>
          <div className="flex flex-wrap gap-3">
            <Link href="/desk" className="press inline-flex min-h-12 items-center bg-ink px-6 font-semibold text-surface hover:bg-ink-2">Open the review desk</Link>
            <Link href="/replay/d1_network" className="press inline-flex min-h-12 items-center border border-ink px-6 font-semibold hover:bg-surface">Watch an example</Link>
          </div>
        </div>
        <figure className="relative w-full max-w-xl justify-self-center border border-ink bg-surface lg:justify-self-end">
          <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? EXAMPLE.label} className="aspect-[4/3] w-full" />
          <figcaption className="border-t border-ink px-4 py-3">
            <p className="font-semibold">{l?.title ?? EXAMPLE.label}{l ? <span className="mono ml-3 font-normal text-muted">${l.price_usd.toLocaleString()}</span> : null}</p>
            <p className="mt-1 text-muted">{EXAMPLE.blurb}</p>
          </figcaption>
          <span className="tent absolute left-3 top-3">Price</span>
          <span className="tent absolute right-3 top-3">Photo</span>
        </figure>
      </section>

      <section className="border-t border-ink bg-surface">
        <dl className="mx-auto grid max-w-7xl px-5 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
          {OUTCOMES.map((o) => (
            <div key={o.name} className="border-b border-line py-5 pr-6 last:border-b-0 lg:border-b-0 lg:border-r lg:px-6 lg:first:pl-0 lg:last:border-r-0">
              <dt className={`serif text-2xl font-bold ${o.tone}`}>{o.name}</dt>
              <dd className="mt-1 text-muted">{o.rule}</dd>
              <dd className="mt-1 font-medium">{o.ask}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}
