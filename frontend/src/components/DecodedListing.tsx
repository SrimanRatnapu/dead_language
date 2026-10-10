"use client";
import { useState } from "react";
import Link from "next/link";
import { imageUrl } from "@/lib/api";
import { usd } from "@/lib/agents";
import type { CaseState } from "@/lib/caseState";
import { Photo } from "./Photo";

interface Mark { text: string; gloss: string }

// Wrap each coded phrase in <ruby> (native interlinear annotation) once evidence explains it.
function annotate(description: string, marks: Mark[]): React.ReactNode[] {
  const lower = description.toLowerCase();
  const found = marks
    .map((m) => ({ ...m, at: lower.indexOf(m.text.toLowerCase()) }))
    .filter((m) => m.at >= 0)
    .sort((a, b) => a.at - b.at);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  for (const m of found) {
    if (m.at < cursor) continue;
    out.push(description.slice(cursor, m.at));
    out.push(
      <ruby key={m.at} className="decoded px-0.5">
        {description.slice(m.at, m.at + m.text.length)}
        <rt>{m.gloss}</rt>
      </ruby>,
    );
    cursor = m.at + m.text.length;
  }
  out.push(description.slice(cursor));
  return out;
}

export function DecodedListing({ state, onOpenEvidence }: { state: CaseState; onOpenEvidence: (id: string) => void }) {
  const { listing, seller, removed, evidence, evidenceOrder } = state;
  const [selected, setSelected] = useState(0);
  if (!listing) return <p className="p-6 text-muted">Loading listing…</p>;

  const all = evidenceOrder.map((id) => evidence[id]);
  const exams = all.filter((e) => e.capability === "material_exam" && typeof e.data.photo_index === "number");
  const verdictExam = [...exams].reverse().find((e) => e.data.material !== "cannot_tell");
  const examHere = [...exams].reverse().find((e) => e.data.photo_index === selected);
  const ratio = all.find((e) => e.capability === "price_check")?.data.ratio_to_median;
  const linked = all.find((e) => e.capability === "linked_sellers");
  const phrases = (linked?.data.shared_phrases as string[] | undefined) ?? [];
  const nLinked = (linked?.data.linked_sellers as string[] | undefined)?.length ?? 0;
  const material = verdictExam ? String(verdictExam.data.material).replaceAll("_", " ") : null;
  const stated = listing.stated_material.replaceAll("_", " ");

  const marks: Mark[] = [
    ...phrases.map((p) => ({ text: p, gloss: `used by ${nLinked} other seller${nLinked === 1 ? "" : "s"}` })),
    ...(material ? [{ text: stated, gloss: `photo says ${material}` }] : []),
  ];

  return (
    <div className="relative flex flex-col gap-5 p-6">
      <Link href="/" className="w-fit text-muted hover:text-ink">← Back</Link>

      {removed && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 bg-bg/90 p-6 text-center">
          <p className="display text-3xl">Removed by seller</p>
          <p className="text-muted">
            The page was saved first.{" "}
            <button onClick={() => onOpenEvidence(evidenceOrder[0])} className="underline underline-offset-2">View snapshot</button>
          </p>
          {removed.relisted_as && <p className="text-muted">It has already reappeared under a new account.</p>}
        </div>
      )}

      {listing.image_paths.length > 0 && (
        <div className="flex flex-col gap-2">
          <Photo src={imageUrl(listing.image_paths[selected])} label={`Photo ${selected + 1}`} className="aspect-[4/3] w-full rounded-xl" caption="Photo unavailable offline" />
          {examHere && (
            <button onClick={() => onOpenEvidence(examHere.id)} className="rise rounded-lg bg-amber-tint px-3 py-2 text-left font-medium text-amber-ink">
              Examiner: {String(examHere.data.features)}
            </button>
          )}
          {listing.image_paths.length > 1 && (
            <div className="flex gap-2">
              {listing.image_paths.map((p, i) => (
                <button
                  key={p}
                  onClick={() => setSelected(i)}
                  aria-label={`Show photo ${i + 1}`}
                  aria-pressed={i === selected}
                  className={`press overflow-hidden rounded-md border-2 ${exams.some((e) => e.data.photo_index === i) ? "border-amber" : i === selected ? "border-ink" : "border-transparent"}`}
                >
                  <Photo src={imageUrl(p)} label={`Photo ${i + 1}`} className="size-12" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <h1 className="display text-[2rem]">{listing.title}</h1>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-2xl font-semibold tracking-tight">{usd(listing.price_usd)}</span>
          {typeof ratio === "number" && (
            <span className="rise font-medium text-amber-ink">{ratio.toFixed(ratio < 10 ? 1 : 0)}× the usual price</span>
          )}
        </div>
        <p className="mt-1 text-muted">
          Listed as <span className={material ? "text-ink line-through decoration-amber decoration-2" : "text-ink"}>{stated}</span>
          {material && <span className="rise font-semibold text-amber-ink"> → looks like {material}</span>}
        </p>
      </div>

      <p className="text-[1.05rem] leading-[2.6]">{annotate(listing.description, marks)}</p>

      <p className="text-muted">
        Sold by {seller?.name}, shipping from {listing.ship_from}.
        {listing.is_reconstructed && " Reconstructed from a documented case."}
      </p>
    </div>
  );
}
