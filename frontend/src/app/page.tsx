"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { WildlifeSignal } from "@/components/WildlifeSignal";
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
      <section className="mx-auto grid max-w-7xl items-center gap-10 px-5 py-12 sm:px-8 lg:min-h-[calc(100dvh-3.5rem-8rem)] lg:grid-cols-[1.05fr_1fr]">
        <div className="flex flex-col gap-7">
          <h1 className="serif text-[clamp(3rem,7.2vw,6.5rem)] leading-[0.94] tracking-[-0.03em] [text-wrap:balance]">
            They can hide the word ivory. They can&rsquo;t hide the <em>price</em>.
          </h1>
          <p className="max-w-[44ch] text-lg text-muted">Three agents with opposing goals review each flagged listing. A person approves anything that gets filed.</p>
          <div className="flex flex-wrap gap-3">
            <Link href="/desk" className="press inline-flex min-h-12 items-center bg-ink px-6 font-semibold text-bg hover:bg-ink-2">Open the review desk</Link>
            <Link href="/replay/d1_network" className="press inline-flex min-h-12 items-center border border-ink px-6 font-semibold hover:bg-surface">Watch an example</Link>
          </div>
        </div>
        <div className="relative justify-self-center lg:justify-self-end">
          <WildlifeSignal />
          <span className="tent lock absolute left-[6%] top-[14%]" style={{ animationDelay: "300ms" }}>Price</span>
          <span className="tent lock absolute right-[8%] top-[24%]" style={{ animationDelay: "600ms" }}>Photo</span>
          <span className="tent lock absolute bottom-[14%] left-[14%]" style={{ animationDelay: "900ms" }}>Wording</span>
        </div>
      </section>

      <section className="border-t border-ink">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-14 sm:px-8 lg:grid-cols-[1.2fr_1fr] lg:items-center">
          <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? EXAMPLE.label} className="aspect-[4/3] w-full border border-line" />
          <div>
            <p className="serial">Case of record</p>
            {l && <p className="serif mt-2 text-7xl leading-none">${l.price_usd.toLocaleString()}</p>}
            <h2 className="mt-4 text-lg font-semibold">{l?.title ?? EXAMPLE.label}</h2>
            <p className="mt-2 max-w-[40ch] text-muted">{EXAMPLE.blurb}</p>
            <Link href="/replay/d1_network" className="press mt-6 inline-flex min-h-11 items-center border-b border-ink font-semibold hover:text-cobalt-ink">Watch the review &rarr;</Link>
          </div>
        </div>
      </section>

      <section className="border-t border-ink bg-surface">
        <dl className="mx-auto grid max-w-7xl px-5 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
          {OUTCOMES.map((o) => (
            <div key={o.name} className="border-b border-line py-6 pr-6 last:border-b-0 lg:border-b-0 lg:border-r lg:px-6 lg:first:pl-0 lg:last:border-r-0">
              <dt className={`serif text-4xl ${o.tone}`}>{o.name}</dt>
              <dd className="mt-2 text-muted">{o.rule}</dd>
              <dd className="mt-1 font-medium">{o.ask}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}
