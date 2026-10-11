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
      <section className="mx-auto grid max-w-7xl items-center gap-8 px-5 pb-10 pt-8 sm:px-8 lg:min-h-[calc(100dvh-3.5rem)] lg:grid-cols-[1fr_1.05fr]">
        <div className="relative z-10 flex flex-col gap-8 lg:-mr-24">
          <h1 className="serif text-[clamp(3.25rem,8vw,7.5rem)] leading-[0.92] tracking-[-0.035em] [text-wrap:balance]">
            Hide the word. <em className="text-cobalt-ink">Not the price.</em>
          </h1>
          <p className="max-w-[42ch] text-xl text-muted">Three agents with opposing goals argue over each flagged wildlife listing. A person approves anything that gets filed.</p>
          <div className="flex flex-wrap gap-3">
            <Link href="/desk" className="press inline-flex min-h-12 items-center bg-ink px-7 text-base font-semibold text-bg hover:bg-ink-2">Open the review desk</Link>
            <Link href="/replay/d1_network" className="press inline-flex min-h-12 items-center px-3 text-base font-semibold underline decoration-1 underline-offset-4 hover:text-cobalt-ink">Watch an example</Link>
          </div>
        </div>
        <div className="relative justify-self-center lg:scale-110 lg:justify-self-end">
          <WildlifeSignal />
          <span className="tent lock absolute left-[8%] top-[18%]" style={{ animationDelay: "300ms" }}>Price</span>
          <span className="tent lock absolute right-[10%] top-[26%]" style={{ animationDelay: "600ms" }}>Photo</span>
          <span className="tent lock absolute bottom-[16%] left-[16%]" style={{ animationDelay: "900ms" }}>Wording</span>
        </div>
      </section>

      <section className="border-t border-ink">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[minmax(0,26rem)_1fr] lg:gap-20">
          <figure className="lg:sticky lg:top-20 lg:self-start">
            <Photo src={imageUrl(l?.image_paths[0] ?? "")} label={l?.title ?? EXAMPLE.label} className="aspect-[4/5] w-full border border-line" />
            <figcaption className="mt-3 flex items-baseline justify-between gap-4">
              <span className="font-semibold">{l?.title ?? EXAMPLE.label}</span>
              {l && <span className="serif text-3xl">${l.price_usd.toLocaleString()}</span>}
            </figcaption>
            <p className="mt-1 text-muted">{EXAMPLE.blurb}</p>
          </figure>
          <div>
            <p className="serial">Every review ends one of four ways</p>
            <dl className="mt-4 border-t border-ink">
              {OUTCOMES.map((o) => (
                <div key={o.name} className="grid gap-x-8 gap-y-1 border-b border-line py-7 sm:grid-cols-[minmax(0,15rem)_1fr]">
                  <dt className={`serif text-5xl leading-none ${o.tone}`}>{o.name}</dt>
                  <dd><p className="text-lg">{o.rule}</p><p className="mt-1 text-muted">{o.ask}</p></dd>
                </div>
              ))}
            </dl>
            <Link href="/desk" className="press mt-8 inline-flex min-h-11 items-center border-b border-ink font-semibold hover:text-cobalt-ink">Open the review desk &rarr;</Link>
          </div>
        </div>
      </section>
    </main>
  );
}
